import pytest
from fastapi.testclient import TestClient

from app.applications import get_store, seed_demo
from app.main import app
from app.samples import AS_OF, BUREAU_A, BUREAU_B, applicant_a, applicant_b

client = TestClient(app)


def apply_body(sample="a", product_id="demo-nbfc-b-flexi", amount=500_000, consent=True):
    docs, bureau, sme = (applicant_a(), BUREAU_A, "SAMPLE-A") if sample == "a" else (applicant_b(), BUREAU_B, "SAMPLE-B")
    return {
        "sme_id": sme,
        "documents": [d.model_dump(mode="json") for d in docs],
        "bureau": bureau.model_dump(mode="json"),
        "sector": "retail",
        "as_of": AS_OF.isoformat(),
        "request": {"sme_id": sme, "amount": amount, "tenure_months": 24},
        "product_id": product_id,
        "consent_accepted": consent,
    }


def submit(**kw):
    response = client.post("/v1/applications", json=apply_body(**kw))
    assert response.status_code == 201, response.text
    return response.json()


def decide(app_id, **body):
    return client.post(f"/v1/applications/{app_id}/decision", json=body)


def test_submit_verifies_server_side_and_lands_in_the_lender_inbox():
    created = submit()
    assert created["status"] == "submitted"
    assert created["profile"]["readiness"]["band"] == "ready"  # computed by the server
    assert "Demo NBFC B" in created["consent"]["text"]
    inbox = client.get("/v1/applications", params={"lender": "Demo NBFC B"}).json()
    assert [a["id"] for a in inbox] == [created["id"]]
    assert inbox[0]["business_name"] == "SAMPLE KUMAR STORES"
    assert client.get("/v1/applications", params={"lender": "Demo Bank A"}).json() == []


def test_consent_is_required():
    assert client.post("/v1/applications", json=apply_body(consent=False)).status_code == 422


def test_cannot_apply_where_not_eligible():
    response = client.post("/v1/applications", json=apply_body(sample="b", product_id="demo-bank-a-unsecured"))
    assert response.status_code == 409
    assert "Business vintage" in response.json()["detail"]


def test_red_flags_reach_the_lender():
    summary = client.get(f"/v1/applications?sme_id=SAMPLE-B").json() or None
    assert summary is None or summary == []
    created = submit(sample="b")
    row = client.get("/v1/applications", params={"sme_id": "SAMPLE-B"}).json()[0]
    assert row["id"] == created["id"]
    assert row["red_flags"] == 2 and row["warnings"] == 1


def test_review_then_decline_needs_a_reason_and_explains_it():
    app_id = submit()["id"]
    assert decide(app_id, action="start_review").json()["status"] == "in_review"
    assert decide(app_id, action="decline").status_code == 400
    declined = decide(app_id, action="decline", reason="cash_flow", note="Please reduce existing EMIs").json()
    assert declined["status"] == "declined"
    message = declined["decision"]["message_for_msme"]
    assert "EMIs or bounces" in message and "not yet" in message and "reduce existing EMIs." in message
    # The MSME sees it too.
    assert client.get("/v1/applications", params={"sme_id": "SAMPLE-A"}).json()[0]["decision_message"] == message


def test_request_info_needs_a_note_and_can_then_be_approved():
    app_id = submit()["id"]
    assert decide(app_id, action="request_info").status_code == 400
    assert decide(app_id, action="request_info", note="Latest GST return").json()["status"] == "info_requested"
    approved = decide(app_id, action="approve_in_principle").json()
    assert approved["status"] == "approved_in_principle"
    assert [e["action"] for e in approved["history"]] == ["submitted", "request_info", "approve_in_principle"]
    assert decide(app_id, action="decline", reason="policy").status_code == 409  # already decided


def test_unknown_application_and_product():
    assert client.get("/v1/applications/APP-NOPE").status_code == 404
    assert client.post("/v1/applications", json=apply_body(product_id="nope")).status_code == 404


def test_demo_seed_fills_two_inboxes_once():
    store = get_store()
    seed_demo(store)
    seed_demo(store)  # idempotent
    assert store.count() == 3
    assert len(store.list(lender="Demo NBFC B")) == 2
    assert len(store.list(lender="Demo Bank A")) == 1


def test_seeded_applications_do_not_belong_to_the_live_sample_applicants():
    seed_demo(get_store())
    assert client.get("/v1/applications", params={"sme_id": "SAMPLE-A"}).json() == []
    assert len(client.get("/v1/applications", params={"lender": "Demo NBFC B"}).json()) == 2
