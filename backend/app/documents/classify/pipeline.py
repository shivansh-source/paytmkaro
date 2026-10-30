"""classify(): rules per page -> context fill-in -> optional VLM fallback -> segments."""

from __future__ import annotations

from app.documents.classify.rules import score_page
from app.documents.classify.segments import build_segments, dominant, fill_from_context, from_score
from app.documents.classify.vlm import vlm_fallback
from app.documents.models import (
    ClassificationResult,
    ClassifyMethod,
    DocumentType,
    LoadedDocument,
    LoadStatus,
    PageClassification,
)
from app.documents.ports import VlmClient


def classify(document: LoadedDocument, *, vlm: VlmClient | None = None) -> ClassificationResult:
    """Label every page, group consecutive pages into segments, pick the dominant type.

    The VLM (if given) is asked only about pages still unknown after rules and context,
    and only for pages that have an image. Its failures never change the rules result.
    """
    if document.status is not LoadStatus.OK:
        return ClassificationResult(
            file_name=document.file_name,
            status=document.status,
            message=document.message,
            document_type=DocumentType.UNKNOWN,
            confidence=0.0,
            method="none",
        )

    scores = [score_page(page) for page in document.pages]
    decisions = [from_score(s) for s in scores]
    fill_from_context(decisions, scores)

    warnings: list[str] = []
    if vlm is not None:
        images = {p.index: p.image_png for p in document.pages if p.image_png}
        requests, warnings = vlm_fallback(decisions, scores, images, vlm)
        if requests:
            fill_from_context(decisions, scores)  # VLM labels may now bridge remaining gaps

    doc_type, confidence = dominant(decisions)
    return ClassificationResult(
        file_name=document.file_name,
        status=document.status,
        message=document.message,
        document_type=doc_type,
        confidence=confidence,
        method=_method({d.by for d in decisions}),
        warnings=warnings,
        pages=[
            PageClassification(
                page_index=d.page_index,
                document_type=d.doc_type,
                confidence=d.confidence,
                method=d.by,  # type: ignore[arg-type]
                signals=d.signals,
            )
            for d in decisions
        ],
        segments=build_segments(decisions),
    )


def _method(used: set[str]) -> ClassifyMethod:
    """'vlm' when only the VLM produced labels, 'rules+vlm' when both did, else 'rules'."""
    by_vlm = bool(used & {"vlm", "rules+vlm"})
    by_rules = bool(used & {"rules", "context", "rules+vlm"})
    if by_vlm:
        return "rules+vlm" if by_rules else "vlm"
    return "rules"
