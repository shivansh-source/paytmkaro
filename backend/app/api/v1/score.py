from fastapi import APIRouter

from app.api.v1.assess import AssessRequest
from app.assessment import ScoreCard, score_sme
from app.scoring import assess

router = APIRouter(tags=["assessment"])


@router.post("/score", response_model=ScoreCard)
def score_documents(body: AssessRequest) -> ScoreCard:
    """Indicative lender-facing assessment: same body as /v1/assess. Not a credit decision, not used for matching."""
    assessment = assess(body.sme_id, body.documents, bureau=body.bureau, sector=body.sector, as_of=body.as_of)
    return score_sme(assessment.profile, assessment.documents, as_of=body.as_of or assessment.profile.updated_at.date())
