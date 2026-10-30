from fastapi import APIRouter
from pydantic import BaseModel

from app.recommendation import MatchInput, MatchResult, load_lender_products, match_input, recommend
from app.recommendation.models import SortOrder
from app.schemas import LoanRequest, SmeProfile

router = APIRouter(tags=["recommendation"])


@router.post("/match", response_model=list[MatchResult])
def match_lenders(profile: MatchInput, sort: SortOrder = "cost") -> list[MatchResult]:
    """Match on flat features. Handy for testing rules; the dashboard uses /match/profile."""
    return recommend(profile, load_lender_products(), sort)


class ProfileMatchRequest(BaseModel):
    profile: SmeProfile
    request: LoanRequest


@router.post("/match/profile", response_model=list[MatchResult])
def match_profile(body: ProfileMatchRequest, sort: SortOrder = "cost") -> list[MatchResult]:
    """Match an assessed SmeProfile (from /assess) against every lender for one loan request.

    `sort=cost` (default): lowest true APR first. `sort=fit`: most comfortable fit first. Matched lenders
    always come before "not yet" ones; the borrower chooses the order and the UI says which is active.
    """
    return recommend(match_input(body.profile, body.request), load_lender_products(), sort)
