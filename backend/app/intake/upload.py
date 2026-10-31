"""One uploaded file -> ingest -> classify -> extract (per segment) -> envelopes.

A file can hold several documents (a PDF with PAN and Aadhaar), so one upload returns a list. Parts the
pipeline can read but we cannot score yet, and parts it could not read, come back in `skipped` with a
plain reason, never as half-empty envelopes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel

from app.documents.classify.pipeline import classify
from app.documents.extract.pipeline import extract_detailed
from app.documents.ingest import load_document
from app.documents.models import DocumentType as PipelineType
from app.documents.models import LoadStatus
from app.documents.ports import OcrEngine, VlmClient
from app.documents.vlm.budget import VlmBudget
from app.intake.bridge import PIPELINE_TYPE, TYPE_MAP, to_envelope
from app import config
from app.schemas import DocumentEnvelope, DocumentType

log = logging.getLogger(__name__)

LABELS = {
    PipelineType.BUREAU_REPORT: "credit bureau report",
    PipelineType.FINANCIAL_STATEMENTS: "financial statements",
    PipelineType.SANCTION_LETTER: "loan sanction letter",
    PipelineType.SETTLEMENT_REPORT: "payment settlement report",
}


class SkippedPart(BaseModel):
    pages: list[int]  # 1-based, as the SME sees them
    document_type: str  # pipeline type, "unknown" when not recognised
    reason: str


class UploadResult(BaseModel):
    file_name: str
    status: LoadStatus  # ok, password_required, unsupported_format, unreadable, too_large
    message: str | None = None  # what to do when status != ok
    documents: list[DocumentEnvelope] = []
    skipped: list[SkippedPart] = []
    warnings: list[str] = []


def process_upload(
    data: bytes,
    file_name: str,
    *,
    sme_id: str,
    expected_type: DocumentType | None = None,
    password: str | None = None,
    mime_type: str | None = None,
    ocr: OcrEngine | None = None,
    vlm: VlmClient | None = None,
    uploaded_at: datetime | None = None,
) -> UploadResult:
    """`expected_type`: the slot the SME uploaded into. Used only when the classifier can't tell; a
    confident classification that disagrees wins, with a warning."""
    uploaded_at = uploaded_at or datetime.now(UTC)
    document = load_document(data, file_name, password=password, ocr=ocr)
    if document.status != LoadStatus.OK:
        return UploadResult(file_name=file_name, status=document.status, message=document.message)

    budget = VlmBudget(config.VLM_MAX_REQUESTS_PER_DOCUMENT)  # one pool for the whole upload
    classified = classify(document, vlm=vlm, budget=budget)
    warnings = list(dict.fromkeys(document.warnings + classified.warnings))
    segments = [(s.document_type, s.page_indexes) for s in classified.segments] or [
        (classified.document_type, [p.index for p in document.pages])
    ]
    hint = PIPELINE_TYPE.get(expected_type) if expected_type else None
    if hint and len(segments) == 1 and segments[0][0] == PipelineType.UNKNOWN:
        segments = [(hint, segments[0][1])]
        warnings.append("We couldn't recognise this document on our own, so we read it as the one you chose.")

    documents: list[DocumentEnvelope] = []
    skipped: list[SkippedPart] = []
    for n, (kind, pages) in enumerate(segments):
        shown = [i + 1 for i in pages]
        if kind == PipelineType.UNKNOWN:
            skipped.append(SkippedPart(pages=shown, document_type=kind, reason=_unknown_reason(document, pages, ocr, vlm)))
            continue
        if kind not in TYPE_MAP:
            skipped.append(SkippedPart(pages=shown, document_type=kind,
                                       reason=f"Looks like a {LABELS.get(kind, kind)}. We can read it, but it isn't used in your score yet."))
            continue
        extraction = extract_detailed(document, kind, page_indexes=pages, vlm=vlm, budget=budget)
        warnings.extend(extraction.result.warnings)
        if extraction.result.status == "failed":
            reason = _no_ocr_reason(document, pages, ocr, vlm) or (
                "We recognised this document but couldn't read its details. Try a clearer photo or the original PDF.")
            skipped.append(SkippedPart(pages=shown, document_type=kind, reason=reason))
            continue
        envelope_type = TYPE_MAP[kind]
        suffix = f"-{n + 1}" if len(segments) > 1 else ""
        documents.append(to_envelope(
            extraction, document, page_indexes=pages, sme_id=sme_id,
            document_id=f"{sme_id}-{envelope_type.value}-{document.sha256[:8]}{suffix}".lower(),
            uploaded_at=uploaded_at, size_bytes=len(data), mime_type=mime_type, password_used=password is not None,
        ))

    if expected_type and documents and all(d.document_type != expected_type for d in documents):
        found = ", ".join(sorted({d.document_type.value.replace("_", " ") for d in documents}))
        warnings.append(f"You uploaded this as {expected_type.value.replace('_', ' ')}, but it looks like: {found}. We used what it is.")
    log.info("upload %s: %d document(s), %d skipped", document.sha256[:12], len(documents), len(skipped))
    return UploadResult(file_name=file_name, status=LoadStatus.OK, documents=documents, skipped=skipped,
                        warnings=list(dict.fromkeys(warnings)))


def _no_ocr_reason(document, pages: list[int], ocr: OcrEngine | None, vlm: VlmClient | None) -> str | None:
    """Said when a photo or scan has no text and nothing here can read images."""
    if ocr is None and vlm is None and not any(p.text.strip() for p in document.pages if p.index in pages):
        return "This looks like a photo or scan, and text reading (OCR) isn't switched on yet. Upload the original PDF for now."
    return None


def _unknown_reason(document, pages: list[int], ocr: OcrEngine | None, vlm: VlmClient | None) -> str:
    return _no_ocr_reason(document, pages, ocr, vlm) or (
        "We couldn't tell which document this is. Upload it in the right slot, or try a clearer copy.")
