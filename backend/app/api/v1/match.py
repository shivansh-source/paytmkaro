from fastapi import APIRouter
from pydantic import BaseModel

from app.recommendation import MatchInput, MatchResult, load_lender_products, match_input, recommend
from app.schemas import LoanRequest, SmeProfile

router = APIRouter(tags=["recommendation"])


@router.post("/match", response_model=list[MatchResult])
def match_lenders(profile: MatchInput) -> list[MatchResult]:
    """Match on flat features. Handy for testing rules; the dashboard uses /match/profile."""
    return recommend(profile, load_lender_products())


class ProfileMatchRequest(BaseModel):
    profile: SmeProfile
    request: LoanRequest


@router.post("/match/profile", response_model=list[MatchResult])
def match_profile(body: ProfileMatchRequest) -> list[MatchResult]:
    """Match an assessed SmeProfile (from /assess) against every lender for one loan request."""
    return recommend(match_input(body.profile, body.request), load_lender_products())
