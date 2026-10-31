from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import workspace
from app.accounts import Account
from app.api.deps import current_msme, db
from app.storage import Database
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


@router.post("/samples/{applicant}/load", response_model=SampleApplicant)
def load_sample_into_file(applicant: Literal["a", "b"], account: Account = Depends(current_msme),
                          database: Database = Depends(db)) -> SampleApplicant:
    """Replace the signed-in SME's stored documents with a sample applicant's, so applying works the same
    way as with uploaded files. Returns a ready /v1/assess body under the SME's own id."""
    sample = sample_applicant(applicant)
    documents = workspace.replace_with(database, account.id, sample.documents)
    return sample.model_copy(update={"sme_id": account.id, "documents": documents})
