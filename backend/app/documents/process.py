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

import importlib.util
import logging
from datetime import datetime

from pydantic import BaseModel

from app import config
from app.bureau import self_declared_bureau_score
from app.documents.classify import classify
from app.documents.extract.envelope import ENVELOPE_TYPE, build_envelope, has_envelope
from app.documents.extract.pipeline import extract_detailed
from app.documents.ingest import load_document
from app.documents.models import ClassificationResult, DocumentType, ExtractionResult, LoadStatus
from app.documents.ports import OcrEngine, VlmClient
from app.documents.vlm import get_default_vlm
from app.documents.vlm.budget import VlmBudget
from app.schemas.common import DocumentType as EnvelopeType
from app.schemas.documents import DocumentEnvelope
from app.schemas.profile import BureauScore

log = logging.getLogger(__name__)

PIPELINE_TYPE = {ours: theirs for theirs, ours in ENVELOPE_TYPE.items()}  # upload slot -> pipeline type
LABELS = {
    DocumentType.BUREAU_REPORT: "credit bureau report",
    DocumentType.FINANCIAL_STATEMENTS: "financial statements",
    DocumentType.SANCTION_LETTER: "loan sanction letter",
    DocumentType.SETTLEMENT_REPORT: "payment settlement report",
}
NO_OCR = "This looks like a photo or scan, and text reading (OCR) isn't switched on yet. Upload the original PDF for now."
UNKNOWN = "We couldn't tell which document this is. Upload it in the right slot, or try a clearer copy."
UNREADABLE = "We recognised this document but couldn't read its details. Try a clearer photo or the original PDF."


class SkippedPart(BaseModel):
    """Pages the SME uploaded that did not become a usable envelope, with a reason they can act on."""

    pages: list[int]  # 1-based, as the SME sees them
    document_type: str  # pipeline type; "unknown" when not recognised
    reason: str


class ProcessResult(BaseModel):
    file_name: str
    sha256: str | None = None
    # "ok", "nothing_recognised" (readable file, no known document in it), a LoadStatus value
    # (password_required, unsupported_format, unreadable, too_large) or "error".
    status: str
    message: str | None = None  # user-facing, set whenever status is not "ok"
    classification: ClassificationResult | None = None
    envelopes: list[DocumentEnvelope] = []
    # Raw extraction is retained only for document types that have no envelope model yet.
    extractions: list[ExtractionResult] = []
    # The score read from an uploaded bureau report, always "self_declared": a document the borrower
    # supplies cannot verify a bureau score (the lender pulls its own with consent). It is a candidate
    # for assess(bureau=...); the caller decides which score wins if the SME also typed one in.
    bureau: BureauScore | None = None
    # What was read but could not be put in an envelope (contract gaps hit at run time).
    notes: list[str] = []
    # User-facing: every part of the file that gave no usable envelope, and why (the upload page shows these).
    skipped: list[SkippedPart] = []
    vlm_requests_used: int = 0
    warnings: list[str] = []


def process_upload(
    data: bytes,
    file_name: str,
    *,
    sme_id: str,
    password: str | None = None,
    expected_type: EnvelopeType | None = None,
    ocr: OcrEngine | None = None,
    vlm: VlmClient | None = None,
    budget: VlmBudget | None = None,
    uploaded_at: datetime | None = None,
) -> ProcessResult:
    """`expected_type`: the upload slot the SME chose. Used only when the classifier recognises nothing in a
    one-segment file; a confident classification that disagrees wins, with a warning."""
    budget = budget if budget is not None else VlmBudget(config.VLM_MAX_REQUESTS_PER_DOCUMENT)
    start = budget.used
    try:
        return _process(data, file_name, sme_id, password, expected_type, ocr, vlm, budget, uploaded_at, start)
    except Exception as exc:  # noqa: BLE001 - the upload endpoint must never see an exception
        log.warning("process_upload failed: %s", type(exc).__name__)  # class only: messages may carry file content
        return ProcessResult(
            file_name=file_name, status="error", vlm_requests_used=budget.used - start,
            message="Something went wrong while reading this file. Please try again or upload a different copy.",
        )


