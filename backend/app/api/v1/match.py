from fastapi import APIRouter

from app.recommendation import MatchResult, SMEProfile, load_lender_products, recommend

router = APIRouter(tags=["recommendation"])


# Takes the profile in the body for now; once the scoring stage stores profiles,
# this can take just an sme_id and load the validated profile itself.
@router.post("/match", response_model=list[MatchResult])
def match_lenders(profile: SMEProfile) -> list[MatchResult]:
    return recommend(profile, load_lender_products())
