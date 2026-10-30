"""Hybrid extraction: text/OCR readers first, the VLM only for what is still missing.

"The VLM reads; code decides." Every value, from either path, goes through the
same pydantic checks; aggregates (totals, counts, period ranges) are computed here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from statistics import mean
from typing import Any

from app import config
from app.documents.extract import bank
from app.documents.extract.common import (
    GST_STATES,
    PAN_HOLDER_TYPES,
    Hit,
    PageView,
    month_label,
    month_range,
    normalize_name,
    page_view,
    parse_date,
)
from app.documents.extract.prompts import build_prompt
from app.documents.extract.readers import PageRead, read_aadhaar, read_gst_certificate, read_gstr_3b, read_itr, read_pan_card
from app.documents.extract.schemas import FIELD_MODELS, FREE_TEXT, REQUIRED, TABLE_MODELS, validate_field, validate_row
from app.documents.models import DocumentType, ExtractedField, ExtractionResult, FieldSource, LoadedDocument, LoadStatus, Page, TextSource
from app.documents.ports import VlmBudgetExceeded, VlmClient, VlmError
from app.documents.privacy import mask_aadhaar_text

READERS: dict[DocumentType, Callable[[PageView], PageRead]] = {
    DocumentType.PAN_CARD: read_pan_card,
    DocumentType.AADHAAR: read_aadhaar,
    DocumentType.GST_CERTIFICATE: read_gst_certificate,
    DocumentType.GSTR_3B: read_gstr_3b,
    DocumentType.ITR: read_itr,
    DocumentType.BANK_STATEMENT: bank.read_bank_statement,
}

VLM_CONFIDENCE = 0.7  # a lone VLM read; raised when an independent text read agrees
LOW_CONFIDENCE = 0.7  # below this a required text value is cross-checked with the VLM
TRUST_TEXT_AT = 0.85  # on disagreement, an OCR value at least this confident beats the VLM
IMAGES_PER_REQUEST = 2  # 2 x 2048 image tokens + prompt + reply stays under the free tier's 8K TPM
FIELDS_MAX_TOKENS = 1024
ROWS_MAX_TOKENS = 4096  # one page of transactions; 2048 image + prompt + 4096 still fits 8K TPM


@dataclass
class Candidate:
    value: Any
    source: FieldSource
    page_index: int | None
    confidence: float
    note: str | None = None
    validated: bool = False


class _Extraction:
    def __init__(self, document_type: DocumentType):
        self.type = document_type
        self.fields: dict[str, Candidate] = {}
        self.rows: list[dict[str, Any]] = []
        self.table: list[dict[str, Any]] = []
        self.warnings: list[str] = []

    # ----- offering values -----

    def _check(self, name: str, raw: Any, origin: str) -> Any | None:
        if name not in FIELD_MODELS[self.type].model_fields:
            return None
        value, reason = validate_field(self.type, name, raw)
        if reason and reason != "empty":
            # Never echo raw values on identity documents into user-visible warnings.
            shown = "" if self.type == DocumentType.AADHAAR else f" {str(raw)[:40]!r}"
            self.warnings.append(f"{name}: {origin} read{shown} but it failed validation ({reason}); not used")
        return value

    def offer_text(self, name: str, hit: Hit, view: PageView) -> None:
        if name in self.fields:
            return
        value = self._check(name, hit.value, "the document text")
        if value is not None:
            self.fields[name] = Candidate(value, view.source, view.index, round(hit.confidence, 3), hit.note, name not in FREE_TEXT)

    def offer_vlm(self, name: str, raw: Any, page_index: int | None) -> None:
        value = self._check(name, raw, "the VLM")
        if value is None:
            return
        vlm = Candidate(value, FieldSource.VLM, page_index, VLM_CONFIDENCE, None, name not in FREE_TEXT)
        text = self.fields.get(name)
        if text is None:
            self.fields[name] = vlm
        elif _same(name, text.value, value):
            text.confidence = round(min(0.99, max(text.confidence, VLM_CONFIDENCE) + 0.1), 3)
            text.validated = True
            text.note = "; ".join(filter(None, [text.note, "text and VLM reads agree"]))
        else:
            keep_text = text.source == FieldSource.TEXT_LAYER or text.confidence >= TRUST_TEXT_AT
            kept, other = (text, vlm) if keep_text else (vlm, text)
            kept.confidence = min(kept.confidence, 0.5)
            kept.note = f"{other.source.value} read a different value; please confirm"
            self.fields[name] = kept
            self.warnings.append(
                f"{name}: {text.source.value} read {_show(self.type, text.value)}, VLM read {_show(self.type, value)}; "
                f"kept the {kept.source.value} value, please confirm"
            )

    def computed(self, name: str, value: Any, confidence: float, note: str | None = None, page_index: int | None = None) -> None:
        checked, reason = validate_field(self.type, name, value)
        if reason is None:
            self.fields[name] = Candidate(checked, FieldSource.COMPUTED, page_index, round(confidence, 3), note, True)

    # ----- what is still needed -----

    def needs(self) -> list[str]:
        needed = [n for n in REQUIRED[self.type] if n not in self.fields or self.fields[n].confidence < LOW_CONFIDENCE]
        if self.type == DocumentType.AADHAAR and "dob" not in self.fields and "year_of_birth" not in self.fields:
            needed.append("dob")
        if self.type in TABLE_MODELS and not self.rows:
            needed.append(TABLE_MODELS[self.type][0])
        return needed


def _same(name: str, a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 0.01
    if isinstance(a, str) and isinstance(b, str):
        if name in FREE_TEXT:  # names/addresses: ignore case, titles and punctuation
            return normalize_name(a) == normalize_name(b)
        return a.replace(" ", "").upper() == b.replace(" ", "").upper()
    return a == b


def _show(document_type: DocumentType, value: Any) -> str:
    return "a value" if document_type == DocumentType.AADHAAR else repr(value)


def _sanitize(value: Any, context: str) -> Any:
    """Mask any Aadhaar number anywhere in a VLM reply before it is looked at."""
    if isinstance(value, str):
        return mask_aadhaar_text(value, context or value)
    if isinstance(value, list):
        return [_sanitize(v, context) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v, context) for k, v in value.items()}
    if isinstance(value, int) and not isinstance(value, bool) and len(str(abs(value))) == 12:
        return mask_aadhaar_text(str(value), context or "aadhaar")
    return value


# ---------- VLM pass ----------


def _row_pages(state: _Extraction, pages: list[Page]) -> list[Page]:
    """Pages of a row document (statement, GSTR-3B) to send to the VLM for rows: every page with an
    image when the text pass found no rows at all; otherwise only scanned/photo pages without rows
    (a native-text page without rows next to pages with rows is a cover or summary page)."""
    if state.type not in TABLE_MODELS:
        return []
    if not state.rows:
        return [p for p in pages if p.image_png]
    with_rows = {row.get("_page") for row in state.rows}
    return [p for p in pages if p.image_png and p.text_source != TextSource.NATIVE and p.index not in with_rows]


def _vlm_pass(state: _Extraction, pages: list[Page], vlm: VlmClient) -> None:
    """Row pages go one image per request (a page of rows needs a long reply); otherwise pages go
    IMAGES_PER_REQUEST at a time until the required fields are found. Text-only pages go as text."""
    budget = config.VLM_MAX_REQUESTS_PER_DOCUMENT
    table_key = TABLE_MODELS[state.type][0] if state.type in TABLE_MODELS else None
    row_key = "transactions" if state.type == DocumentType.BANK_STATEMENT else table_key
    context = "aadhaar" if state.type == DocumentType.AADHAAR else ""
    row_pages = _row_pages(state, pages)
    chunks: list[tuple[list[Page], bool]] = [([p], True) for p in row_pages]
    # Then the other image pages for header/fields; skipped once nothing required is missing.
    with_image = [p for p in pages if p.image_png and p not in row_pages]
    chunks += [(with_image[i : i + IMAGES_PER_REQUEST], False) for i in range(0, len(with_image), IMAGES_PER_REQUEST)]
    text_only = [p for p in pages if not p.image_png and p.text.strip() and not any(r.get("_page") == p.index for r in state.rows)]
    if text_only:
        chunks.append((text_only, bool(table_key) and not state.rows))

    used = 0
    for n, (chunk, want_rows) in enumerate(chunks):
        if not want_rows and not state.needs():
            continue
        if used >= budget:
            unread = sorted({p.index + 1 for c, rows in chunks[n:] if rows or state.needs() for p in c})
            state.warnings.append(
                f"VLM request budget for this document ({budget}) is spent; page(s) {', '.join(map(str, unread))} not read by the VLM"
                + (f"; still missing: {', '.join(state.needs())}" if state.needs() else "")
            )
            return
        used += 1
        with_transactions = want_rows and state.type == DocumentType.BANK_STATEMENT
        images = [p.image_png for p in chunk if p.image_png]
        text = None if images else "\n\n".join(mask_aadhaar_text(p.text) for p in chunk)
        prompt = build_prompt(state.type, with_transactions=with_transactions, text=text)
        try:
            reply = vlm.complete_json(prompt, images, max_tokens=ROWS_MAX_TOKENS if want_rows else FIELDS_MAX_TOKENS)
        except VlmBudgetExceeded as exc:
            state.warnings.append(f"VLM unavailable (rate limit or budget): {exc}; remaining pages and fields not read by the VLM")
            return
        except VlmError as exc:
            state.warnings.append(f"VLM call failed for page(s) {', '.join(str(p.index + 1) for p in chunk)}: {exc}")
            continue
        if not isinstance(reply, dict):
            state.warnings.append("VLM reply was not a JSON object; ignored")
            continue
        reply = _sanitize(reply, context)
        page_index = chunk[0].index if len(chunk) == 1 else None
        for name, raw in reply.items():
            if name not in (table_key, row_key):
                state.offer_vlm(name, raw, page_index)
        rows = reply.get(row_key) if row_key else None
        if want_rows and isinstance(rows, list):
            state.rows.extend({**raw, "_confidence": VLM_CONFIDENCE, "_source": FieldSource.VLM, "_page": page_index} for raw in rows if isinstance(raw, dict))
    # Keep rows in page order whichever path read them (sort is stable within a page).
    order = {p.index: i for i, p in enumerate(pages)}
    state.rows.sort(key=lambda r: order.get(r.get("_page"), len(order)))


# ---------- Type-specific finishing (computed fields, row checks) ----------


def _finish_pan(state: _Extraction) -> None:
    if pan := state.fields.get("pan"):
        state.computed("holder_type", PAN_HOLDER_TYPES.get(pan.value[3]), pan.confidence, f"PAN 4th character '{pan.value[3]}'", pan.page_index)


def _finish_gst(state: _Extraction) -> None:
    if gstin := state.fields.get("gstin"):
        state.computed("pan_from_gstin", gstin.value[2:12], gstin.confidence, "GSTIN characters 3-12", gstin.page_index)
        state.computed("state_code", gstin.value[:2], gstin.confidence, "GSTIN characters 1-2", gstin.page_index)
        state.computed("state", GST_STATES[gstin.value[:2]], gstin.confidence, "GST state code", gstin.page_index)
    if "registration_date" not in state.fields:
        for name in ("validity_from", "date_of_liability"):
            if src := state.fields.get(name):
                state.computed("registration_date", src.value, src.confidence, f"from {name.replace('_', ' ')}", src.page_index)
                break


def _finish_gstr3b(state: _Extraction) -> None:
    periods: dict[str, dict[str, Any]] = {}
    for raw in state.rows:
        source = raw.get("_source", FieldSource.TEXT_LAYER)
        row, reason = validate_row(state.type, {k: v for k, v in raw.items() if not k.startswith("_")})
        if row is None:
            state.warnings.append(f"GSTR-3B row skipped: {reason}")
            continue
        if row["period"] in periods:
            if abs(periods[row["period"]]["taxable_outward_value"] - row["taxable_outward_value"]) > 0.01:
                state.warnings.append(f"GSTR-3B {month_label(row['period'])} appears twice with different 3.1(a) values; kept the first")
            continue
        periods[row["period"]] = {**row, "source": str(source), "page_index": raw.get("_page"), "confidence": raw.get("_confidence", 0.8)}
    rows = [periods[k] for k in sorted(periods)]
    state.table = rows
    if not rows:
        return
    conf = mean(r["confidence"] for r in rows)
    keys = [r["period"] for r in rows]
    state.computed("period_from", keys[0], conf, "first return period")
    state.computed("period_to", keys[-1], conf, "last return period")
    state.computed("months_filed", len(rows), conf, "returns found in the document")
    state.computed("total_taxable_outward_value", round(sum(r["taxable_outward_value"] for r in rows), 2), conf, f"sum of 3.1(a) over {len(rows)} month(s)")
    state.computed("total_tax", round(sum((r.get(k) or 0) for r in rows for k in ("igst", "cgst", "sgst", "cess")), 2), conf, "sum of 3.1(a) tax amounts")
    first, last = parse_date(keys[0] + "-01"), parse_date(keys[-1] + "-01")
    gaps = [m for m in month_range(first, last) if m not in periods]
    for gap in gaps:
        state.warnings.append(f"GSTR-3B for {month_label(gap)} is not in the document")


def _finish_bank(state: _Extraction) -> None:
    opening = state.fields.get("opening_balance")
    rows, warnings = bank.resolve_rows(state.rows, opening.value if opening else None)
    state.warnings.extend(warnings)
    table = []
    for row in rows:
        clean = {k: (v.isoformat() if k == "date" else v) for k, v in row.items() if not k.startswith("_") and k not in {"balance_ok", "direction_inferred"}}
        checked, reason = validate_row(state.type, clean)
        if checked is None:
            state.warnings.append(f"Transaction on {clean['date']} skipped: {reason}")
            continue
        checked["balance_ok"] = row["balance_ok"]
        checked["direction_inferred"] = bool(row.get("direction_inferred"))
        checked["source"] = str(row.get("_source") or FieldSource.TEXT_LAYER)
        checked["page_index"] = row.get("_page")
        checked["confidence"] = row["_confidence"]
        table.append(checked)
    state.table = table
    if not table:
        return
    conf = mean(r["confidence"] for r in table)
    first, last = parse_date(table[0]["date"]), parse_date(table[-1]["date"])
    if "period_from" not in state.fields:
        state.computed("period_from", first.isoformat(), conf, "date of the first transaction")
    if "period_to" not in state.fields:
        state.computed("period_to", last.isoformat(), conf, "date of the last transaction")
    start = parse_date(state.fields["period_from"].value)
    end = parse_date(state.fields["period_to"].value)
    breaks = sum(1 for r in table if r["balance_ok"] is False)
    checked_rows = sum(1 for r in table if r["balance_ok"] is not None)
    state.computed("transaction_count", len(table), conf)
    state.computed("total_credits", round(sum(r["credit"] or 0 for r in table), 2), conf, "sum of credit rows")
    state.computed("total_debits", round(sum(r["debit"] or 0 for r in table), 2), conf, "sum of debit rows")
    state.computed("balance_breaks", breaks, conf, f"{checked_rows} of {len(table)} rows checked: previous balance - debit + credit = balance")
    if start and end and start <= end:
        gaps = bank.missing_months(rows, start, end)
        state.computed("months_covered", len(month_range(start, end)), conf, "calendar months in the statement period")
        state.computed("missing_months", gaps, conf, "months in the period with no transactions")
        state.warnings.extend(bank.coverage_warnings(gaps))
    if checked_rows == 0:
        state.warnings.append("Balance math could not be checked: no running balance column was read")
    if (closing := state.fields.get("closing_balance")) and table[-1]["balance"] is not None:
        if abs(closing.value - table[-1]["balance"]) > bank.TOLERANCE:
            state.warnings.append(f"Closing balance {bank.money(closing.value)} does not match the last row's balance {bank.money(table[-1]['balance'])}")


FINISHERS: dict[DocumentType, Callable[[_Extraction], None]] = {
    DocumentType.PAN_CARD: _finish_pan,
    DocumentType.GST_CERTIFICATE: _finish_gst,
    DocumentType.GSTR_3B: _finish_gstr3b,
    DocumentType.BANK_STATEMENT: _finish_bank,
}


def extract(
    document: LoadedDocument,
    document_type: DocumentType,
    *,
    page_indexes: list[int] | None = None,
    vlm: VlmClient | None = None,
) -> ExtractionResult:
    """Read the fields of one document (or one segment of it). `vlm=None` means text/OCR only;
    callers that want the fallback pass app.documents.vlm.get_default_vlm()."""
    if document_type not in READERS:
        return ExtractionResult(document_type=document_type, status="failed", warnings=[f"No extractor for document type '{document_type}'"])
    if document.status != LoadStatus.OK:
        return ExtractionResult(
            document_type=document_type, status="failed", missing=list(REQUIRED[document_type]),
            warnings=[document.message or f"Document could not be read ({document.status})"],
        )

    pages = [p for p in document.pages if page_indexes is None or p.index in page_indexes]
    state = _Extraction(document_type)
    for page in pages:
        view = page_view(page)
        read = READERS[document_type](view)
        state.warnings.extend(read.warnings)
        for name, hit in read.fields.items():
            state.offer_text(name, hit, view)
        state.rows.extend({**row, "_source": view.source, "_page": view.index} for row in read.rows)

    if vlm is not None and (state.needs() or _row_pages(state, pages)):
        _vlm_pass(state, pages, vlm)

    if finish := FINISHERS.get(document_type):
        finish(state)

    missing = [n for n in REQUIRED[document_type] if n not in state.fields]
    if document_type == DocumentType.AADHAAR and "dob" not in state.fields and "year_of_birth" not in state.fields:
        missing.append("dob")
    tables = {TABLE_MODELS[document_type][0]: state.table} if document_type in TABLE_MODELS else {}
    has_data = bool(state.fields) or any(tables.values())
    status = "ok" if not missing and has_data else "partial" if has_data else "failed"
    fields = {
        name: ExtractedField(value=c.value, source=c.source, page_index=c.page_index, confidence=c.confidence, validated=c.validated, note=c.note)
        for name, c in state.fields.items()
    }
    return ExtractionResult(document_type=document_type, status=status, fields=fields, missing=missing, tables=tables, warnings=list(dict.fromkeys(state.warnings)))
