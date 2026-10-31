"""ExtractionResult (the document pipeline's output) -> DocumentEnvelope (what validation and scoring read).

The only place that knows both shapes. Field names, enums and sources are mapped here; nothing is
guessed. Rules:
- A field that was read and passed the extractor's checks keeps its value, confidence and source.
- A field that was read but failed them (a PAN read as "ABCPK12E4F") is kept at low confidence, so
  validation shows ✗ and the SME can fix it, instead of the field silently going missing. Text fields keep
  the raw read as the value; dates and amounts keep it only as `raw_text`.
- A required field nobody could read becomes value=None (validation reports it, `needs_review` is set).
- Boxes (`bbox`) are best effort: only OCR'd pages have positions, so text-layer PDFs get none.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from statistics import mean
from typing import Any

from app.documents.extract.pipeline import Extraction
from app.documents.models import DocumentType as PipelineType
from app.documents.models import FieldSource, LoadedDocument, Page, SourceFormat, TextSource
from app.schemas import DocumentEnvelope, DocumentType, Source
from app.schemas.documents import FileInfo, Triage

# Pipeline type -> envelope type. Types missing here (bureau report, financial statements, sanction
# letter, settlement report) are read by the pipeline but have no envelope slot yet.
TYPE_MAP: dict[PipelineType, DocumentType] = {
    PipelineType.PAN_CARD: DocumentType.PAN_CARD,
    PipelineType.AADHAAR: DocumentType.AADHAAR,
    PipelineType.GST_CERTIFICATE: DocumentType.GST_REGISTRATION,
    PipelineType.GSTR_3B: DocumentType.GSTR3B,
    PipelineType.BANK_STATEMENT: DocumentType.BANK_STATEMENT,
    PipelineType.UDYAM_CERTIFICATE: DocumentType.UDYAM,
    PipelineType.ITR: DocumentType.ITR_V,
}
PIPELINE_TYPE = {ours: theirs for theirs, ours in TYPE_MAP.items()}

SOURCE = {
    FieldSource.TEXT_LAYER: Source.PARSER,
    FieldSource.OCR: Source.OCR,
    FieldSource.VLM: Source.VLM,
    FieldSource.COMPUTED: Source.SYSTEM,
}
REJECTED_CONFIDENCE = 0.3  # read, but failed a format / checksum check: always needs review
MIME = {
    SourceFormat.PDF: "application/pdf", SourceFormat.JPEG: "image/jpeg", SourceFormat.PNG: "image/png",
    SourceFormat.WEBP: "image/webp", SourceFormat.TIFF: "image/tiff", SourceFormat.BMP: "image/bmp",
    SourceFormat.HEIC: "image/heic", SourceFormat.CSV: "text/csv", SourceFormat.TXT: "text/plain",
    SourceFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    SourceFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    SourceFormat.XLS: "application/vnd.ms-excel",
}
IMAGES = {SourceFormat.JPEG, SourceFormat.PNG, SourceFormat.WEBP, SourceFormat.TIFF, SourceFormat.BMP, SourceFormat.HEIC}
# Pipeline constitutions with no exact envelope value. An OPC is legally a private limited company.
CONSTITUTION = {"opc": "pvt_ltd", "aop": "other", "government": "other", "foreign_company": "other"}
GENDER = {"transgender": "other"}


class _Fields:
    """Builds `Extracted` dicts for one extraction result."""

    def __init__(self, extraction: Extraction, pages: dict[int, Page]):
        self.result = extraction.result
        self.raw = extraction.raw
        self.rejected = extraction.rejected
        self.pages = pages
        self.default_source = _main_source(extraction)

    def get(self, name: str, *, text: bool = False, convert=None, required: bool = True) -> dict[str, Any] | None:
        """`text`: the target is a string, so a rejected read can be kept as the value."""
        if (f := self.result.fields.get(name)) is not None:
            raw = self.raw.get(name)
            return {
                "value": convert(f.value) if convert else f.value,
                "confidence": f.confidence,
                "source": SOURCE[f.source],
                "raw_text": raw,
                "bbox": _locate(self.pages.get(f.page_index), raw or str(f.value)),
            }
        if (r := self.rejected.get(name)) is not None:
            return {
                "value": r.raw if text else None,
                "confidence": REJECTED_CONFIDENCE,
                "source": SOURCE[r.source],
                "raw_text": r.raw,
                "bbox": _locate(self.pages.get(r.page_index), r.raw),
            }
        return self.missing() if required else None

    def missing(self) -> dict[str, Any]:
        return {"value": None, "confidence": 0.0, "source": self.default_source}

    def value(self, name: str) -> Any:
        f = self.result.fields.get(name)
        return f.value if f else None


def _address(fields: _Fields, name: str = "address") -> dict[str, Any]:
    field = fields.get(name, text=True)
    if field["value"] is not None:
        field["value"] = {"text": field["value"], "pincode": fields.value("pincode"), "state": fields.value("state")}
    return field


def _row_provenance(row: dict[str, Any]) -> dict[str, Any]:
    source = FieldSource(row.get("source") or FieldSource.TEXT_LAYER)
    return {"source": SOURCE[source], "confidence": row.get("confidence") or 0.8}


def _pan_card(f: _Fields, _: Extraction, __: dict[int, Page]) -> dict[str, Any]:
    return {
        "document_type": "pan_card",
        "pan_number": f.get("pan", text=True),
        "name": f.get("name", text=True),
        "father_name": f.get("father_name", text=True, required=False),
        "dob": f.get("dob"),
    }


def _aadhaar(f: _Fields, _: Extraction, pages: dict[int, Page]) -> dict[str, Any]:
    dob = f.get("dob")
    if dob["value"] is None and (year := f.value("year_of_birth")):
        dob["raw_text"] = f"year of birth {year}"  # a year is not a date: the SME confirms the full date
    flags = [ok for page in pages.values() for ok in page.aadhaar_verhoeff_valid]
    return {
        "document_type": "aadhaar",
        "aadhaar_last4": f.get("aadhaar_last4"),
        "verhoeff_valid": all(flags) if flags else None,
        "name": f.get("name", text=True),
        "dob": dob,
        "gender": f.get("gender", convert=lambda g: GENDER.get(g, g), required=False),
        "address": _address(f),
    }


def _gst_registration(f: _Fields, _: Extraction, __: dict[int, Page]) -> dict[str, Any]:
    registered = f.get("registration_date")
    if registered["value"] is None:
        registered = f.get("date_of_liability")
    return {
        "document_type": "gst_registration",
        "gstin": f.get("gstin", text=True),
        "legal_name": f.get("legal_name", text=True),
        "trade_name": f.get("trade_name", text=True, required=False),
        "constitution": f.get("constitution_of_business", convert=lambda c: CONSTITUTION.get(c, c)),
        "registration_date": registered,
        "principal_address": _address(f),
    }


def _gstr3b(f: _Fields, extraction: Extraction, _: dict[int, Page]) -> dict[str, Any]:
    months = [
        {"period": row["period"], "outward_taxable_value": row["taxable_outward_value"], "provenance": _row_provenance(row)}
        for row in extraction.result.tables.get("periods", [])
    ]
    return {"document_type": "gstr3b", "gstin": f.get("gstin", text=True), "months": months}


def _bank_statement(f: _Fields, extraction: Extraction, _: dict[int, Page]) -> dict[str, Any]:
    rows = extraction.result.tables.get("transactions", [])
    with_balance = [r for r in rows if r.get("balance") is not None]
    transactions = [
        {
            "date": r["date"],
            "narration": r.get("narration") or "",
            "debit": r.get("debit") or 0,
            "credit": r.get("credit") or 0,
            "balance": r["balance"],
            "provenance": _row_provenance(r),
        }
        for r in with_balance
    ]
    opening, closing = f.get("opening_balance"), f.get("closing_balance")
    if with_balance:
        # Statement headers often omit these; the running balance gives them exactly.
        first, last = with_balance[0], with_balance[-1]
        conf = round(mean(r.get("confidence") or 0.8 for r in (first, last)), 3)
        if opening["value"] is None:
            value = first["balance"] - (first.get("credit") or 0) + (first.get("debit") or 0)
            opening = {"value": round(value, 2), "confidence": conf, "source": Source.SYSTEM}
        if closing["value"] is None:
            closing = {"value": last["balance"], "confidence": conf, "source": Source.SYSTEM}
    return {
        "document_type": "bank_statement",
        "account_holder_name": f.get("account_holder_name", text=True),
        "account_number_last4": f.get("account_number_last4"),
        "ifsc": f.get("ifsc", text=True),
        "bank_name": f.get("bank_name", text=True, required=False),
        "period_from": f.get("period_from"),
        "period_to": f.get("period_to"),
        "opening_balance": opening,
        "closing_balance": closing,
        "transactions": transactions,
    }


def _udyam(f: _Fields, _: Extraction, __: dict[int, Page]) -> dict[str, Any]:
    return {
        "document_type": "udyam",
        "udyam_number": f.get("udyam_number", text=True),
        "enterprise_name": f.get("enterprise_name", text=True),
        "enterprise_type": f.get("enterprise_type"),
        "major_activity": f.get("major_activity"),
        "date_of_incorporation": f.get("date_of_incorporation", required=False),
        "date_of_registration": f.get("registration_date", required=False),
        "address": _address(f),
    }


def _itr_v(f: _Fields, _: Extraction, __: dict[int, Page]) -> dict[str, Any]:
    return {
        "document_type": "itr_v",
        "pan_number": f.get("pan", text=True),
        "assessment_year": f.get("assessment_year", text=True),
        "itr_form": f.get("form_type", text=True),
        "gross_total_income": f.get("gross_total_income"),
        "acknowledgement_number": f.get("acknowledgement_number", text=True),
        "filing_date": f.get("filing_date", required=False),
    }


BUILDERS = {
    DocumentType.PAN_CARD: _pan_card,
    DocumentType.AADHAAR: _aadhaar,
    DocumentType.GST_REGISTRATION: _gst_registration,
    DocumentType.GSTR3B: _gstr3b,
    DocumentType.BANK_STATEMENT: _bank_statement,
    DocumentType.UDYAM: _udyam,
    DocumentType.ITR_V: _itr_v,
}


def to_envelope(
    extraction: Extraction,
    document: LoadedDocument,
    *,
    page_indexes: list[int],
    sme_id: str,
    document_id: str,
    uploaded_at: datetime,
    size_bytes: int,
    mime_type: str | None = None,
    password_used: bool = False,
) -> DocumentEnvelope:
    """One extracted document (or one segment of a bundled file) as an envelope, ready for /v1/assess."""
    document_type = TYPE_MAP[extraction.result.document_type]
    pages = {p.index: p for p in document.pages if p.index in page_indexes}
    data = BUILDERS[document_type](_Fields(extraction, pages), extraction, pages)
    return DocumentEnvelope(
        document_id=document_id,
        sme_id=sme_id,
        document_type=document_type,
        status="needs_review",  # extraction done; validation sets verified / needs_review
        uploaded_at=uploaded_at,
        file=FileInfo(
            file_name=document.file_name,
            mime_type=mime_type or MIME.get(document.source_format, "application/octet-stream"),
            size_bytes=size_bytes,
            pages=len(pages) or None,
            sha256=document.sha256,
        ),
        triage=_triage(extraction, document, list(pages.values()), password_used),
        data=data,
    )


def _main_source(extraction: Extraction) -> Source:
    sources = Counter(f.source for f in extraction.result.fields.values() if f.source != FieldSource.COMPUTED)
    return SOURCE[sources.most_common(1)[0][0]] if sources else Source.OCR


def _triage(extraction: Extraction, document: LoadedDocument, pages: list[Page], password_used: bool) -> Triage:
    if document.source_format in IMAGES:
        kind = "photo"
    elif document.source_format == SourceFormat.PDF and not any(p.text_source == TextSource.NATIVE for p in pages):
        kind = "scanned_pdf"
    else:
        kind = "digital_pdf"  # text-native: PDF text layer, spreadsheet, Word, CSV
    fields = extraction.result.fields.values()
    used_vlm = any(f.source == FieldSource.VLM for f in fields) or any(
        r.get("source") == FieldSource.VLM for rows in extraction.result.tables.values() for r in rows
    )
    extractor = _main_source(extraction)
    ocr_conf = [line.confidence for p in pages for line in p.ocr_lines]
    return Triage(
        input_kind=kind,
        extractor=extractor if extractor in (Source.PARSER, Source.OCR, Source.VLM) else Source.OCR,
        fell_back_to_vlm=used_vlm,
        fallback_reason="text and OCR could not read every field" if used_vlm else None,
        ocr_mean_confidence=round(mean(ocr_conf), 3) if ocr_conf else None,
        password_protected=password_used,
    )


def _norm(text: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", text.upper())


def _locate(page: Page | None, needle: str | None) -> dict[str, Any] | None:
    """Box of the OCR line that contains `needle`, as page fractions. None without OCR positions."""
    if page is None or not needle or not page.ocr_lines or not page.width or not page.height:
        return None
    target = _norm(needle)
    if len(target) < 3:
        return None
    for line in page.ocr_lines:
        if target in _norm(line.text):
            x0, y0, x1, y1 = line.bbox
            w, h = page.width, page.height
            return {
                "page": page.index + 1,
                "x0": max(0.0, min(1.0, x0 / w)), "y0": max(0.0, min(1.0, y0 / h)),
                "x1": max(0.0, min(1.0, x1 / w)), "y1": max(0.0, min(1.0, y1 / h)),
            }
    return None
