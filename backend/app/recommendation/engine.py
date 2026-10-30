"""Recommendation engine: hard filters, then fit score, then rank.

Deterministic by design. Every number comes from code and every result carries
the checks that produced it. An LLM may narrate these results, but never
decides them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.recommendation.fixes import suggest_fixes
from app.recommendation.models import LenderProduct, MatchInput, MatchResult
from app.recommendation.rules import RULES, Rule

BLOCKING = {"fail", "missing"}


def evaluate(profile: MatchInput, product: LenderProduct, rules: Sequence[Rule] = RULES) -> MatchResult:
    """Run every rule for one product. Any failed or missing check makes it "not yet".

    A "warn" (soft cutoff, collateral above the free limit) is shown but doesn't block; it counts as
    zero headroom in the fit score.
    """
    checks = [check for rule in rules if (check := rule(profile, product)) is not None]
    blockers = [check for check in checks if check.outcome in BLOCKING]

    if blockers:
        fixes = suggest_fixes(blockers, profile, product)
        status, fit_score, reasons = "not_yet", None, [check.message for check in blockers]
    else:
        # Fit = average headroom across the numeric thresholds; a product with
        # no thresholds has nothing to clear and counts as a full fit.
        headrooms = [check.headroom for check in checks if check.headroom is not None]
        fit = sum(headrooms) / len(headrooms) if headrooms else 1.0
        fixes = []
        warnings = [check.message for check in checks if check.outcome == "warn"]
        passes = [check.message for check in checks if check.outcome == "pass"]
        status, fit_score, reasons = "matched", round(fit * 100, 1), warnings + passes

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
        fixes=fixes,
        quick_fix=bool(fixes) and all(f.kind == "change_request" for f in fixes),
    )


def _rank_key(result: MatchResult) -> tuple:
    # Matched: best fit first, then cheapest APR.
    # Not yet: quick fixes (just change the request) first, then fewest fixes, then cheapest APR.
    if result.status == "matched":
        return (0, -(result.fit_score or 0), result.apr_range[0])
    return (1, not result.quick_fix, len(result.fixes), result.apr_range[0])


def recommend(profile: MatchInput, products: Iterable[LenderProduct]) -> list[MatchResult]:
    """Evaluate every product and return them ranked, matched first."""
    return sorted((evaluate(profile, product) for product in products), key=_rank_key)
