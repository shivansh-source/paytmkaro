"""Lender recommendation: SME profile x lender criteria -> ranked, explained matches."""

from app.recommendation.engine import evaluate, recommend
from app.recommendation.lenders import load_lender_products
from app.recommendation.models import CheckResult, LenderProduct, MatchResult, SMEProfile

__all__ = [
    "CheckResult",
    "LenderProduct",
    "MatchResult",
    "SMEProfile",
    "evaluate",
    "load_lender_products",
    "recommend",
]
