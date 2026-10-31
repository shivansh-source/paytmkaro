"""SmeProfile: the validated, scored view of one MSME.

Built by our code from verified documents. The MSME dashboard renders it, the recommendation engine
matches on it (via recommendation.adapter), and lenders receive it with evidence links.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import (
    SCHEMA_VERSION,
    Address,
    Check,
    Constitution,
    DocumentType,
    MsmeCategory,
    Schema,
    Sourced,
)
from app.schemas.documents import DocumentStatus


class Identity(Schema):
    """Fields stay None until the document that provides them is uploaded."""

    legal_name: Sourced[str] | None = None
    trade_name: Sourced[str] | None = None
    constitution: Sourced[Constitution] | None = None
    pan: Sourced[str] | None = None
    promoter_dob: Sourced[date] | None = None  # proprietor / main promoter, from PAN; for lender age limits
    gstin: Sourced[str] | None = None
    udyam_number: Sourced[str] | None = None
    msme_category: Sourced[MsmeCategory] | None = None
    date_of_incorporation: Sourced[date] | None = None
    business_vintage_months: Sourced[int] | None = None
    address: Sourced[Address] | None = None
    sector: str | None = None  # self-declared until we map Udyam NIC codes


class CashflowMetrics(Schema):
    """Deterministic metrics from bank statements and GSTR-3B. None = not computable yet."""

    months_analyzed: int = Field(ge=0)
    avg_monthly_balance: Sourced[float] | None = None
    avg_monthly_credits: Sourced[float] | None = None
    bounces_6m: Sourced[int] | None = None
    existing_emi_monthly: Sourced[float] | None = None
    foir: Sourced[float] | None = None  # existing EMIs / average monthly credits
    gst_turnover_12m: Sourced[float] | None = None  # annualised if fewer than 12 months filed
    gst_vs_bank_ratio: Sourced[float] | None = None  # GST turnover / bank credits, same months


class BureauScore(Schema):
    value: int = Field(ge=300, le=900)
    source: Literal["mock", "self_declared", "bureau"]
    as_of: date | None = None
    cmr_rank: int | None = Field(default=None, ge=1, le=10)
    max_dpd_24m: int | None = Field(default=None, ge=0, le=999)
    enquiries_90d: int | None = Field(default=None, ge=0)
    written_off_or_settled: bool | None = None
    suit_filed_or_wilful_default: bool | None = None
    active_accounts: int | None = Field(default=None, ge=0)
    overdue_amount: float | None = Field(default=None, ge=0)


class ReadinessComponent(Schema):
    name: str  # "Documents complete", "KYC verified", "Cash flow"...
    points: float = Field(ge=0)
    max_points: float = Field(gt=0)
    note: str | None = None


class Readiness(Schema):
    """0-100, computed in code. The LLM may explain it but never sets it."""

    score: int = Field(ge=0, le=100)
    band: Literal["not_ready", "almost_ready", "ready"]
    components: list[ReadinessComponent] = []


class FixItItem(Schema):
    id: str
    priority: Literal["high", "medium", "low"]
    title: str  # "Upload your bank statement for March 2026"
    detail: str | None = None
    action: Literal["upload", "re_upload", "confirm_field", "add_info"]
    check_id: str | None = None  # the check that produced this item
    document_type: DocumentType | None = None


class DocumentSummary(Schema):
    document_id: str
    document_type: DocumentType
    status: DocumentStatus


class SmeProfile(Schema):
    schema_version: Literal["1.0", "1.1", "1.2"] = SCHEMA_VERSION
    sme_id: str
    updated_at: datetime
    identity: Identity
    cashflow: CashflowMetrics
    bureau: BureauScore | None = None
    documents: list[DocumentSummary] = []
    cross_checks: list[Check] = []
    readiness: Readiness | None = None
    fix_it: list[FixItItem] = []


class LoanRequest(Schema):
    """What the SME is asking for. Kept apart from the profile: one profile, many requests."""

    sme_id: str
    amount: int = Field(gt=0)  # rupees
    tenure_months: int | None = Field(default=None, gt=0)
    purpose: str | None = None
