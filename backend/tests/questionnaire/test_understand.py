"""Free-text questionnaire answers. A fake model replays realistic (and deliberately bad) outputs, so these
tests never call Sarvam."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.llm import LLMError
from app.main import app
from app.questionnaire.understand import InterpretRequest, amounts_in, interpret, mask_private, parse_amount

TODAY = date(2026, 10, 31)
client = TestClient(app)

NULLS = dict(
    sector=None, constitution=None, started_year=None, years_in_business=None, sales_amount=None, sales_period=None,
    loan_amount=None, tenure_months=None, tenure_years=None, purpose=None, emi_amounts=None, bounces_6m_count=None,
    has_gst=None, has_udyam=None, has_itr=None, credit_score=None,
)


class FakeLLM:
    def __init__(self, **fields):
        self.out = {**NULLS, **fields}
        self.seen: list[str] = []

    def extract(self, *, system, user, schema, name):
        self.seen.append(user)
        return self.out


class DownLLM:
    def extract(self, **_):
        raise LLMError("down")


def ask(step, text, llm=None):
    return interpret(InterpretRequest(step=step, text=text, today=TODAY), llm, use_default_llm=False)


@pytest.mark.parametrize(
    ("text", "amount"),
    [("5 lakh", 500_000), ("₹5,00,000", 500_000), ("50k", 50_000), ("1.5 cr", 15_000_000), ("Rs 75000", 75_000), ("५ लाख", 500_000)],
)
def test_amounts(text, amount):
    assert parse_amount(text) == amount


def test_short_answers_need_no_model():
    llm = FakeLLM(sector="food")
    assert ask("loan_amount", "5 lakh", llm).updates == {"loan_amount": 500_000}
    assert ask("emi", "koi loan nahi", llm).updates == {"existing_emi_monthly": 0}
    assert ask("bounces", "3", llm).updates == {"bounces_6m": "3_plus"}
    assert ask("started", "2022", llm).updates == {"started_year": 2022}
    assert ask("score", "742", llm).updates == {"credit_score": 742}
    assert ask("sector", "kirana dukaan", llm).updates == {"sector": "retail"}
    assert llm.seen == []  # all handled by rules


def test_long_answer_fills_several_questions_and_code_does_the_math():
    llm = FakeLLM(sector="retail", years_in_business=3, loan_amount=500_000, purpose="buy stock")
    r = ask("sector", "main kirana dukaan chalata hoon, teen saal se, 5 lakh chahiye stock ke liye", llm)
    assert r.source == "ai" and r.answered_step
    assert r.updates == {"sector": "retail", "started_year": 2023, "loan_amount": 500_000, "purpose": "Buy stock"}


def test_emis_are_summed_in_code_and_grounded_in_the_text():
    ok = ask("emi", "bike loan 4500 mahina aur business loan 20k", FakeLLM(emi_amounts=[4500, 20000]))
    assert ok.updates == {"existing_emi_monthly": 24_500}
    slip = ask("emi", "bike loan 4500 mahina aur business loan 20k", FakeLLM(emi_amounts=[4500, 2000]))
    assert "existing_emi_monthly" not in slip.updates  # 2000 isn't in the text: dropped, question asked again


def test_monthly_sales_become_yearly_in_code():
    r = ask("annual_sales", "महीने में करीब 2 लाख की बिक्री", FakeLLM(sales_amount=200_000, sales_period="month"))
    assert r.updates == {"annual_sales": "10l_25l"}


def test_defaults_for_unmentioned_topics_are_dropped():
    llm = FakeLLM(bounces_6m_count=2, emi_amounts=[])  # model invents "no loans" from a bounce sentence
    assert ask("bounces", "do baar EMI bounce hui thi", llm).updates == {"bounces_6m": "1_2"}
    llm = FakeLLM(sector="retail", bounces_6m_count=0, has_gst=False)  # never mentioned
    assert ask("sector", "I run a general store near the market", llm).updates == {"sector": "retail"}


def test_out_of_range_model_values_are_dropped():
    r = ask("have", "CIBIL 1200 hai, GST hai", FakeLLM(credit_score=1200, has_gst=True))
    assert r.updates == {"has_gst": True}


def test_private_numbers_never_reach_the_model():
    llm = FakeLLM(sector="services")
    ask("sector", "my PAN is ABCPK1234F, phone 9876543210, I run a salon", llm)
    assert "ABCPK1234F" not in llm.seen[0] and "9876543210" not in llm.seen[0]
    assert mask_private("₹5,00,000") == "₹5,00,000"  # money with commas is kept


def test_model_down_or_no_key_falls_back_politely():
    for llm in (DownLLM(), None):
        r = ask("have", "GST hai par Udyam nahi", llm)
        assert r.updates == {} and r.source == "none" and "tap an option" in r.message


def test_extra_answer_for_another_question_keeps_current_question_open():
    r = ask("tenure", "GST hai", FakeLLM(has_gst=True))
    assert r.updates == {"has_gst": True} and not r.answered_step
    assert "repay" in r.message


def test_grounding_set():
    assert amounts_in("4500 mahina aur 20k") == {4500, 20000}


def test_interpret_endpoint_without_key(monkeypatch):
    monkeypatch.setattr("app.questionnaire.understand.get_llm", lambda: None)
    body = {"step": "loan_amount", "text": "10 lakh", "today": TODAY.isoformat()}
    assert client.post("/v1/questionnaire/interpret", json=body).json()["updates"] == {"loan_amount": 1_000_000}
