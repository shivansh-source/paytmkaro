"""Hard-filter rules, one per lender criterion.

A rule takes (profile, product) and returns a CheckResult, or None when the
lender does not set that criterion. To add a criterion: add the field to
LenderProduct (and the profile field it is compared with to SMEProfile), then
add one entry to RULES.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.recommendation.models import CheckResult, LenderProduct, SMEProfile

Rule = Callable[[SMEProfile, LenderProduct], CheckResult | None]


def inr(amount: float) -> str:
    """Format rupees with Indian digit grouping: 1500000 -> ₹15,00,000."""
    digits = str(int(round(amount)))
    head, groups = digits[:-3], [digits[-3:]]
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join(groups)


def months(n: int) -> str:
    return f"{n} months"


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

    def __call__(self, profile: SMEProfile, product: LenderProduct) -> CheckResult | None:
        required = getattr(product, self.criterion)
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
            return CheckResult(
                rule=self.rule,
                outcome="fail",
                required=required,
                actual=actual,
                message=f"{self.label}: needs {bound} {self.fmt(required)}, you have {self.fmt(actual)}",
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


def ticket_size(profile: SMEProfile, product: LenderProduct) -> CheckResult | None:
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


def tenure(profile: SMEProfile, product: LenderProduct) -> CheckResult | None:
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


def gst_registration(profile: SMEProfile, product: LenderProduct) -> CheckResult | None:
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


def constitution(profile: SMEProfile, product: LenderProduct) -> CheckResult | None:
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


def sector(profile: SMEProfile, product: LenderProduct) -> CheckResult | None:
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


RULES: list[Rule] = [
    ticket_size,
    tenure,
    Threshold("business_vintage", "business_vintage_months", "min_business_vintage_months", True, "Business vintage", months),
    Threshold("annual_turnover", "annual_turnover", "min_annual_turnover", True, "Annual turnover", inr),
    Threshold("bureau_score", "bureau_score", "min_bureau_score", True, "Bureau score"),
    Threshold("foir", "foir", "max_foir", False, "FOIR", pct),
    Threshold("bounces_6m", "bounces_6m", "max_bounces_6m", False, "Bounces in the last 6 months"),
    gst_registration,
    constitution,
    sector,
]
