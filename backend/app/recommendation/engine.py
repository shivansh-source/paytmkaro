"""Recommendation engine: hard filters, then fit score, then rank.

Deterministic by design. Every number comes from code and every result carries
the checks that produced it. An LLM may narrate these results, but never
decides them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.recommendation.models import LenderProduct, MatchResult, SMEProfile
from app.recommendation.rules import RULES, Rule


def evaluate(profile: SMEProfile, product: LenderProduct, rules: Sequence[Rule] = RULES) -> MatchResult:
    """Run every rule for one product. Any failed or missing check makes it "not yet"."""
    checks = [check for rule in rules if (check := rule(profile, product)) is not None]
    blockers = [check for check in checks if check.outcome != "pass"]

    if blockers:
        status, fit_score, reasons = "not_yet", None, [check.message for check in blockers]
    else:
        # Fit = average headroom across the numeric thresholds; a product with
        # no thresholds has nothing to clear and counts as a full fit.
        headrooms = [check.headroom for check in checks if check.headroom is not None]
        fit = sum(headrooms) / len(headrooms) if headrooms else 1.0
        status, fit_score, reasons = "matched", round(fit * 100, 1), [check.message for check in checks]

    return MatchResult(
        product_id=product.id,
        lender=product.lender,
        product=product.product,
        status=status,
        fit_score=fit_score,
        apr_range=product.pricing.apr_range,
        processing_fee_pct=product.pricing.processing_fee_pct,
        scheme=product.scheme,
        reasons=reasons,
        checks=checks,
    )


def _rank_key(result: MatchResult) -> tuple:
    # Matched: best fit first, then cheapest APR.
    # Not yet: fewest things to fix first (closest to eligible), then cheapest APR.
    if result.status == "matched":
        return (0, -(result.fit_score or 0), result.apr_range[0])
    return (1, len(result.reasons), result.apr_range[0])


def recommend(profile: SMEProfile, products: Iterable[LenderProduct]) -> list[MatchResult]:
    """Evaluate every product and return them ranked, matched first."""
    return sorted((evaluate(profile, product) for product in products), key=_rank_key)
