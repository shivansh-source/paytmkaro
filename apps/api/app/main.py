from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[1]
LENDER_SAMPLE_PATH = BASE_DIR / "schemas" / "lenders" / "v1" / "lender_products.sample.json"

app = FastAPI(title="CreditSetu API", version="0.1.0")


class DocumentUploadRequest(BaseModel):
    sme_id: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    file_name: str = Field(min_length=1)


class DocumentUploadResponse(BaseModel):
    job_id: str
    status: Literal["queued"]
    next_step: str


class MatchRequest(BaseModel):
    sme_id: str = Field(min_length=1)
    requested_amount: int = Field(gt=0)
    business_vintage_months: int = Field(ge=0)
    annual_turnover: int = Field(ge=0)
    bureau_score: int = Field(ge=300, le=900)
    foir: float = Field(ge=0, le=1)
    bounces_6m: int = Field(ge=0)
    constitution: str = Field(min_length=1)
    sector: str = Field(min_length=1)


class MatchResult(BaseModel):
    lender: str
    product: str
    status: Literal["matched", "not_yet"]
    reasons: list[str]
    apr_range: list[float]


def load_lender_products() -> list[dict]:
    with LENDER_SAMPLE_PATH.open("r", encoding="utf-8") as schema_file:
        payload = json.load(schema_file)
    return payload.get("products", [])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/documents", response_model=DocumentUploadResponse)
def create_document_upload(request: DocumentUploadRequest) -> DocumentUploadResponse:
    return DocumentUploadResponse(
        job_id=f"job-{request.sme_id}-{request.document_type}",
        status="queued",
        next_step="Run extraction + cross-document checks asynchronously",
    )


@app.get("/v1/profile/{sme_id}")
def get_validated_profile(sme_id: str) -> dict:
    return {
        "sme_id": sme_id,
        "kyc_status": "pending",
        "readiness_score": 0,
        "message": "Skeleton profile. Hook document extraction pipeline here.",
    }


@app.post("/v1/match", response_model=list[MatchResult])
def match_lenders(request: MatchRequest) -> list[MatchResult]:
    products = load_lender_products()
    output: list[MatchResult] = []

    for item in products:
        reasons: list[str] = []
        status: Literal["matched", "not_yet"] = "matched"

        if request.requested_amount < item["ticket_size"]["min"] or request.requested_amount > item["ticket_size"]["max"]:
            status = "not_yet"
            reasons.append("Requested amount is outside lender ticket size")
        if request.business_vintage_months < item["min_business_vintage_months"]:
            status = "not_yet"
            reasons.append(
                f"Needs {item['min_business_vintage_months']} months vintage, you have {request.business_vintage_months}"
            )
        if request.annual_turnover < item["min_annual_turnover"]:
            status = "not_yet"
            reasons.append("Annual turnover below lender minimum")
        if request.bureau_score < item["min_bureau_score"]:
            status = "not_yet"
            reasons.append("Bureau score below lender minimum")
        if request.foir > item["max_foir"]:
            status = "not_yet"
            reasons.append("FOIR is above lender limit")
        if request.bounces_6m > item["max_bounces_6m"]:
            status = "not_yet"
            reasons.append("Bounce count exceeds lender limit")
        if request.constitution not in item["allowed_constitutions"]:
            status = "not_yet"
            reasons.append("Business constitution is not supported")
        if request.sector in item["excluded_sectors"]:
            status = "not_yet"
            reasons.append("Sector is excluded by lender policy")

        output.append(
            MatchResult(
                lender=item["lender"],
                product=item["product"],
                status=status,
                reasons=reasons or ["Eligible based on submitted fields"],
                apr_range=item["pricing"]["apr_range"],
            )
        )

    return sorted(output, key=lambda x: (x.status != "matched", x.apr_range[0]))


@app.get("/v1/offers/{offer_id}/explain")
def explain_offer(offer_id: str, language: str = "en") -> dict:
    return {
        "offer_id": offer_id,
        "language": language,
        "kfs": {
            "true_apr": "18.0% - 20.0%",
            "emi": "₹ 38,000 (example)",
            "total_payback": "₹ 13,68,000 (example)",
            "cooling_off": "You can cancel within the lender's cooling-off window.",
        },
    }
