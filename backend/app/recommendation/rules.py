"""Hard-filter rules, one per lender criterion.

A rule takes (profile, product) and returns a CheckResult, or None when the
lender does not set that criterion. To add a criterion: add the field to
LenderProduct (and the profile field it is compared with to MatchInput), then
add one entry to RULES.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.recommendation.models import CheckResult, LenderProduct, MatchInput

Rule = Callable[[MatchInput, LenderProduct], CheckResult | None]


def inr(amount: float) -> str:
    """Format rupees with Indian digit grouping: 1500000 -> ₹15,00,000."""
    digits = str(int(round(amount)))
    head, groups = digits[:-3], [digits[-3:]]
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join(groups)


def months(n: float) -> str:
    return f"{n:g} months"


def pct(ratio: float) -> str:
    return f"{ratio:.0%}"


@dataclass(frozen=True)
class Threshold:
    """Numeric criterion: profile.<profile_field> must be at least (or at most)
    product.<criterion>.

    A passing threshold also reports headroom (0-1): how far past the bar the
    SME is, relative to the bar. The engine averages headroom into the fit score.
    """

    rule: str
    profile_field: str
    criterion: str
    at_least: bool
    label: str
    fmt: Callable[[Any], str] = str
    # Optional override for the bar, e.g. a stricter vintage for one constitution.
    requirement: Callable[[MatchInput, LenderProduct], Any] | None = None
    # Product flag that, when explicitly False, makes a miss a soft "warn" instead of a "fail".
    soft_flag: str | None = None

    def __call__(self, profile: MatchInput, product: LenderProduct) -> CheckResult | None:
        required = self.requirement(profile, product) if self.requirement else getattr(product, self.criterion)
        if required is None:
            return None

        bound = "at least" if self.at_least else "at most"
        actual = getattr(profile, self.profile_field)
        if actual is None:
            return CheckResult(
                rule=self.rule,
                outcome="missing",
                required=required,
                message=f"{self.label}: not available yet; this lender needs {bound} {self.fmt(required)}",
            )

        gap = actual - required if self.at_least else required - actual
        if gap < 0:
            soft = self.soft_flag is not None and getattr(product, self.soft_flag) is False
            return CheckResult(
                rule=self.rule,
                outcome="warn" if soft else "fail",
                required=required,
                actual=actual,
                headroom=0.0 if soft else None,
                message=f"{self.label}: needs {bound} {self.fmt(required)}, you have {self.fmt(actual)}"
                + ("; not a hard cutoff, so the lender may still consider you" if soft else ""),
            )

        limit = "minimum" if self.at_least else "limit"
        return CheckResult(
            rule=self.rule,
            outcome="pass",
            required=required,
            actual=actual,
            headroom=min(gap / required, 1.0) if required else 1.0,
            message=f"{self.label}: {self.fmt(actual)} meets the {limit} of {self.fmt(required)}",
        )


def ticket_size(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
    if product.ticket_size is None:
        return None
    lo, hi = product.ticket_size.min, product.ticket_size.max
    span = f"{inr(lo)} to {inr(hi)}"
    if lo <= profile.requested_amount <= hi:
        return CheckResult(
            rule="ticket_size",
            outcome="pass",
            required=[lo, hi],
            actual=profile.requested_amount,
            message=f"Loan amount: {inr(profile.requested_amount)} is within {span}",
        )
    return CheckResult(
        rule="ticket_size",
        outcome="fail",
        required=[lo, hi],
        actual=profile.requested_amount,
        message=f"Loan amount: this lender lends {span}, you asked for {inr(profile.requested_amount)}",
    )


def tenure(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
    # No tenure preference from the SME means any tenure is acceptable.
    if product.tenure_months is None or profile.requested_tenure_months is None:
        return None
    lo, hi = product.tenure_months.min, product.tenure_months.max
    wanted = profile.requested_tenure_months
    ok = lo <= wanted <= hi
    return CheckResult(
        rule="tenure",
        outcome="pass" if ok else "fail",
        required=[lo, hi],
        actual=wanted,
        message=(
            f"Tenure: {wanted} months is within {lo} to {hi} months"
            if ok
            else f"Tenure: this lender offers {lo} to {hi} months, you asked for {wanted}"
        ),
    )


def gst_registration(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
    if not product.gst_required:
        return None
    if profile.gst_registered is None:
        return CheckResult(
            rule="gst_registration",
            outcome="missing",
            required=True,
            message="GST registration: upload your GST certificate; this lender requires it",
        )
    return CheckResult(
        rule="gst_registration",
        outcome="pass" if profile.gst_registered else "fail",
        required=True,
        actual=profile.gst_registered,
        message=(
            "GST registration: verified"
            if profile.gst_registered
            else "GST registration: this lender only lends to GST-registered businesses"
        ),
    )


def constitution(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
    allowed = product.allowed_constitutions
    if allowed is None:
        return None
    if profile.constitution is None:
        return CheckResult(
            rule="constitution",
            outcome="missing",
            required=allowed,
            message="Business type: not available yet; add it to check this lender",
        )
    ok = profile.constitution in allowed
    return CheckResult(
        rule="constitution",
        outcome="pass" if ok else "fail",
        required=allowed,
        actual=profile.constitution,
        message=(
            f"Business type: {profile.constitution} is accepted"
            if ok
            else f"Business type: this lender accepts {', '.join(allowed)}; you are {profile.constitution}"
        ),
    )


def sector(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
    excluded = product.excluded_sectors
    if not excluded:
        return None
    if profile.sector is None:
        return CheckResult(
            rule="sector",
            outcome="missing",
            required=excluded,
            message="Sector: not available yet; add it to check this lender",
        )
    ok = profile.sector not in excluded
    return CheckResult(
        rule="sector",
        outcome="pass" if ok else "fail",
        required=excluded,
        actual=profile.sector,
        message=(
            f"Sector: {profile.sector} is accepted"
            if ok
            else f"Sector: this lender does not lend to {profile.sector}"
        ),
    )


def _flag_rule(rule: str, criterion: str, have_field: str, label: str, missing_hint: str):
    """A yes/no requirement: the lender requires a document or registration the SME may lack."""

    def check(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
        if not getattr(product, criterion):
            return None
        have = getattr(profile, have_field)
        if have is None:
            return CheckResult(rule=rule, outcome="missing", required=True, message=f"{label}: {missing_hint}")
        return CheckResult(
            rule=rule,
            outcome="pass" if have else "fail",
            required=True,
            actual=have,
            message=f"{label}: provided" if have else f"{label}: required by this lender",
        )

    check.__name__ = rule
    return check


itr = _flag_rule("itr", "itr_required", "has_itr", "ITR-V", "this lender requires it; upload your ITR-V")
udyam = _flag_rule("udyam", "udyam_required", "has_udyam", "Udyam registration", "this lender requires it; upload your Udyam certificate")


def eligible_sectors(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
    allowed = product.eligible_sectors
    if not allowed:
        return None
    if profile.sector is None:
        return CheckResult(rule="eligible_sectors", outcome="missing", required=allowed,
                           message="Sector: not available yet; add it to check this lender")
    ok = profile.sector in allowed
    return CheckResult(
        rule="eligible_sectors",
        outcome="pass" if ok else "fail",
        required=allowed,
        actual=profile.sector,
        message=f"Sector: {profile.sector} is covered" if ok else f"Sector: this product only covers {', '.join(allowed)}",
    )


def geography(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
    blocked = product.negative_geographies
    if not blocked or profile.state is None:
        return None
    ok = profile.state not in blocked
    return CheckResult(
        rule="geography",
        outcome="pass" if ok else "fail",
        required=blocked,
        actual=profile.state,
        message=f"Location: {profile.state} is served" if ok else f"Location: this lender doesn't lend in {profile.state}",
    )


def collateral_free_limit(profile: MatchInput, product: LenderProduct) -> CheckResult | None:
    limit = product.collateral_free_limit
    if limit is None:
        return None
    ok = profile.requested_amount <= limit
    return CheckResult(
        rule="collateral_free_limit",
        outcome="pass" if ok else "warn",
        required=limit,
        actual=profile.requested_amount,
        headroom=None if ok else 0.0,
        message=f"Collateral: none needed up to {inr(limit)}"
        if ok
        else f"Collateral: above {inr(limit)} this lender asks for security; borrow {inr(limit)} or less to avoid it",
    )


def _vintage_requirement(profile: MatchInput, product: LenderProduct):
    """Lenders can set a different vintage per constitution; that wins over the general minimum."""
    for rule in product.min_business_vintage_by_constitution:
        if profile.constitution and rule.constitution == profile.constitution and rule.min_business_vintage_months is not None:
            return int(rule.min_business_vintage_months)
    return product.min_business_vintage_months


def years(n: float) -> str:
    return f"{n:g} years"


RULES: list[Rule] = [
    ticket_size,
    tenure,
    Threshold("business_vintage", "business_vintage_months", "min_business_vintage_months", True, "Business vintage", months,
              requirement=_vintage_requirement),
    Threshold("annual_turnover", "annual_turnover", "min_annual_turnover", True, "Annual turnover", inr),
    Threshold("bureau_score", "bureau_score", "min_bureau_score", True, "Bureau score", soft_flag="bureau_score_is_hard_cutoff"),
    Threshold("foir", "foir", "max_foir", False, "FOIR", pct),
    Threshold("bounces_6m", "bounces_6m", "max_bounces_6m", False, "Bounces in the last 6 months"),
    Threshold("bank_statement_months", "bank_statement_months", "min_bank_statement_months", True, "Bank statement", months),
    Threshold("min_age", "applicant_age_years", "min_age_years", True, "Applicant age", years),
    Threshold("max_age", "applicant_age_years", "max_age_years", False, "Applicant age", years),
    gst_registration,
    itr,
    udyam,
    constitution,
    sector,
    eligible_sectors,
    geography,
    collateral_free_limit,
]
