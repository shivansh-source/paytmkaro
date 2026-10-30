"""Lender product criteria: one record per lender product (ported from Anansh's v1.0.0 JSON Schema).

Core fields are what the recommendation engine filters on today (ticket size, tenure, vintage,
turnover, bureau score, FOIR, bounces, GST, constitution, sector, pricing). Every other field supports
lender research and the lender dashboard. Unknown values are omitted or null; published values,
inferences and assumptions stay distinguishable through `source_records` / `source_confidence`.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import Constitution, Schema

LENDER_SCHEMA_VERSION = "1.0.0"

InstitutionType = Literal["bank", "small_finance_bank", "cooperative_bank", "nbfc", "platform", "lsp", "other", "unknown"]
InstitutionRole = Literal["regulated_lender", "lending_platform", "lsp", "channel_partner", "unknown"]
ProductType = Literal[
    "term_loan",
    "working_capital",
    "cash_credit",
    "overdraft",
    "dropline_overdraft",
    "invoice_finance",
    "equipment_finance",
    "letter_of_credit",
    "bank_guarantee",
    "composite",
    "other",
    "unknown",
]
AgeCheckedAt = Literal["application", "sanction", "maturity", "disbursal", "unknown"]
SourceConfidence = Literal["public", "inferred", "assumed", "conflicting", "unverified"]
RecordStatus = Literal["draft", "needs_review", "approved", "active", "expired", "archived"]
SourceType = Literal[
    "official_product_page",
    "official_eligibility_page",
    "official_fees_page",
    "official_kfs",
    "official_mitc",
    "official_policy",
    "supplied_workbook",
    "government_scheme_page",
    "borrower_provided",
    "lender_portal",
    "inferred",
    "assumed",
    "other",
]
ReviewStatus = Literal["pending", "approved", "rejected", "needs_update"]
Requiredness = Literal["mandatory", "conditional", "optional", "additional_on_request", "unknown"]
AprBasis = Literal["all_in_apr", "nominal_interest_rate_proxy", "unknown"]
InterestType = Literal["fixed", "floating", "hybrid", "benchmark_linked", "unknown"]
InterestBasis = Literal["reducing_balance", "daily_reducing", "flat", "unknown"]
ResolutionStatus = Literal["unresolved", "resolved", "needs_lender_confirmation"]


# ---- Ranges --------------------------------------------------------------------------------------


class _IntRange(Schema):
    min: int = Field(ge=0)
    max: int = Field(ge=0)
    min_inclusive: bool = True
    max_inclusive: bool = True

    @model_validator(mode="after")
    def _ordered(self):
        if self.min > self.max:
            raise ValueError(f"min ({self.min}) is greater than max ({self.max})")
        return self


class InrRange(_IntRange):
    """Rupee range."""


class MonthRange(_IntRange):
    """Range in months."""


class NumberRange(Schema):
    min: float | None = None
    max: float | None = None
    unit: str | None = None


# ---- Building blocks -----------------------------------------------------------------------------


class Pricing(Schema):
    apr_range: tuple[float, float] = Field(
        description="All-in APR percent per annum as [min,max]. Do not substitute nominal interest rate "
        "unless marked as a proxy."
    )
    processing_fee_pct: float = Field(ge=0, description="Percent points; use 2 for 2%, not 0.02.")
    interest_rate_range_pct_pa: NumberRange | None = None
    apr_basis: AprBasis = "unknown"
    interest_type: InterestType = "unknown"
    interest_basis: InterestBasis = "unknown"
    benchmark: str | None = None
    benchmark_rate_pct_pa: float | None = None
    spread_pct_pa: float | None = None
    reset_frequency_months: float | None = Field(default=None, ge=0)
    indicative_only: bool = True
    pricing_factors: list[str] = []
    notes: str | None = None

    @model_validator(mode="after")
    def _apr_ordered(self):
        low, high = self.apr_range
        if low < 0 or low > high:
            raise ValueError(f"apr_range must be [min, max] with 0 <= min <= max, got {list(self.apr_range)}")
        return self


class AmountTier(Schema):
    name: str
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)
    min_inclusive: bool = True
    max_inclusive: bool = True
    conditions: list[str] = []


class FacilityTenure(Schema):
    facility: str
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, ge=0)
    moratorium_max_months: float | None = Field(default=None, ge=0)
    notes: str | None = None


class ConstitutionRule(Schema):
    constitution: Constitution
    min_business_vintage_months: float | None = Field(default=None, ge=0)
    notes: str | None = None


class Charge(Schema):
    charge_type: str
    amount_inr: float | None = Field(default=None, ge=0)
    rate_pct: float | None = Field(default=None, ge=0)
    rate_pct_pa: float | None = Field(default=None, ge=0)
    basis: str | None = None
    trigger: str | None = None
    frequency: str | None = None
    tax_applicable: bool | None = None
    tax_included: bool | None = None
    conditions: list[str] = []
    source_record_index: int | None = Field(default=None, ge=0)


class DocumentRequirement(Schema):
    # Free text, not DocumentType: lenders ask for documents we don't extract yet (balance sheet, CMA...).
    document_type: str
    requiredness: Requiredness = "unknown"
    applicant_scope: str | None = None
    lookback_months: float | None = Field(default=None, ge=0)
    accepted_formats: list[str] = []
    condition: str | None = None
    validation_checks: list[str] = []


class Guarantee(Schema):
    scheme: str | None = None
    coverage_pct: float | None = Field(default=None, ge=0, le=100)
    premium_borne_by: str | None = None
    conditions: list[str] = []


class MarginTier(Schema):
    up_to_inr: int | None = Field(default=None, ge=0)
    margin_pct: float | None = Field(default=None, ge=0, le=100)
    conditions: list[str] = []


class Margin(Schema):
    working_capital_pct: float | None = Field(default=None, ge=0, le=100)
    term_loan_pct: float | None = Field(default=None, ge=0, le=100)
    tiers: list[MarginTier] = []


class ScoreThresholds(Schema):
    overall_pct: float | None = Field(default=None, ge=0, le=100)
    subscore_pct: float | None = Field(default=None, ge=0, le=100)
    subheads: list[str] = []
    go_no_go_rule: str | None = None
    notes: str | None = None


class Condition(Schema):
    description: str
    applies_when: str | None = None
    effect: str | None = None
    source_record_index: int | None = Field(default=None, ge=0)


class KfsRequirements(Schema):
    kfs_required: bool | None = None
    unique_proposal_number_required: bool | None = None
    minimum_validity_working_days: int | None = Field(default=None, ge=0)
    apr_computation_required: bool | None = None
    amortization_schedule_required: bool | None = None
    third_party_charges_in_apr: bool | None = None
    summary_box_in_loan_agreement: bool | None = None
    borrower_explanation_acknowledgement_required: bool | None = None
    language_requirement: str | None = None
    notes: str | None = None


class SourceRecord(Schema):
    source_type: SourceType
    url: str | None = None
    document_name: str | None = None
    locator: str | None = None
    captured_at: date
    effective_from: date | None = None
    effective_to: date | None = None
    confidence: SourceConfidence
    review_status: ReviewStatus = "pending"
    notes: str | None = None


class Conflict(Schema):
    field: str
    description: str
    source_record_indexes: list[int] = []
    resolution_status: ResolutionStatus = "unresolved"
    resolution_note: str | None = None


# ---- The record ----------------------------------------------------------------------------------


class LenderProduct(Schema):
    """One lender product's criteria, pricing and evidence. None / [] = not stated by the lender."""

    schema_version: Literal["1.0.0"] = LENDER_SCHEMA_VERSION

    # Identity
    id: str = Field(min_length=1, description="Stable lender-product identifier.")
    lender: str = Field(min_length=1)
    legal_entity_name: str | None = None
    institution_type: InstitutionType = "unknown"
    institution_role: InstitutionRole = "unknown"
    product: str = Field(min_length=1)
    product_type: ProductType = "unknown"
    scheme: str | None = None
    purpose: list[str] = []
    target_segment: list[str] = []
    eligible_sectors: list[str] = []

    # Amount and tenure
    ticket_size: InrRange | None = None
    ticket_size_tiers: list[AmountTier] = []
    ticket_size_conditions: list[str] = []
    tenure_months: MonthRange | None = None
    tenure_by_facility: list[FacilityTenure] = []
    moratorium_max_months: float | None = Field(default=None, ge=0)
    moratorium_included_in_tenure: bool | None = None
    repayment_frequency: list[str] = []
    repayment_modes: list[str] = []
    repayment_on_demand: bool | None = None
    renewal_period_months: float | None = Field(default=None, gt=0)

    # Business and financial eligibility
    min_business_vintage_months: int | None = Field(default=None, ge=0)
    min_business_vintage_by_constitution: list[ConstitutionRule] = []
    min_annual_turnover: int | None = Field(default=None, ge=0)
    turnover_period_months: float | None = Field(default=None, gt=0)
    minimum_profit_history_months: float | None = Field(default=None, ge=0)
    profit_required: bool | None = None

    # Credit history
    min_bureau_score: int | None = Field(default=None, ge=300, le=900)
    bureau_score_type: str | None = None
    bureau_score_is_hard_cutoff: bool | None = None
    max_foir: float | None = Field(default=None, ge=0, le=1, description="Ratio between 0 and 1.")
    max_bounces_6m: int | None = Field(default=None, ge=0)
    commercial_cic_required: bool | None = None
    consumer_cic_required: bool | None = None
    credit_history_conditions: list[str] = []
    loan_default_hard_filter: bool | None = None

    # Registrations and documents
    gst_required: bool = False
    udyam_required: bool | None = None
    udyam_preferred: bool | None = None
    gst_registration_vintage_months: float | None = Field(default=None, ge=0)
    min_bank_statement_months: float | None = Field(default=None, ge=0)
    max_bank_statement_months: float | None = Field(default=None, ge=0)
    itr_required: bool | None = None
    itr_years_required: int | None = Field(default=None, ge=0)
    business_registration_required: bool | None = None
    min_current_account_vintage_months: float | None = Field(default=None, ge=0)

    # Applicant
    min_age_years: float | None = Field(default=None, ge=0)
    max_age_years: float | None = Field(default=None, ge=0)
    age_checked_at: AgeCheckedAt = "unknown"
    allowed_constitutions: list[Constitution] | None = None
    excluded_sectors: list[str] = []
    excluded_entities: list[str] = []
    negative_geographies: list[str] = []

    # Security
    collateral: str = Field(
        default="none",
        description="Backend-compatible string, e.g. none, required, conditional, or detailed rule text.",
    )
    collateral_free_limit: int | None = Field(default=None, ge=0)
    collateral_conditions: list[str] = []
    primary_security: list[str] = []
    personal_guarantee_required: bool | None = None
    credit_guarantee: Guarantee | None = None
    margin: Margin | None = None
    facilities_available: list[str] = []

    # Pricing and charges
    pricing: Pricing
    charges: list[Charge] = []

    # Process
    documents_required: list[DocumentRequirement] = []
    required_checks: list[str] = []
    internal_score_thresholds: ScoreThresholds | None = None
    risk_gradation_factors: list[str] = []
    eligibility_exceptions: list[Condition] = []
    negative_list_notes: str | None = None
    approval_time_hours: NumberRange | None = None
    disbursal_time_hours: NumberRange | None = None
    kfs_requirements: KfsRequirements | None = None
    cross_sell: list[str] = []
    application_languages: list[str] = []
    data_consents: list[str] = []
    data_rights_notes: str | None = None
    co_lending_or_partner_notes: str | None = None

    # Evidence and lifecycle
    source_records: list[SourceRecord] = []
    source_confidence: SourceConfidence = "unverified"
    conflicts_and_gaps: list[Conflict] = []
    effective_from: date | None = None
    effective_to: date | None = None
    last_verified_at: date | None = None
    record_status: RecordStatus = "draft"
    extensions: dict[str, Any] = Field(
        default={},
        description="Namespaced fields for project-specific criteria not yet promoted into the stable schema.",
    )


class LenderCatalog(Schema):
    """The shape of backend/data/lenders.json."""

    products: list[LenderProduct]
