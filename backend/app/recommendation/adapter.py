"""Bridge from the shared MSME schemas to the engine's flat input.

The engine stays decoupled from document details: if SmeProfile changes shape, only this function
changes.
"""

from __future__ import annotations

from app.recommendation.models import MatchInput
from app.schemas import DocumentType, LoanRequest, SmeProfile


def _value(sourced):  # Sourced[T] | None -> T | None
    return sourced.value if sourced is not None else None


def match_input(profile: SmeProfile, request: LoanRequest) -> MatchInput:
    identity, cash = profile.identity, profile.cashflow
    on_file = {d.document_type for d in profile.documents if d.status != "failed"}
    as_of = profile.updated_at.date()

    dob = _value(identity.promoter_dob)
    age = None
    if dob is not None:
        age = as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))

    turnover = _value(cash.gst_turnover_12m)
    address = _value(identity.address)
    constitution = _value(identity.constitution)
    return MatchInput(
        sme_id=profile.sme_id,
        requested_amount=request.amount,
        requested_tenure_months=request.tenure_months,
        business_vintage_months=_value(identity.business_vintage_months),
        annual_turnover=round(turnover) if turnover is not None else None,
        bureau_score=profile.bureau.value if profile.bureau else None,
        foir=_value(cash.foir),
        bounces_6m=_value(cash.bounces_6m),
        gst_registered=identity.gstin is not None,
        constitution=constitution.value if constitution is not None else None,
        sector=identity.sector,
        has_itr=DocumentType.ITR_V in on_file,
        has_udyam=identity.udyam_number is not None,
        bank_statement_months=cash.months_analyzed or None,
        applicant_age_years=age,
        state=address.state if address is not None else None,
    )
