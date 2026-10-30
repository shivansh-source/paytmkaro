"""Lender recommendation: SME profile x lender criteria -> ranked, explained matches."""

from app.recommendation.adapter import match_input
from app.recommendation.engine import evaluate, recommend
from app.recommendation.lenders import load_lender_products
from app.recommendation.models import CheckResult, LenderProduct, MatchInput, MatchResult

__all__ = [
    "CheckResult",
    "LenderProduct",
    "MatchInput",
    "MatchResult",
    "evaluate",
    "load_lender_products",
    "match_input",
    "recommend",
]
