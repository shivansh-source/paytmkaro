"""Offer math for the Key Fact Statement: EMI, schedule, fees, total payback and true APR.

All deterministic. True APR is the annualised internal rate of return of what the borrower actually
receives (loan minus upfront fees) against what they repay, so fees show up in the rate. Lenders quote
ranges, so every offer is computed at both ends: best case and worst case.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import Schema
from app.schemas.lender import LenderProduct

GST_ON_FEES = 0.18  # GST on processing fees
COOLING_OFF = (
    "After the loan is disbursed you get a cooling-off (look-up) period to exit by repaying the principal "
    "and the proportionate APR, with no penalty. The lender's KFS states how many days."
)
DEFAULT_TENURE_MONTHS = 12


class Installment(Schema):
    month: int = Field(ge=1)
    emi: float
    principal: float
    interest: float
    balance: float  # outstanding after this payment


class OfferScenario(Schema):
    label: Literal["best_case", "worst_case"]
    interest_rate_pct_pa: float
    emi: float
    total_interest: float
    processing_fee: float
    gst_on_processing_fee: float
    net_disbursed: float  # what reaches the bank account
    total_amount_payable: float  # sum of all EMIs
    total_cost_of_credit: float  # interest + fees + GST on fees
    apr_pct: float  # true annual cost, fees included
    schedule: list[Installment]


class OfferEstimate(Schema):
    product_id: str
    lender: str
    product: str
    amount: int
    tenure_months: int
    tenure_adjusted: bool  # requested tenure was outside the product's range and was clamped
    within_ticket_size: bool
    rate_basis: Literal["interest_rate", "apr_proxy"]
    indicative_only: bool
    scenarios: list[OfferScenario]
    cooling_off: str = COOLING_OFF
    notes: list[str] = []


def emi_for(principal: float, annual_rate_pct: float, months: int) -> float:
    r = annual_rate_pct / 1200
    if r == 0:
        return round(principal / months, 2)
    factor = (1 + r) ** months
    return round(principal * r * factor / (factor - 1))


def amortize(principal: float, annual_rate_pct: float, months: int) -> list[Installment]:
    r = annual_rate_pct / 1200
    emi = emi_for(principal, annual_rate_pct, months)
    balance = principal
    rows: list[Installment] = []
    for m in range(1, months + 1):
        interest = round(balance * r, 2)
        principal_part = round(emi - interest, 2) if m < months else round(balance, 2)  # last EMI clears the rest
        balance = round(balance - principal_part, 2)
        rows.append(Installment(month=m, emi=round(principal_part + interest, 2), principal=principal_part,
                                interest=interest, balance=max(balance, 0.0)))
    return rows


def true_apr(net_disbursed: float, payments: list[float]) -> float:
    """Annualised IRR (monthly rate x 12), in percent. Bisection: robust and plenty fast here."""

    def npv(rate: float) -> float:
        return sum(p / (1 + rate) ** k for k, p in enumerate(payments, start=1)) - net_disbursed

    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if npv(mid) > 0 else (lo, mid)
    return round((lo + hi) / 2 * 1200, 2)


def scenario(label, amount: int, rate: float, tenure: int, fee_pct: float) -> OfferScenario:
    schedule = amortize(amount, rate, tenure)
    fee = round(amount * fee_pct / 100, 2)
    gst = round(fee * GST_ON_FEES, 2)
    net = round(amount - fee - gst, 2)
    payable = round(sum(i.emi for i in schedule), 2)
    interest = round(sum(i.interest for i in schedule), 2)
    return OfferScenario(
        label=label,
        interest_rate_pct_pa=rate,
        emi=schedule[0].emi,
        total_interest=interest,
        processing_fee=fee,
        gst_on_processing_fee=gst,
        net_disbursed=net,
        total_amount_payable=payable,
        total_cost_of_credit=round(interest + fee + gst, 2),
        apr_pct=true_apr(net, [i.emi for i in schedule]),
        schedule=schedule,
    )


def estimate_offer(product: LenderProduct, amount: int, tenure_months: int | None = None) -> OfferEstimate:
    notes: list[str] = []
    pricing = product.pricing

    tenure = tenure_months or (product.tenure_months.max if product.tenure_months else DEFAULT_TENURE_MONTHS)
    adjusted = False
    if product.tenure_months and not product.tenure_months.min <= tenure <= product.tenure_months.max:
        clamped = min(max(tenure, product.tenure_months.min), product.tenure_months.max)
        notes.append(f"Tenure changed from {tenure} to {clamped} months to fit this product")
        tenure, adjusted = clamped, True

    within = product.ticket_size is None or product.ticket_size.min <= amount <= product.ticket_size.max
    if not within:
        notes.append("Amount is outside this product's loan range; figures are for comparison only")

    rates = pricing.interest_rate_range_pct_pa
    if rates is not None and rates.min is not None and rates.max is not None:
        low, high, basis = rates.min, rates.max, "interest_rate"
    else:
        low, high, basis = pricing.apr_range[0], pricing.apr_range[1], "apr_proxy"
        notes.append("The lender publishes only an APR range, so the EMI uses it as the interest rate: a conservative estimate")

    scenarios = [scenario("best_case", amount, low, tenure, pricing.processing_fee_pct)]
    if high != low:
        scenarios.append(scenario("worst_case", amount, high, tenure, pricing.processing_fee_pct))

    return OfferEstimate(
        product_id=product.id,
        lender=product.lender,
        product=product.product,
        amount=amount,
        tenure_months=tenure,
        tenure_adjusted=adjusted,
        within_ticket_size=within,
        rate_basis=basis,
        indicative_only=pricing.indicative_only,
        scenarios=scenarios,
        notes=notes,
    )