def _process(data, file_name, sme_id, password, expected_type, ocr, vlm, budget, uploaded_at, start) -> ProcessResult:
    document = load_document(data, file_name, password=password, ocr=ocr)
    if document.status != LoadStatus.OK:
        return ProcessResult(
            file_name=file_name, sha256=document.sha256, status=document.status.value,
            message=document.message, warnings=document.warnings,
        )
    # When the SME chose the upload slot, the VLM is saved for reading fields rather than also naming the document.
    classification = classify(document, vlm=None if expected_type else vlm, budget=budget)
    result = ProcessResult(file_name=file_name, sha256=document.sha256, status="ok", classification=classification, warnings=list(document.warnings))
    counts: dict[str, int] = {}
    segments = [(s.document_type, s.page_indexes) for s in classification.segments]
    hint = PIPELINE_TYPE.get(expected_type) if expected_type else None
    if hint and len(segments) == 1 and segments[0][0] == DocumentType.UNKNOWN:
        segments = [(hint, segments[0][1])]
        result.warnings.append("We couldn't recognise this document on our own, so we read it as the one you chose.")

    def no_text(pages: list[int]) -> bool:
        return ocr is None and vlm is None and not any(p.text.strip() for p in document.pages if p.index in pages)

    for doc_type, page_indexes in segments:
        shown = [i + 1 for i in page_indexes]
        if doc_type == DocumentType.UNKNOWN:
            result.notes.append(f"Pages {', '.join(map(str, shown))} were not recognised as a known document")
            result.skipped.append(SkippedPart(pages=shown, document_type=doc_type.value, reason=NO_OCR if no_text(page_indexes) else UNKNOWN))
            continue
        extraction = extract_detailed(document, doc_type, page_indexes=page_indexes, vlm=vlm, budget=budget)
        kind = doc_type.value
        counts[kind] = counts.get(kind, 0) + 1
        result.warnings.extend(f"{kind}: {w}" for w in extraction.result.warnings)
        if not has_envelope(doc_type):
            result.extractions.append(extraction.result)
            result.skipped.append(SkippedPart(pages=shown, document_type=kind,
                                              reason=f"Looks like a {LABELS.get(doc_type, kind)}. We can read it, but it isn't used in your score yet."))
            continue
        built = build_envelope(
            extraction, document, sme_id=sme_id, document_id=f"{document.sha256[:12]}-{kind}-{counts[kind]}",
            uploaded_at=uploaded_at, page_indexes=page_indexes, size_bytes=len(data), password_protected=bool(password),
        )
        if built is not None:
            result.envelopes.append(built.envelope)
            result.notes.extend(f"{kind}: {note}" for note in built.notes)
            if built.envelope.status == "failed":
                result.skipped.append(SkippedPart(pages=shown, document_type=kind, reason=NO_OCR if no_text(page_indexes) else UNREADABLE))
    usable = [e for e in result.envelopes if e.status != "failed"]
    if expected_type and usable and all(e.document_type != expected_type for e in usable):
        found = ", ".join(sorted({e.document_type.value.replace("_", " ") for e in usable}))
        result.warnings.append(f"You uploaded this as {expected_type.value.replace('_', ' ')}, but it looks like: {found}. We used what it is.")
    result.bureau = self_declared_bureau_score(result.envelopes)
    if result.bureau is not None:
        result.warnings.append("bureau_report: the score comes from a report you uploaded, so it is unverified; the lender will pull its own.")
        for part in result.skipped:
            if part.document_type == DocumentType.BUREAU_REPORT.value:
                part.reason = f"Credit report: we use its score ({result.bureau.value}) as self-declared; the lender checks its own."
    if not result.envelopes and not result.extractions:
        result.status = "nothing_recognised"
        result.message = "We could not recognise a supported document in this file. Check the document checklist and try another copy."
    result.vlm_requests_used = budget.used - start
    return result


def default_ocr() -> OcrEngine | None:
    """Local PaddleOCR when it is installed (it is heavy, ~1 GB); else None."""
    if not config.OCR_ENABLED or importlib.util.find_spec("paddleocr") is None:
        return None
    from app.documents.ocr import get_default_ocr

    return get_default_ocr()


def default_engines() -> tuple[OcrEngine | None, VlmClient | None]:
    """The engines the upload route uses. The VLM only runs alongside OCR, because OCR is what finds Aadhaar
    numbers to black out before a page image leaves the server (config.VLM_WITHOUT_OCR overrides, knowingly)."""
    ocr, vlm = default_ocr(), get_default_vlm()
    if ocr is None and vlm is not None and config.OCR_ENABLED and not config.VLM_WITHOUT_OCR:
        log.warning("PaddleOCR is not installed: the VLM is off for uploads so unredacted images never leave the server")
        vlm = None
    return ocr, vlm
