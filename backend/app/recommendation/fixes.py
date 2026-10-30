"""The "not yet" path: turn each blocking check into one concrete step, computed from the numbers.

"Business vintage: needs 24 months, you have 14" becomes "Eligible in 10 months". The SME sees what to
change, not just what failed. All deterministic.
"""

from __future__ import annotations

from collections.abc import Callable

from app.recommendation.models import CheckResult, Fix, LenderProduct, MatchInput
from app.recommendation.rules import inr

# Most actionable first: things the SME can change in the form right now, then documents, then time.
KIND_ORDER = {"change_request": 0, "add_info": 1, "add_document": 2, "improve": 3, "wait": 4, "not_eligible": 5}

FixBuilder = Callable[[CheckResult, MatchInput, LenderProduct], Fix | None]


def _ticket_size(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    lo, hi = c.required
    if p.requested_amount > hi:
        return Fix(rule=c.rule, kind="change_request", message=f"Ask for {inr(hi)} or less", target=hi)
    return Fix(rule=c.rule, kind="change_request", message=f"This lender's minimum loan is {inr(lo)}", target=lo)


def _tenure(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    lo, hi = c.required
    return Fix(rule=c.rule, kind="change_request", message=f"Choose a tenure between {lo} and {hi} months", target=[lo, hi])


def _vintage(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    wait = int(c.required - c.actual)
    return Fix(rule=c.rule, kind="wait", months=wait, target=c.required,
               message=f"Eligible in {wait} month{'s' if wait != 1 else ''}, when your business turns {c.required:g} months old")


def _turnover(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    short = c.required - c.actual
    return Fix(rule=c.rule, kind="improve", target=c.required,
               message=f"Grow annual turnover by {inr(short)} (to {inr(c.required)}), or file the GST returns that show it")


def _bureau(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    return Fix(rule=c.rule, kind="improve", target=c.required,
               message=f"Raise your bureau score by {c.required - c.actual} points (to {c.required}): pay every EMI and card bill on time")


def _foir(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    cut = 1 - c.required / c.actual
    return Fix(rule=c.rule, kind="improve", target=c.required,
               message=f"Reduce existing EMIs by about {cut:.0%} (FOIR from {c.actual:.0%} to {c.required:.0%}), e.g. close a small loan first")


def _bounces(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    return Fix(rule=c.rule, kind="wait", months=6, target=c.required,
               message=f"Keep bounces to {c.required} or fewer: older bounces drop out of the 6-month window")


def _document(name: str) -> FixBuilder:
    return lambda c, p, product: Fix(rule=c.rule, kind="add_document", message=f"Upload your {name}")


def _not_eligible(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    return Fix(rule=c.rule, kind="not_eligible", message=c.message)


def _bank_months(c: CheckResult, p: MatchInput, product: LenderProduct) -> Fix:
    return Fix(rule=c.rule, kind="add_document", target=c.required,
               message=f"Upload {c.required:g} months of bank statements (you have {c.actual:g})")


BUILDERS: dict[str, FixBuilder] = {
    "ticket_size": _ticket_size,
    "tenure": _tenure,
    "business_vintage": _vintage,
    "annual_turnover": _turnover,
    "bureau_score": _bureau,
    "foir": _foir,
    "bounces_6m": _bounces,
    "bank_statement_months": _bank_months,
    "gst_registration": lambda c, p, product: Fix(rule=c.rule, kind="add_document", message="Register for GST and upload the certificate"),
    "itr": _document("ITR-V"),
    "udyam": lambda c, p, product: Fix(rule=c.rule, kind="add_document", message="Register on the Udyam portal (free) and upload the certificate"),
    "constitution": _not_eligible,
    "sector": _not_eligible,
    "eligible_sectors": _not_eligible,
    "geography": _not_eligible,
    "min_age": _not_eligible,
    "max_age": _not_eligible,
}


def suggest_fixes(checks: list[CheckResult], profile: MatchInput, product: LenderProduct) -> list[Fix]:
    fixes: list[Fix] = []
    for c in checks:
        if c.outcome == "missing":
            fixes.append(Fix(rule=c.rule, kind="add_info", message=c.message.replace("not available yet; ", "")))
        elif c.outcome == "fail":
            builder = BUILDERS.get(c.rule, _not_eligible)
            if (fix := builder(c, profile, product)) is not None:
                fixes.append(fix)
    return sorted(fixes, key=lambda f: KIND_ORDER[f.kind])
