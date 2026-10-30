"""Validation: per-document checks, transaction tagging and cross-document checks.

Input: DocumentEnvelopes from extraction (OCR/VLM). Output: the same envelopes with `checks` filled and
`status` set, plus the cross-document checks. Everything here is deterministic.
"""

from __future__ import annotations

from datetime import date

from app.schemas.common import Check, CheckStatus, DocumentType
from app.schemas.documents import DocumentEnvelope
from app.validation.cross import DocumentSet, cross_checks
from app.validation.documents import check_document
from app.validation.tagging import tag_statement


def validate_document(envelope: DocumentEnvelope, as_of: date) -> DocumentEnvelope:
    """Tag (bank statements), run the document's own checks, and set its status."""
    if envelope.data is None:
        return envelope
    if envelope.document_type == DocumentType.BANK_STATEMENT:
        envelope = envelope.model_copy(update={"data": tag_statement(envelope.data)})
    checks = check_document(envelope, as_of)
    status = "verified" if all(c.status == CheckStatus.PASS for c in checks) else "needs_review"
    return envelope.model_copy(update={"checks": checks, "status": status})


def validate_all(envelopes: list[DocumentEnvelope], as_of: date) -> tuple[list[DocumentEnvelope], DocumentSet, list[Check]]:
    validated = [validate_document(e, as_of) for e in envelopes]
    docs = DocumentSet.from_envelopes(validated)
    return validated, docs, cross_checks(docs)


__all__ = ["DocumentSet", "check_document", "cross_checks", "validate_all", "validate_document"]
