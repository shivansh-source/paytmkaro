"""One call from uploaded bytes to envelopes: ingest -> classify -> extract -> bridge.

    result = process_upload(data, "kyc.pdf", sme_id="sme-1", password=None, ocr=ocr, vlm=get_default_vlm())
    scoring.assess("sme-1", result.envelopes)

One VlmBudget is shared by the classifier and every extract() call, so a whole upload (all segments of
a bundle) stays under config.VLM_MAX_REQUESTS_PER_DOCUMENT. Nothing here raises: an unreadable,
password-protected, unsupported or oversized file comes back with a status and a user-facing message.
The Aadhaar number is already masked by ingest; only the last 4 digits can appear in the result, and
failures are logged by exception class only (never with file content).
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from pydantic import BaseModel, ValidationError

from app import config
from app.documents.classify import classify
from app.documents.extract.envelope import build_envelope, has_envelope
from app.documents.extract.pipeline import extract_detailed
from app.documents.ingest import load_document
from app.documents.models import ClassificationResult, DocumentType, ExtractionResult, LoadStatus
from app.documents.ports import OcrEngine, VlmClient
from app.documents.vlm.budget import VlmBudget
from app.schemas.documents import DocumentEnvelope
from app.schemas.profile import BureauScore

log = logging.getLogger(__name__)


class ProcessResult(BaseModel):
    file_name: str
    sha256: str | None = None
    # "ok", "nothing_recognised" (readable file, no known document in it), a LoadStatus value
    # (password_required, unsupported_format, unreadable, too_large) or "error".
    status: str
    message: str | None = None  # user-facing, set whenever status is not "ok"
    classification: ClassificationResult | None = None
    envelopes: list[DocumentEnvelope] = []
    # Documents the envelope has no slot for (bureau report, financial statements, sanction letter,
    # settlement report): their raw extraction is returned instead.
    extractions: list[ExtractionResult] = []
    # The score read from an uploaded bureau report, always "self_declared": a document the borrower
    # supplies cannot verify a bureau score (the lender pulls its own with consent). It is a candidate
    # for assess(bureau=...); the caller decides which score wins if the SME also typed one in.
    bureau: BureauScore | None = None
    # What was read but could not be put in an envelope (contract gaps hit at run time).
    notes: list[str] = []
    vlm_requests_used: int = 0
    warnings: list[str] = []


def process_upload(
    data: bytes,
    file_name: str,
    *,
    sme_id: str,
    password: str | None = None,
    ocr: OcrEngine | None = None,
    vlm: VlmClient | None = None,
    budget: VlmBudget | None = None,
    uploaded_at: datetime | None = None,
) -> ProcessResult:
    budget = budget if budget is not None else VlmBudget(config.VLM_MAX_REQUESTS_PER_DOCUMENT)
    start = budget.used
    try:
        return _process(data, file_name, sme_id, password, ocr, vlm, budget, uploaded_at, start)
    except Exception as exc:  # noqa: BLE001 - the upload endpoint must never see an exception
        log.warning("process_upload failed: %s", type(exc).__name__)  # class only: messages may carry file content
        return ProcessResult(
            file_name=file_name, status="error", vlm_requests_used=budget.used - start,
            message="Something went wrong while reading this file. Please try again or upload a different copy.",
        )


def _self_provided_bureau(extractions: list[ExtractionResult]) -> BureauScore | None:
    """The newest consumer score among the uploaded reports. A report with no credit history, an unreadable
    or out-of-range score gives nothing, and the commercial CMR rank (1-10, lower is better) is never used."""
    candidates: list[tuple[date, int, date | None]] = []
    for extraction in extractions:
        field = extraction.fields.get("score") if extraction.document_type == DocumentType.BUREAU_REPORT else None
        if field is None or field.value is None:
            continue
        reported = extraction.fields.get("report_date")
        try:
            as_of = date.fromisoformat(str(reported.value)) if reported is not None and reported.value else None
            candidates.append((as_of or date.min, int(field.value), as_of))
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    _, value, as_of = max(candidates, key=lambda c: c[0])
    try:
        return BureauScore(value=value, source="self_declared", as_of=as_of)
    except ValidationError:
        return None


def _process(data, file_name, sme_id, password, ocr, vlm, budget, uploaded_at, start) -> ProcessResult:
    document = load_document(data, file_name, password=password, ocr=ocr)
    if document.status != LoadStatus.OK:
        return ProcessResult(
            file_name=file_name, sha256=document.sha256, status=document.status.value,
            message=document.message, warnings=document.warnings,
        )
    classification = classify(document, vlm=vlm, budget=budget)
    result = ProcessResult(file_name=file_name, sha256=document.sha256, status="ok", classification=classification, warnings=list(document.warnings))
    counts: dict[str, int] = {}
    for segment in classification.segments:
        if segment.document_type == DocumentType.UNKNOWN:
            result.notes.append(f"Pages {', '.join(str(i + 1) for i in segment.page_indexes)} were not recognised as a known document")
            continue
        extraction = extract_detailed(document, segment.document_type, page_indexes=segment.page_indexes, vlm=vlm, budget=budget)
        kind = segment.document_type.value
        counts[kind] = counts.get(kind, 0) + 1
        result.warnings.extend(f"{kind}: {w}" for w in extraction.result.warnings)
        if not has_envelope(segment.document_type):
            result.extractions.append(extraction.result)
            continue
        built = build_envelope(
            extraction, document, sme_id=sme_id, document_id=f"{document.sha256[:12]}-{kind}-{counts[kind]}",
            uploaded_at=uploaded_at, page_indexes=segment.page_indexes, size_bytes=len(data), password_protected=bool(password),
        )
        if built is not None:
            result.envelopes.append(built.envelope)
            result.notes.extend(f"{kind}: {note}" for note in built.notes)
    result.bureau = _self_provided_bureau(result.extractions)
    if result.bureau is not None:
        result.warnings.append("bureau_report: the score comes from a report you uploaded, so it is unverified; the lender will pull its own.")
    if not result.envelopes and not result.extractions:
        result.status = "nothing_recognised"
        result.message = "We could not recognise any supported document in this file. Upload a PAN, Aadhaar, GST certificate, GSTR-3B, Udyam, ITR-V or bank statement."
    result.vlm_requests_used = budget.used - start
    return result
