"""Lender-facing SME assessment: a transparent, weighted, parameter-by-parameter view of credit-relevant signals.

`score_sme(profile, documents, as_of=...)` is the one entry point. It is separate from the readiness score in
app.scoring (which measures how complete and consistent the FILE is) and it is NOT fed into lender matching.
See DESIGN.md for the parameter registry, the math, the field lock and what can honestly be claimed.
"""

from app.assessment.config import AssessmentConfig, load_config
from app.assessment.models import Coverage, FeatureTable, ParameterResult, ScoreCard
from app.assessment.registry import REGISTRY, Parameter
from app.assessment.scorer import score_sme

__all__ = [
    "AssessmentConfig",
    "Coverage",
    "FeatureTable",
    "Parameter",
    "ParameterResult",
    "REGISTRY",
    "ScoreCard",
    "load_config",
    "score_sme",
]
