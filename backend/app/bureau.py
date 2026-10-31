"""Shared conversion of borrower-uploaded bureau reports into an assessment input."""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from app.schemas.common import DocumentType
from app.schemas.documents import BureauReport, DocumentEnvelope
from app.schemas.profile import BureauScore


def self_declared_bureau_score(envelopes: list[DocumentEnvelope]) -> BureauScore | None:
    """Use the newest valid consumer score; keep CMR separate and ignore invalid scores."""
    candidates: list[tuple[date, BureauReport]] = []
    for envelope in envelopes:
        report = envelope.data
        if envelope.document_type != DocumentType.BUREAU_REPORT or not isinstance(report, BureauReport):
            continue
        score = report.score.value if report.score else None
        if score is None or not 300 <= score <= 900:
            continue
        as_of = report.report_date.value if report.report_date else None
        candidates.append((as_of or date.min, report))

    if not candidates:
        return None
    _, report = max(candidates, key=lambda candidate: candidate[0])
    try:
        return BureauScore(
            value=report.score.value,
            source="self_declared",
            as_of=report.report_date.value if report.report_date else None,
            cmr_rank=report.cmr_rank.value if report.cmr_rank else None,
            max_dpd_24m=report.max_dpd_24m.value if report.max_dpd_24m else None,
            enquiries_90d=report.enquiries_90d.value if report.enquiries_90d else None,
            written_off_or_settled=report.written_off_or_settled.value if report.written_off_or_settled else None,
            suit_filed_or_wilful_default=report.suit_filed_or_wilful_default.value if report.suit_filed_or_wilful_default else None,
            active_accounts=report.active_accounts.value if report.active_accounts else None,
            overdue_amount=report.overdue_amount.value if report.overdue_amount else None,
        )
    except ValidationError:
        # Invalid optional bureau details must not break the document assessment.
        return None
