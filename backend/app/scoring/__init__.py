"""Scoring: validated documents -> SmeProfile (identity, cash-flow metrics, readiness, fix-it list).

`assess()` is the one entry point: extraction output in, profile + checked documents out.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.schemas.common import DocumentType, Schema
from app.schemas.documents import BureauReport, DocumentEnvelope
from app.schemas.profile import BureauScore, DocumentSummary, SmeProfile
from app.scoring.fixit import build_fix_it
from app.scoring.metrics import build_identity, compute_metrics
from app.scoring.readiness import score_readiness
from app.validation import validate_all


def _bureau_from_documents(envelopes: list[DocumentEnvelope]) -> BureauScore | None:
    """Use the newest borrower-uploaded consumer score only as self-declared input.

    A commercial CMR rank is retained on its own document and is never converted to a consumer score.
    """
    candidates: list[tuple[date, BureauReport]] = []
    for envelope in envelopes:
        data = envelope.data
        if envelope.document_type != DocumentType.BUREAU_REPORT or not isinstance(data, BureauReport):
            continue
        if data.score is None or data.score.value is None:
            continue
        candidates.append((data.report_date.value if data.report_date and data.report_date.value else date.min, data))
    if not candidates:
        return None
    _, report = max(candidates, key=lambda pair: pair[0])
    return BureauScore(
        value=report.score.value, source="self_declared", as_of=report.report_date.value if report.report_date else None,
        cmr_rank=report.cmr_rank.value if report.cmr_rank else None,
        max_dpd_24m=report.max_dpd_24m.value if report.max_dpd_24m else None,
        enquiries_90d=report.enquiries_90d.value if report.enquiries_90d else None,
        written_off_or_settled=report.written_off_or_settled.value if report.written_off_or_settled else None,
        suit_filed_or_wilful_default=report.suit_filed_or_wilful_default.value if report.suit_filed_or_wilful_default else None,
        active_accounts=report.active_accounts.value if report.active_accounts else None,
        overdue_amount=report.overdue_amount.value if report.overdue_amount else None,
    )


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
    if bureau is None:
        bureau = _bureau_from_documents(envelopes)
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
