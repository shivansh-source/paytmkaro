"""Data contracts for the recommendation engine.

Lender records use the shared LenderProduct (app.schemas.lender, mirrored from
/schemas/v1/lender/lender_product.schema.json). Every criterion is optional: None
means "this lender has no such requirement". To filter on a new criterion, add a
rule in rules.py (and the profile field to MatchInput + adapter.py).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.lender import LenderProduct

__all__ = ["CheckResult", "Fix", "LenderProduct", "MatchInput", "MatchResult"]


class MatchInput(BaseModel):
    """Flat features the engine matches on. Build it from an SmeProfile + LoanRequest with
    recommendation.adapter.match_input(); /v1/match also accepts it directly.

    None means "not known yet" (document missing or not extracted). Rules report
    that as missing data instead of guessing.
    """

    sme_id: str = Field(min_length=1)
    requested_amount: int = Field(gt=0)
    requested_tenure_months: int | None = Field(default=None, gt=0)
    business_vintage_months: int | None = Field(default=None, ge=0)
    annual_turnover: int | None = Field(default=None, ge=0)
    # Not derivable from documents: mocked or self-declared until a bureau partnership exists.
    bureau_score: int | None = Field(default=None, ge=300, le=900)
    foir: float | None = Field(default=None, ge=0)
    bounces_6m: int | None = Field(default=None, ge=0)
    gst_registered: bool | None = None
    constitution: str | None = None
    sector: str | None = None
    has_itr: bool | None = None
    has_udyam: bool | None = None
    bank_statement_months: int | None = Field(default=None, ge=0)
    applicant_age_years: int | None = Field(default=None, ge=0)
    state: str | None = None  # business state, for lenders' negative geographies


# warn = below a soft cutoff: shown to the SME and costs fit, but does not block the match.
CheckOutcome = Literal["pass", "warn", "fail", "missing"]


class CheckResult(BaseModel):
    """Outcome of one rule against one lender product: the audit trail for a match."""

    rule: str
    outcome: CheckOutcome
    message: str
    required: Any = None
    actual: Any = None
    # 0-1, how comfortably a passing threshold is cleared; feeds the fit score.
    headroom: float | None = None


FixKind = Literal["change_request", "wait", "improve", "add_document", "add_info", "not_eligible"]


class Fix(BaseModel):
    """One concrete step from "not yet" to "matched", computed from a failed check."""

    rule: str
    kind: FixKind
    message: str  # "Ask for ₹12,00,000 or less", "Eligible in 10 months (Aug 2027)"
    months: int | None = None  # for kind == "wait"
    target: Any = None  # the value to reach, e.g. max amount or required score


class MatchResult(BaseModel):
    product_id: str
    lender: str
    product: str
    status: Literal["matched", "not_yet"]
    # 0-100, only for matched products.
    fit_score: float | None
    apr_range: tuple[float, float]
    processing_fee_pct: float
    scheme: str | None
    # Display lines: why it matched, or what to fix for "not yet".
    reasons: list[str]
    checks: list[CheckResult]
    # "Not yet" path: one fix per blocking check, most actionable first.
    fixes: list[Fix] = []
    # True when every fix is just a change to the request (amount / tenure): fixable right now.
    quick_fix: bool = False
