import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.offers import amortize, emi_for, estimate_offer, true_apr
from app.schemas import LenderProduct

client = TestClient(app)


def product(**overrides) -> LenderProduct:
    return LenderProduct.model_validate(
        {"id": "p", "lender": "L", "product": "P", "pricing": {"apr_range": [16, 20], "processing_fee_pct": 2}, **overrides}
    )


def test_textbook_emi():
    assert emi_for(500_000, 12, 24) == 23_537


def test_schedule_repays_exactly_the_principal():
    schedule = amortize(500_000, 18, 24)
    assert sum(i.principal for i in schedule) == pytest.approx(500_000, abs=0.05)
    assert schedule[-1].balance == 0


def test_apr_equals_rate_without_fees_and_rises_with_fees():
    emi = emi_for(500_000, 16, 24)
    assert true_apr(500_000, [emi] * 24) == pytest.approx(16, abs=0.01)
    assert true_apr(488_200, [emi] * 24) > 18  # 2% fee + GST on it


def test_estimate_has_best_and_worst_case():
    offer = estimate_offer(product(), 500_000, 24)
    best, worst = offer.scenarios
    assert best.emi < worst.emi
    assert best.processing_fee == 10_000 and best.gst_on_processing_fee == 1_800
    assert best.net_disbursed == 488_200
    assert best.apr_pct > best.interest_rate_pct_pa
    assert offer.rate_basis == "apr_proxy" and offer.notes


def test_published_interest_rate_is_used_when_available():
    offer = estimate_offer(product(pricing={"apr_range": [16, 20], "processing_fee_pct": 1,
                                            "interest_rate_range_pct_pa": {"min": 14, "max": 17}}), 500_000, 24)
    assert offer.rate_basis == "interest_rate"
    assert offer.scenarios[0].interest_rate_pct_pa == 14


def test_tenure_is_clamped_to_the_product():
    offer = estimate_offer(product(tenure_months={"min": 12, "max": 36}), 500_000, 60)
    assert offer.tenure_months == 36 and offer.tenure_adjusted


def test_offer_endpoint():
    response = client.get("/v1/offers/demo-bank-a-unsecured/explain", params={"amount": 500_000, "tenure_months": 24})
    assert response.status_code == 200
    assert len(response.json()["scenarios"][0]["schedule"]) == 24
    assert client.get("/v1/offers/nope/explain", params={"amount": 1}).status_code == 404
