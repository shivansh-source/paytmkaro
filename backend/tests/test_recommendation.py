import json

import pytest

from app.config import DATA_DIR
from app.recommendation import LenderProduct, MatchInput, evaluate, load_lender_products, recommend
from app.recommendation.rules import inr


def load_profile(name: str) -> MatchInput:
    path = DATA_DIR / "sample_profiles" / f"{name}.json"
    return MatchInput.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def products() -> list[LenderProduct]:
    return load_lender_products()


def make_product(**overrides) -> LenderProduct:
    return LenderProduct.model_validate(
        {
            "id": "test-product",
            "lender": "Test Lender",
            "product": "Test loan",
            "pricing": {"apr_range": [18, 22], "processing_fee_pct": 2},
            **overrides,
        }
    )


def test_clean_applicant_matches_every_lender(products):
    by_fit = recommend(load_profile("applicant_a"), products, sort="fit")
    by_cost = recommend(load_profile("applicant_a"), products, sort="cost")

    assert [r.status for r in by_fit] == ["matched"] * len(products)
    fits = [r.fit_score for r in by_fit]
    assert fits == sorted(fits, reverse=True)
    aprs = [r.true_apr_pct for r in by_cost]
    assert aprs == sorted(aprs)
    # The two orders genuinely differ: the cheapest lender is the strictest one.
    assert by_cost[0].lender == "Demo Bank A" and by_fit[-1].lender == "Demo Bank A"


def test_messy_applicant_gets_specific_not_yet_reasons(products):
    results = recommend(load_profile("applicant_b"), products)
    bank_a = next(r for r in results if r.lender == "Demo Bank A")

    assert bank_a.status == "not_yet"
    assert bank_a.fit_score is None
    assert "Business vintage: needs at least 24 months, you have 14 months" in bank_a.reasons
    assert "Annual turnover: needs at least ₹15,00,000, you have ₹11,00,000" in bank_a.reasons
    # Matched products are ranked ahead of not-yet ones.
    assert results[-1] is bank_a


def test_missing_profile_data_blocks_instead_of_guessing():
    profile = MatchInput(sme_id="x", requested_amount=500000, bureau_score=None)
    result = evaluate(profile, make_product(min_bureau_score=700))

    assert result.status == "not_yet"
    [check] = result.checks
    assert (check.rule, check.outcome) == ("bureau_score", "missing")


def test_unset_criteria_are_skipped():
    profile = MatchInput(sme_id="x", requested_amount=500000)
    result = evaluate(profile, make_product())

    assert result.checks == []
    assert (result.status, result.fit_score) == ("matched", 100.0)


def test_fit_score_reflects_headroom():
    product = make_product(min_business_vintage_months=12, max_foir=0.5)
    barely = evaluate(MatchInput(sme_id="x", requested_amount=1, business_vintage_months=12, foir=0.5), product)
    comfortably = evaluate(MatchInput(sme_id="x", requested_amount=1, business_vintage_months=24, foir=0.0), product)

    assert barely.fit_score == 0.0
    assert comfortably.fit_score == 100.0


def test_ties_on_fit_rank_by_cheapest_apr():
    profile = MatchInput(sme_id="x", requested_amount=500000)
    cheap = make_product(id="cheap", pricing={"apr_range": [14, 18], "processing_fee_pct": 1})
    pricey = make_product(id="pricey", pricing={"apr_range": [24, 30], "processing_fee_pct": 1})

    assert [r.product_id for r in recommend(profile, [pricey, cheap])] == ["cheap", "pricey"]


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(999, "₹999"), (1000, "₹1,000"), (100000, "₹1,00,000"), (1500000, "₹15,00,000"), (123456789, "₹12,34,56,789")],
)
def test_inr_uses_indian_grouping(amount, expected):
    assert inr(amount) == expected
