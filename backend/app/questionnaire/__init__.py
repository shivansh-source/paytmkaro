"""Pre-qualification questionnaire: a few self-declared answers before any upload.

It turns 7 quick answers into (1) estimated engine inputs, (2) a "likely lenders" preview marked as an
estimate, and (3) a personalised document checklist. Everything here is self-declared and is replaced by
verified values once documents are assessed. Deterministic: no LLM decides anything.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.recommendation import MatchInput, MatchResult, load_lender_products, recommend
from app.schemas.common import Constitution, DocumentType
from app.validation.months import months_between

Sector = Literal["retail", "trading", "manufacturing", "services", "food", "other"]
SalesBand = Literal["under_10l", "10l_25l", "25l_1cr", "over_1cr"]
BounceBand = Literal["none", "1_2", "3_plus", "not_sure"]

# Conservative (lower-bound) turnover per band, so the preview never over-promises.
SALES_ESTIMATE: dict[str, int] = {"under_10l": 500_000, "10l_25l": 1_000_000, "25l_1cr": 2_500_000, "over_1cr": 10_000_000}
BOUNCES_ESTIMATE: dict[str, int | None] = {"none": 0, "1_2": 2, "3_plus": 3, "not_sure": None}


class Answers(BaseModel):
    """What the MSME tells us before uploading. All self-declared."""

    sector: Sector
    constitution: Constitution | Literal["not_sure"]
    started_year: int = Field(ge=1950, le=2100)
    started_month: int = Field(default=1, ge=1, le=12)
    annual_sales: SalesBand
    loan_amount: int = Field(gt=0)
    tenure_months: int = Field(gt=0, le=120)
    purpose: str = Field(default="Working capital", max_length=120)
    existing_emi_monthly: int = Field(default=0, ge=0)
    bounces_6m: BounceBand = "not_sure"
    has_gst: bool
    has_udyam: bool
    has_itr: bool
    credit_score: int | None = Field(default=None, ge=300, le=900)


class Estimates(BaseModel):
    business_vintage_months: int
    annual_turnover: int
    foir: float | None
    bounces_6m: int | None


DocumentStatus = Literal["required", "recommended", "optional", "not_needed"]


class ChecklistItem(BaseModel):
    document_type: DocumentType
    status: DocumentStatus
    why: str


class Prequalification(BaseModel):
    estimates: Estimates
    matches: list[MatchResult]  # estimates only: verified after upload
    checklist: list[ChecklistItem]
    notes: list[str]


def estimate(answers: Answers, as_of: date) -> Estimates:
    turnover = SALES_ESTIMATE[answers.annual_sales]
    monthly_income = turnover / 12
    return Estimates(
        business_vintage_months=max(0, months_between(date(answers.started_year, answers.started_month, 1), as_of)),
        annual_turnover=turnover,
        foir=round(answers.existing_emi_monthly / monthly_income, 3) if monthly_income else None,
        bounces_6m=BOUNCES_ESTIMATE[answers.bounces_6m],
    )


def match_input(answers: Answers, estimates: Estimates) -> MatchInput:
    return MatchInput(
        sme_id="PREQUAL",
        requested_amount=answers.loan_amount,
        requested_tenure_months=answers.tenure_months,
        business_vintage_months=estimates.business_vintage_months,
        annual_turnover=estimates.annual_turnover,
        bureau_score=answers.credit_score,
        foir=estimates.foir,
        bounces_6m=estimates.bounces_6m,
        gst_registered=answers.has_gst,
        constitution=None if answers.constitution == "not_sure" else answers.constitution,
        sector=answers.sector,
        has_itr=answers.has_itr,
        has_udyam=answers.has_udyam,
    )


def checklist(answers: Answers) -> list[ChecklistItem]:
    gst = "required" if answers.has_gst else "not_needed"
    no_gst_why = "You said you're not GST-registered. Some lenders need GST, so a few matches will need it later"
    return [
        ChecklistItem(document_type=DocumentType.PAN_CARD, status="required", why="Your identity, and the anchor for every cross-check"),
        ChecklistItem(document_type=DocumentType.AADHAAR, status="required", why="Name, date of birth and address. Only the last 4 digits are kept"),
        ChecklistItem(document_type=DocumentType.GST_REGISTRATION, status=gst,
                      why="Your business identity: GSTIN, legal name, address" if answers.has_gst else no_gst_why),
        ChecklistItem(document_type=DocumentType.GSTR3B, status=gst,
                      why="Your declared sales for the last 6 months" if answers.has_gst else no_gst_why),
        ChecklistItem(document_type=DocumentType.BANK_STATEMENT, status="required",
                      why="Your real cash flow: balances, EMIs and bounces, last 6-12 months"),
        ChecklistItem(document_type=DocumentType.UDYAM, status="required" if answers.has_udyam else "recommended",
                      why="Confirms your MSME status" if answers.has_udyam
                      else "Free and online at udyamregistration.gov.in, and some lenders require it"),
        ChecklistItem(document_type=DocumentType.ITR_V, status="recommended" if answers.has_itr else "optional",
                      why="Some lenders ask for it; you have one, so adding it opens more options" if answers.has_itr
                      else "Optional: only some lenders ask for it"),
    ]


def prequalify(answers: Answers, as_of: date | None = None) -> Prequalification:
    as_of = as_of or date.today()
    est = estimate(answers, as_of)
    notes = ["These are estimates from your answers. Upload documents and we verify every number."]
    if answers.credit_score is None:
        notes.append("Without a credit score, lenders that set a minimum show as 'not yet: add your bureau score'.")
    if answers.bounces_6m == "not_sure":
        notes.append("Your bank statement will show any bounces; we'll count them for you.")
    return Prequalification(
        estimates=est,
        matches=recommend(match_input(answers, est), load_lender_products(), "cost"),
        checklist=checklist(answers),
        notes=notes,
    )
