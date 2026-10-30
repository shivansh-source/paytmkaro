"""Bridge from the shared MSME schemas to the engine's flat input.

The engine stays decoupled from document details: if SmeProfile changes shape, only this function
changes.
"""

from __future__ import annotations

from app.recommendation.models import MatchInput
from app.schemas import LoanRequest, SmeProfile


def match_input(profile: SmeProfile, request: LoanRequest) -> MatchInput:
    identity, cash = profile.identity, profile.cashflow

    def value(sourced):  # Sourced[T] | None -> T | None
        return sourced.value if sourced is not None else None

    turnover = value(cash.gst_turnover_12m)
    return MatchInput(
        sme_id=profile.sme_id,
        requested_amount=request.amount,
        requested_tenure_months=request.tenure_months,
        business_vintage_months=value(identity.business_vintage_months),
        annual_turnover=round(turnover) if turnover is not None else None,
        bureau_score=profile.bureau.value if profile.bureau else None,
        foir=value(cash.foir),
        bounces_6m=value(cash.bounces_6m),
        gst_registered=identity.gstin is not None,
        constitution=identity.constitution.value,
        sector=identity.sector,
    )
