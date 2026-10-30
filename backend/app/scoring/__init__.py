"""Scoring: validated documents -> SmeProfile (identity, cash-flow metrics, readiness, fix-it list).

`assess()` is the one entry point: extraction output in, profile + checked documents out.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.schemas.common import Schema
from app.schemas.documents import DocumentEnvelope
from app.schemas.profile import BureauScore, DocumentSummary, SmeProfile
from app.scoring.fixit import build_fix_it
from app.scoring.metrics import build_identity, compute_metrics
from app.scoring.readiness import score_readiness
from app.validation import validate_all


class Assessment(Schema):
    profile: SmeProfile
    documents: list[DocumentEnvelope]  # the input envelopes with checks and status filled in


def assess(
    sme_id: str,
    envelopes: list[DocumentEnvelope],
    *,
    bureau: BureauScore | None = None,
    sector: str | None = None,
    as_of: date | None = None,
) -> Assessment:
    as_of = as_of or date.today()
    documents, docs, cross = validate_all(envelopes, as_of)
    metrics = compute_metrics(docs)
    profile = SmeProfile(
        sme_id=sme_id,
        updated_at=datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc),
        identity=build_identity(docs, as_of, sector),
        cashflow=metrics,
        bureau=bureau,
        documents=[DocumentSummary(document_id=e.document_id, document_type=e.document_type, status=e.status) for e in documents],
        cross_checks=cross,
        readiness=score_readiness(docs, cross, metrics, bureau),
        fix_it=build_fix_it(docs, documents, cross, metrics, bureau),
    )
    return Assessment(profile=profile, documents=documents)


__all__ = ["Assessment", "assess"]
