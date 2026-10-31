"""Applications: an MSME sharing its verified file with one lender product, and the lender's decision.

The profile stored here is always computed by the server (`assess()` on the documents), never taken from
the client, so what the lender sees is what our checks produced.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.recommendation.models import MatchResult
from app.schemas.common import Schema
from app.schemas.documents import DocumentEnvelope
from app.schemas.profile import BureauScore, LoanRequest, SmeProfile

ApplicationStatus = Literal["submitted", "in_review", "approved_in_principle", "info_requested", "declined", "withdrawn"]
DecisionAction = Literal["start_review", "approve_in_principle", "request_info", "decline"]
DeclineReason = Literal["vintage", "turnover", "cash_flow", "credit_history", "documents", "policy", "other"]

# What the MSME reads. A decline always says why: no silent rejections.
DECLINE_REASON_TEXT: dict[str, str] = {
    "vintage": "your business needs to be operating for longer",
    "turnover": "your turnover is below what this product needs",
    "cash_flow": "your current EMIs or bounces are too high for this loan",
    "credit_history": "your credit history doesn't meet this product's bar yet",
    "documents": "some documents need to be corrected or completed",
    "policy": "this loan falls outside the lender's current policy",
    "other": "the lender gave a specific reason (see note)",
}

CONSENT_TEXT = (
    "I agree to share my verified business profile, the documents I uploaded, and the checks run on them "
    "with {lender} for my loan application. I can withdraw this consent at any time."
)


class Consent(Schema):
    text: str
    accepted_at: datetime


class Event(Schema):
    at: datetime
    actor: Literal["msme", "lender", "system"]
    action: str
    note: str | None = None


class Decision(Schema):
    action: Literal["approve_in_principle", "request_info", "decline"]
    reason: DeclineReason | None = None
    note: str | None = None
    decided_at: datetime
    message_for_msme: str


class ApplicationSummary(Schema):
    """One inbox row."""

    id: str
    sme_id: str
    business_name: str
    lender: str
    product_id: str
    product: str
    amount: int
    tenure_months: int | None
    status: ApplicationStatus
    readiness_score: int | None
    readiness_band: str | None
    red_flags: int  # failed cross-checks
    warnings: int  # cross-checks needing a look
    fit_label: str | None
    true_apr_pct: float | None
    submitted_at: datetime
    updated_at: datetime
    decision_message: str | None = None


class Application(Schema):
    id: str
    status: ApplicationStatus
    submitted_at: datetime
    updated_at: datetime
    lender: str
    product_id: str
    product: str
    request: LoanRequest
    match: MatchResult  # the engine's verdict against this product at submission time
    profile: SmeProfile
    documents: list[DocumentEnvelope]  # validated envelopes: the evidence behind every number
    consent: Consent
    decision: Decision | None = None
    history: list[Event] = []

    def summary(self) -> ApplicationSummary:
        identity = self.profile.identity
        name = identity.trade_name or identity.legal_name
        readiness = self.profile.readiness
        return ApplicationSummary(
            id=self.id,
            sme_id=self.profile.sme_id,
            business_name=name.value if name else self.profile.sme_id,
            lender=self.lender,
            product_id=self.product_id,
            product=self.product,
            amount=self.request.amount,
            tenure_months=self.request.tenure_months,
            status=self.status,
            readiness_score=readiness.score if readiness else None,
            readiness_band=readiness.band if readiness else None,
            red_flags=sum(1 for c in self.profile.cross_checks if c.status == "fail"),
            warnings=sum(1 for c in self.profile.cross_checks if c.status == "warn"),
            fit_label=self.match.fit_label,
            true_apr_pct=self.match.true_apr_pct,
            submitted_at=self.submitted_at,
            updated_at=self.updated_at,
            decision_message=self.decision.message_for_msme if self.decision else None,
        )


class ApplyRequest(BaseModel):
    """Same inputs as /v1/assess plus the loan request, the product and explicit consent."""

    sme_id: str
    # Only the SME's confirmations (user_confirmed) are taken from these; the file itself is the stored one.
    documents: list[DocumentEnvelope] = []
    bureau: BureauScore | None = None
    sector: str | None = None
    as_of: date | None = None
    request: LoanRequest
    product_id: str
    consent_accepted: bool = Field(description="Must be true: the MSME agreed to share its file with this lender")


class DecisionRequest(BaseModel):
    action: DecisionAction
    reason: DeclineReason | None = None
    note: str | None = Field(default=None, max_length=1000)
