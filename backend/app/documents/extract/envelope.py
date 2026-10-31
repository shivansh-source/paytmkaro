"""Bridge: ExtractionResult -> DocumentEnvelope (the team's contract, app.schemas.documents).

Extraction hands over RAW values with confidence and a box; it does not decide anything. A field that
could not be read becomes Extracted(value=None, confidence=0) so validation can report it; nothing is
invented. Validation (not this module) computes status, checks and transaction tags: envelopes leave
here as "needs_review" (or "failed" with an error).

Conversions
- type: gst_certificate->gst_registration, gstr_3b->gstr3b, itr->itr_v, udyam_certificate->udyam,
  pan_card/aadhaar/bank_statement unchanged. Other types (bureau, financials, sanction letter,
  settlements) have no envelope slot: the bridge returns None.
- source: text_layer->parser, ocr->ocr, vlm->vlm, computed->system.
- bbox: OCR pixel box on Page.image_png -> page fractions 0-1, page = index + 1; None when there is no
  unambiguous box (never fabricated).
- raw_text: the value as read, before normalising (kept when a letter/digit swap was repaired).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from statistics import mean
from typing import Any

from app.documents.extract.common import money, parse_date
from app.documents.extract.pipeline import Extraction
from app.documents.models import DocumentType as DT
from app.documents.models import ExtractionResult, FieldSource, LoadedDocument, OcrLine, Page, SourceFormat, TextSource
from app.schemas.common import Address, BBox, DocumentType, Extracted, RowProvenance, Source
from app.schemas.documents import (
    Aadhaar,
    BankStatement,
    DocumentEnvelope,
    FileInfo,
    GstRegistration,
    Gstr3b,
    Gstr3bMonth,
    ItrV,
    PanCard,
    Transaction,
    Triage,
    Udyam,
)

ENVELOPE_TYPE: dict[DT, DocumentType] = {
    DT.PAN_CARD: DocumentType.PAN_CARD,
    DT.AADHAAR: DocumentType.AADHAAR,
    DT.GST_CERTIFICATE: DocumentType.GST_REGISTRATION,
    DT.GSTR_3B: DocumentType.GSTR3B,
    DT.ITR: DocumentType.ITR_V,
    DT.BANK_STATEMENT: DocumentType.BANK_STATEMENT,
    DT.UDYAM_CERTIFICATE: DocumentType.UDYAM,
}

SOURCE: dict[FieldSource, Source] = {
    FieldSource.TEXT_LAYER: Source.PARSER,
    FieldSource.OCR: Source.OCR,
    FieldSource.VLM: Source.VLM,
    FieldSource.COMPUTED: Source.SYSTEM,
}

MIME: dict[SourceFormat, str] = {
    SourceFormat.PDF: "application/pdf",
    SourceFormat.JPEG: "image/jpeg",
    SourceFormat.PNG: "image/png",
    SourceFormat.WEBP: "image/webp",
    SourceFormat.TIFF: "image/tiff",
    SourceFormat.BMP: "image/bmp",
    SourceFormat.HEIC: "image/heic",
    SourceFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    SourceFormat.DOC: "application/msword",
    SourceFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    SourceFormat.XLS: "application/vnd.ms-excel",
    SourceFormat.CSV: "text/csv",
    SourceFormat.TXT: "text/plain",
}
_IMAGE_FORMATS = {SourceFormat.JPEG, SourceFormat.PNG, SourceFormat.WEBP, SourceFormat.TIFF, SourceFormat.BMP, SourceFormat.HEIC}
_CONSTITUTIONS = {"proprietorship", "partnership", "llp", "pvt_ltd", "public_ltd", "huf", "trust", "society"}
INFERRED_DIRECTION_CONFIDENCE = 0.8  # a debit/credit decided by narration words, not by the balance, is less certain


@dataclass
class BridgeOutput:
    envelope: DocumentEnvelope
    # What the extractor read but the envelope cannot represent, or had to leave out.
    notes: list[str] = field(default_factory=list)


def has_envelope(document_type: DT) -> bool:
    return document_type in ENVELOPE_TYPE


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def _date_variants(d: date) -> list[str]:
    return [d.strftime("%d/%m/%Y"), d.strftime("%d-%m-%Y"), d.strftime("%d-%b-%Y"), d.strftime("%d %B %Y"), d.strftime("%d.%m.%Y"), d.isoformat()]


def _candidates(value: Any, raw: str | None) -> list[str]:
    out: list[str] = [raw] if raw else []
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, str):
        if (d := parse_date(value)) is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            out += _date_variants(d)
        else:
            out.append(value)
    elif isinstance(value, (int, float)):
        out += [f"{value:.2f}", money(value).lstrip("₹-")]
        if float(value).is_integer():
            out.append(str(int(value)))
    return [c for c in out if len(_norm(c)) >= 4]


def _fraction(value: float, size: int) -> float:
    return min(max(value / size, 0.0), 1.0)


@dataclass
class _Ctx:
    result: ExtractionResult
    raw: dict[str, str]
    document: LoadedDocument
    pages: list[Page]
    default_source: Source
    notes: list[str]

    def page(self, index: int | None) -> Page | None:
        return next((p for p in self.pages if p.index == index), None) if index is not None else None

    def box(self, page: Page | None, line: OcrLine) -> BBox | None:
        if page is None or not page.width or not page.height:
            return None
        x0, y0, x1, y1 = line.bbox
        return BBox(
            page=page.index + 1,
            x0=_fraction(min(x0, x1), page.width), y0=_fraction(min(y0, y1), page.height),
            x1=_fraction(max(x0, x1), page.width), y1=_fraction(max(y0, y1), page.height),
        )

    def find_box(self, page_index: int | None, candidates: list[str], *, also: list[str] = ()) -> BBox | None:
        """The one OCR box whose text contains a candidate (and, when given, one of `also`)."""
        page = self.page(page_index)
        if page is None or not page.ocr_lines:
            return None
        wanted = [_norm(c) for c in candidates]
        extra = [_norm(a) for a in also]
        hits: list[OcrLine] = []
        for line in page.ocr_lines:
            text = _norm(line.text)
            if any(w and w in text for w in wanted) and (not extra or any(e in text for e in extra)):
                hits.append(line)
        if not hits:
            return None
        tightest = min(len(_norm(h.text)) for h in hits)
        best = {h.bbox for h in hits if len(_norm(h.text)) == tightest}
        return self.box(page, next(h for h in hits if h.bbox in best)) if len(best) == 1 else None

    def x(self, name: str, convert: Callable[[Any], Any] | None = None, *, required: bool = True, boxed: bool = True) -> Extracted | None:
        f = self.result.fields.get(name)
        if f is None:
            return Extracted(value=None, confidence=0.0, source=self.default_source, raw_text=self.raw.get(name)) if required else None
        try:
            value = convert(f.value) if convert else f.value
        except (ValueError, TypeError, KeyError):
            value = None
        if value is None:
            self.notes.append(f"{name}: read as {str(f.value)[:40]!r} but it does not fit the envelope type; left empty")
        bbox = self.find_box(f.page_index, _candidates(f.value, self.raw.get(name))) if boxed and value is not None else None
        return Extracted(
            value=value, confidence=f.confidence if value is not None else 0.0, source=SOURCE[f.source],
            bbox=bbox, raw_text=self.raw.get(name),
        )

    def address(self, text_field: str, *, state_field: str | None = "state", pincode_field: str = "pincode") -> Extracted | None:
        f = self.result.fields.get(text_field)
        if f is None:
            return Extracted(value=None, confidence=0.0, source=self.default_source)
        pin = self.result.fields.get(pincode_field)
        state = self.result.fields.get(state_field) if state_field else None
        value = Address(text=str(f.value), pincode=pin.value if pin else None, state=str(state.value) if state else None)
        return Extracted(
            value=value, confidence=f.confidence, source=SOURCE[f.source],
            bbox=self.find_box(f.page_index, [str(f.value)[:40]]), raw_text=self.raw.get(text_field),
        )

    def provenance(self, source: str | None, confidence: float, bbox: BBox | None = None) -> RowProvenance:
        try:
            src = SOURCE[FieldSource(source)] if source else self.default_source
        except ValueError:
            src = self.default_source
        return RowProvenance(source=src, confidence=min(max(confidence, 0.0), 1.0), bbox=bbox)


def _iso(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _last4(value: Any) -> str | None:
    text = str(value)
    return text if re.fullmatch(r"\d{4}", text) else None


def _constitution(value: Any) -> str:
    return value if value in _CONSTITUTIONS else "other"


def _gender(value: Any) -> str | None:
    return {"male": "male", "female": "female", "transgender": "other"}.get(str(value))


# ---------- per-type builders ----------


def _pan(c: _Ctx) -> PanCard:
    return PanCard(
        pan_number=c.x("pan"), name=c.x("name"), father_name=c.x("father_name", required=False), dob=c.x("dob", _iso),
    )


def _aadhaar(c: _Ctx) -> Aadhaar:
    flags = [flag for p in c.pages for flag in p.aadhaar_verhoeff_valid]
    dob: Extracted | None = c.x("dob", _iso)
    year_of_birth: Extracted | None = None
    if dob.value is None and "year_of_birth" in c.result.fields:
        # The card prints only a year: report that, and do not ask the SME to confirm a date that was never printed.
        year_of_birth = c.x("year_of_birth", int, boxed=False)
        dob = None
    return Aadhaar(
        aadhaar_last4=c.x("aadhaar_last4", _last4, boxed=False),
        verhoeff_valid=all(flags) if flags else None,
        name=c.x("name"), dob=dob, year_of_birth=year_of_birth, gender=c.x("gender", _gender, required=False, boxed=False), address=c.address("address", state_field=None),
    )


def _gst(c: _Ctx) -> GstRegistration:
    return GstRegistration(
        gstin=c.x("gstin"), legal_name=c.x("legal_name"), trade_name=c.x("trade_name", required=False),
        constitution=c.x("constitution_of_business", _constitution, boxed=False), registration_date=c.x("registration_date", _iso),
        principal_address=c.address("address"),
    )


def _gstr3b(c: _Ctx) -> Gstr3b:
    months = [
        Gstr3bMonth(
            period=row["period"], outward_taxable_value=row["taxable_outward_value"],
            provenance=c.provenance(row.get("source"), row.get("confidence", 0.8)),
        )
        for row in c.result.tables.get("periods", [])
    ]
    return Gstr3b(gstin=c.x("gstin"), months=months)


def _bank(c: _Ctx) -> BankStatement:
    rows = []
    no_balance = 0
    for row in c.result.tables.get("transactions", []):
        no_balance += row.get("balance") is None  # kept: its credit or debit still counts, only the running balance is unknown
        narration = row.get("narration") or ""
        confidence = row.get("confidence", 0.8)
        if row.get("direction_inferred"):
            confidence = min(confidence, INFERRED_DIRECTION_CONFIDENCE)
        bbox = None
        if row.get("page_index") is not None and len(_norm(row.get("narration") or "")) >= 6:
            bbox = c.find_box(row["page_index"], [(row["narration"] or "")[:24]], also=_date_variants(_iso(row["date"])))
        rows.append(
            Transaction(
                date=_iso(row["date"]), narration=narration, ref=(str(row["ref"]).strip() or None) if row.get("ref") else None, debit=row.get("debit") or 0.0, credit=row.get("credit") or 0.0,
                balance=row.get("balance"), tags=[], provenance=c.provenance(row.get("source"), confidence, bbox),
            )
        )
    if no_balance:
        c.notes.append(f"{no_balance} of {len(rows)} transactions have no printed balance; they are kept without one")
    return BankStatement(
        account_holder_name=c.x("account_holder_name"), account_number_last4=c.x("account_number_last4", _last4, boxed=False),
        ifsc=c.x("ifsc"), bank_name=c.x("bank_name", required=False), period_from=c.x("period_from", _iso, boxed=False),
        period_to=c.x("period_to", _iso, boxed=False), opening_balance=c.x("opening_balance", float, required=False), closing_balance=c.x("closing_balance", float),
        transactions=rows,
    )


def _udyam(c: _Ctx) -> Udyam:
    return Udyam(
        udyam_number=c.x("udyam_number"), enterprise_name=c.x("enterprise_name"), enterprise_type=c.x("enterprise_type"),
        major_activity=c.x("major_activity"), date_of_incorporation=c.x("date_of_incorporation", _iso, required=False),
        date_of_registration=c.x("registration_date", _iso, required=False), address=c.address("address"),
    )


def _itr(c: _Ctx) -> ItrV:
    return ItrV(
        pan_number=c.x("pan"), assessment_year=c.x("assessment_year"), itr_form=c.x("form_type"),
        gross_total_income=c.x("gross_total_income", float), acknowledgement_number=c.x("acknowledgement_number"),
        filing_date=c.x("filing_date", _iso, required=False),
    )


BUILDERS: dict[DT, Callable[[_Ctx], Any]] = {
    DT.PAN_CARD: _pan, DT.AADHAAR: _aadhaar, DT.GST_CERTIFICATE: _gst, DT.GSTR_3B: _gstr3b,
    DT.ITR: _itr, DT.BANK_STATEMENT: _bank, DT.UDYAM_CERTIFICATE: _udyam,
}


# ---------- triage and file info ----------


def _input_kind(document: LoadedDocument, pages: list[Page]) -> str:
    if document.source_format in _IMAGE_FORMATS:
        return "photo"
    if document.source_format == SourceFormat.PDF:
        return "digital_pdf" if pages and all(p.text_source == TextSource.NATIVE for p in pages) else "scanned_pdf"
    if document.source_format in (SourceFormat.XLSX, SourceFormat.XLS, SourceFormat.CSV):
        return "spreadsheet"
    if document.source_format in (SourceFormat.DOCX, SourceFormat.DOC):
        return "word"
    return "text"


def _triage(result: ExtractionResult, document: LoadedDocument, pages: list[Page], password_protected: bool) -> Triage:
    sources = [f.source for f in result.fields.values() if f.source != FieldSource.COMPUTED]
    sources += [FieldSource(r["source"]) for rows in result.tables.values() for r in rows if r.get("source") in {s.value for s in FieldSource}]
    vlm_fields = [n for n, f in result.fields.items() if f.source == FieldSource.VLM]
    counts = {s: sources.count(s) for s in (FieldSource.TEXT_LAYER, FieldSource.OCR, FieldSource.VLM)}
    if any(counts.values()):
        top = max(counts.values())
        winner = next(s for s in (FieldSource.TEXT_LAYER, FieldSource.OCR, FieldSource.VLM) if counts[s] == top)
    else:
        winner = FieldSource.TEXT_LAYER if pages and all(p.text_source == TextSource.NATIVE for p in pages) else FieldSource.OCR
    scores = [line.confidence for p in pages for line in p.ocr_lines]
    fell_back = counts[FieldSource.VLM] > 0
    return Triage(
        input_kind=_input_kind(document, pages),
        extractor=SOURCE[winner],
        fell_back_to_vlm=fell_back,
        fallback_reason=(f"required fields missing or low-confidence after the text pass were read by the VLM: {', '.join(vlm_fields)}" if fell_back and vlm_fields else ("table rows read by the VLM" if fell_back else None)),
        ocr_mean_confidence=round(mean(scores), 3) if scores else None,
        password_protected=password_protected,
    )


def build_envelope(
    extraction: Extraction | ExtractionResult,
    document: LoadedDocument,
    *,
    sme_id: str,
    document_id: str,
    uploaded_at: datetime | None = None,
    page_indexes: list[int] | None = None,
    size_bytes: int | None = None,
    password_protected: bool = False,
) -> BridgeOutput | None:
    """The envelope for one extracted document (or one segment of a bundle), or None when the
    envelope has no slot for this document type."""
    result, raw = (extraction.result, extraction.raw) if isinstance(extraction, Extraction) else (extraction, {})
    if result.document_type not in ENVELOPE_TYPE:
        return None
    pages = [p for p in document.pages if page_indexes is None or p.index in page_indexes]
    triage = _triage(result, document, pages, password_protected)
    file = FileInfo(
        file_name=document.file_name, mime_type=MIME.get(document.source_format, "application/octet-stream"),
        size_bytes=size_bytes or 0, pages=len(document.pages) or None, sha256=document.sha256,
    )
    base = dict(
        document_id=document_id, sme_id=sme_id, document_type=ENVELOPE_TYPE[result.document_type],
        uploaded_at=uploaded_at or datetime.now(timezone.utc), file=file, triage=triage,
    )
    if result.status == "failed":
        error = result.warnings[0] if result.warnings else "No fields could be read from this document."
        return BridgeOutput(DocumentEnvelope(**base, status="failed", data=None, error=error), list(result.warnings))

    ctx = _Ctx(result, raw, document, pages, triage.extractor, [])
    data = BUILDERS[result.document_type](ctx)
    return BridgeOutput(DocumentEnvelope(**base, status="needs_review", data=data), ctx.notes)


def to_envelope(extraction: Extraction | ExtractionResult, document: LoadedDocument, **kwargs: Any) -> DocumentEnvelope | None:
    out = build_envelope(extraction, document, **kwargs)
    return out.envelope if out else None
