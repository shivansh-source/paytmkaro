"""Data contracts for the recommendation engine.

Field sets are still being decided. Every lender criterion is optional, where
None means "this lender has no such requirement", so a new criterion can be
added here (plus one rule in rules.py) without editing existing lender records.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Range(BaseModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)


class Pricing(BaseModel):
    apr_range: tuple[float, float]
    processing_fee_pct: float = Field(ge=0)


class LenderProduct(BaseModel):
    """One lender product's eligibility criteria and pricing."""

    id: str = Field(min_length=1)
    lender: str
    product: str
    ticket_size: Range | None = None
    tenure_months: Range | None = None
    min_business_vintage_months: int | None = Field(default=None, ge=0)
    min_annual_turnover: int | None = Field(default=None, ge=0)
    min_bureau_score: int | None = Field(default=None, ge=300, le=900)
    max_foir: float | None = Field(default=None, ge=0, le=1)
    max_bounces_6m: int | None = Field(default=None, ge=0)
    gst_required: bool = False
    allowed_constitutions: list[str] | None = None
    excluded_sectors: list[str] = []
    collateral: str = "none"
    scheme: str | None = None
    pricing: Pricing


class SMEProfile(BaseModel):
    """Features the engine matches on, as produced by the cash-flow scoring stage.

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


CheckOutcome = Literal["pass", "fail", "missing"]


class CheckResult(BaseModel):
    """Outcome of one rule against one lender product: the audit trail for a match."""

    rule: str
    outcome: CheckOutcome
    message: str
    required: Any = None
    actual: Any = None
    # 0-1, how comfortably a passing threshold is cleared; feeds the fit score.
    headroom: float | None = None


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
