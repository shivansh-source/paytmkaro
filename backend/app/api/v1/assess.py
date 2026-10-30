from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas import BureauScore, DocumentEnvelope
from app.scoring import Assessment, assess

router = APIRouter(tags=["assessment"])


class AssessRequest(BaseModel):
    sme_id: str
    documents: list[DocumentEnvelope]  # extraction output
    bureau: BureauScore | None = None
    sector: str | None = None
    as_of: date | None = None  # defaults to today; fixed in tests and demos


@router.post("/assess", response_model=Assessment)
def assess_documents(body: AssessRequest) -> Assessment:
    """Validate extracted documents and build the SmeProfile: checks, metrics, readiness, fix-it list."""
    return assess(body.sme_id, body.documents, bureau=body.bureau, sector=body.sector, as_of=body.as_of)
