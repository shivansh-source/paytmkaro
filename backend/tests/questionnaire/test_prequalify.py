from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.questionnaire import Answers, prequalify

client = TestClient(app)
AS_OF = date(2026, 10, 31)


def answers(**overrides) -> Answers:
    base = dict(
        sector="retail", constitution="proprietorship", started_year=2023, started_month=7, annual_sales="25l_1cr",
        loan_amount=500_000, tenure_months=24, existing_emi_monthly=40_000, bounces_6m="none",
        has_gst=True, has_udyam=True, has_itr=False, credit_score=760,
    )
    return Answers(**{**base, **overrides})


def test_estimates_are_conservative():
    est = prequalify(answers(), AS_OF).estimates
    assert est.business_vintage_months == 39
    assert est.annual_turnover == 2_500_000  # lower bound of the band
    assert est.foir == round(40_000 / (2_500_000 / 12), 3)
    assert est.bounces_6m == 0


def test_strong_answers_preview_matches():
    result = prequalify(answers(), AS_OF)
    assert {m.status for m in result.matches} == {"matched"}


def test_bounces_and_young_business_show_the_not_yet_path():
    result = prequalify(answers(started_year=2025, started_month=8, bounces_6m="3_plus", annual_sales="10l_25l"), AS_OF)
    bank_a = next(m for m in result.matches if m.lender == "Demo Bank A")
    assert bank_a.status == "not_yet"
    assert {"business_vintage", "bounces_6m"} <= {f.rule for f in bank_a.fixes}


def test_unknowns_stay_unknown_not_guessed():
    result = prequalify(answers(credit_score=None, bounces_6m="not_sure", constitution="not_sure"), AS_OF)
    bank_a = next(m for m in result.matches if m.lender == "Demo Bank A")
    assert any(c.outcome == "missing" and c.rule == "bureau_score" for c in bank_a.checks)
    assert result.estimates.bounces_6m is None
    assert len(result.notes) == 3


def test_checklist_is_personalised():
    no_gst = {c.document_type: c.status for c in prequalify(answers(has_gst=False, has_udyam=False, has_itr=True), AS_OF).checklist}
    assert no_gst["gst_registration"] == "not_needed" and no_gst["gstr3b"] == "not_needed"
    assert no_gst["udyam"] == "recommended" and no_gst["itr_v"] == "recommended"
    assert no_gst["pan_card"] == no_gst["bank_statement"] == "required"


def test_prequalify_endpoint():
    body = {"answers": answers().model_dump(mode="json"), "as_of": AS_OF.isoformat()}
    response = client.post("/v1/prequalify", json=body)
    assert response.status_code == 200
    assert len(response.json()["checklist"]) == 7
    bad = {**body, "answers": {**body["answers"], "credit_score": 1200}}
    assert client.post("/v1/prequalify", json=bad).status_code == 422
