from datetime import date
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.samples import AS_OF, BUREAU_A, BUREAU_B, applicant_a, applicant_b
from app.schemas import BureauScore, DocumentEnvelope

router = APIRouter(tags=["samples"])


class SampleApplicant(BaseModel):
    """A ready-made /v1/assess request body. SAMPLE data, for demos before extraction is wired in."""

    sme_id: str
    label: str
    documents: list[DocumentEnvelope]
    bureau: BureauScore
    sector: str
    as_of: date


@router.get("/samples/{applicant}", response_model=SampleApplicant)
def sample_applicant(applicant: Literal["a", "b"]) -> SampleApplicant:
    if applicant == "a":
        return SampleApplicant(sme_id="SAMPLE-A", label="Applicant A (clean file)", documents=applicant_a(),
                               bureau=BUREAU_A, sector="retail", as_of=AS_OF)
    return SampleApplicant(sme_id="SAMPLE-B", label="Applicant B (needs work)", documents=applicant_b(),
                           bureau=BUREAU_B, sector="retail", as_of=AS_OF)
