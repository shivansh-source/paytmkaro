from fastapi.testclient import TestClient

from app.applications import get_store, seed_demo
from app.main import app
from app.samples import AS_OF, BUREAU_A, BUREAU_B
from tests.conftest import sign_in

client = TestClient(app)


def msme(mobile="9876500001", sample="a"):
    """A signed-in business with sample applicant A or B loaded into its stored file."""
    headers = sign_in(client, "msme", mobile)
    loaded = client.post(f"/v1/samples/{sample}/load", headers=headers)
    assert loaded.status_code == 200, loaded.text
    return headers, loaded.json()


def lender(name="Demo NBFC B", mobile="9876511111"):
    return sign_in(client, "lender", mobile, organisation=name)


def apply_body(sample="a", product_id="demo-nbfc-b-flexi", amount=500_000, consent=True, documents=()):
    return {
        "sme_id": "ignored: the server uses the signed-in account",
        "documents": list(documents),
        "bureau": (BUREAU_A if sample == "a" else BUREAU_B).model_dump(mode="json"),
        "sector": "retail",
        "as_of": AS_OF.isoformat(),
        "request": {"sme_id": "x", "amount": amount, "tenure_months": 24},
        "product_id": product_id,
        "consent_accepted": consent,
    }


def submit(headers, **kw):
    response = client.post("/v1/applications", json=apply_body(**kw), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def decide(headers, app_id, **body):
    return client.post(f"/v1/applications/{app_id}/decision", json=body, headers=headers)


def test_submit_verifies_server_side_and_lands_in_the_lender_inbox():
    headers, _ = msme()
    created = submit(headers)
    assert created["status"] == "submitted" and created["profile"]["sme_id"] == "SME-9876500001"
    assert created["profile"]["readiness"]["band"] == "ready"  # computed by the server
    assert "Demo NBFC B" in created["consent"]["text"]
    inbox = client.get("/v1/applications", headers=lender()).json()
    assert [a["id"] for a in inbox] == [created["id"]]
    assert inbox[0]["business_name"] == "SAMPLE KUMAR STORES"
    assert client.get("/v1/applications", headers=lender("Demo Bank A", "9876522222")).json() == []


def test_consent_and_a_stored_file_are_required():
    headers, _ = msme()
    assert client.post("/v1/applications", json=apply_body(consent=False), headers=headers).status_code == 422
    empty = sign_in(client, "msme", "9876500009")
    response = client.post("/v1/applications", json=apply_body(), headers=empty)
    assert response.status_code == 409 and "Upload your documents" in response.json()["detail"]


def test_applying_needs_a_business_session():
    assert client.post("/v1/applications", json=apply_body()).status_code == 401
    assert client.post("/v1/applications", json=apply_body(), headers=lender()).status_code == 403


def test_cannot_apply_where_not_eligible():
    headers, _ = msme(sample="b")
    response = client.post("/v1/applications", json=apply_body(sample="b", product_id="demo-bank-a-unsecured"), headers=headers)
    assert response.status_code == 409
    assert "Business vintage" in response.json()["detail"]


def test_red_flags_reach_the_lender():
    headers, _ = msme(sample="b")
    assert client.get("/v1/applications", headers=headers).json() == []
    created = submit(headers, sample="b")
    row = client.get("/v1/applications", headers=headers).json()[0]
    assert row["id"] == created["id"]
    assert row["red_flags"] == 2 and row["warnings"] == 1


def test_document_values_edited_in_the_browser_are_ignored_but_confirmations_count():
    headers, loaded = msme(sample="b")
    docs = loaded["documents"]
    bank = next(d for d in docs if d["document_type"] == "bank_statement")
    bank["data"]["account_holder_name"]["user_confirmed"] = True  # "RAVI KUMAAR" is me: allowed
    pan = next(d for d in docs if d["document_type"] == "pan_card")
    pan["data"]["name"]["value"] = "SOMEONE ELSE"  # tampering: ignored
    created = submit(headers, sample="b", documents=docs)
    names = {c["id"]: c["status"] for c in created["profile"]["cross_checks"]}
    assert names["cross.name_match"] == "pass"  # the confirmation was carried over
    stored_pan = next(d for d in created["documents"] if d["document_type"] == "pan_card")
    assert stored_pan["data"]["name"]["value"] != "SOMEONE ELSE"


def test_review_then_decline_needs_a_reason_and_explains_it():
    headers, _ = msme()
    nbfc = lender()
    app_id = submit(headers)["id"]
    assert decide(nbfc, app_id, action="start_review").json()["status"] == "in_review"
    assert decide(nbfc, app_id, action="decline").status_code == 400
    declined = decide(nbfc, app_id, action="decline", reason="cash_flow", note="Please reduce existing EMIs").json()
    assert declined["status"] == "declined"
    message = declined["decision"]["message_for_msme"]
    assert "EMIs or bounces" in message and "not yet" in message and "reduce existing EMIs." in message
    # The MSME sees it too.
    assert client.get("/v1/applications", headers=headers).json()[0]["decision_message"] == message


def test_request_info_needs_a_note_and_can_then_be_approved():
    headers, _ = msme()
    nbfc = lender()
    app_id = submit(headers)["id"]
    assert decide(nbfc, app_id, action="request_info").status_code == 400
    assert decide(nbfc, app_id, action="request_info", note="Latest GST return").json()["status"] == "info_requested"
    approved = decide(nbfc, app_id, action="approve_in_principle").json()
    assert approved["status"] == "approved_in_principle"
    assert [e["action"] for e in approved["history"]] == ["submitted", "request_info", "approve_in_principle"]
    assert decide(nbfc, app_id, action="decline", reason="policy").status_code == 409  # already decided


def test_nobody_else_can_see_or_decide_an_application():
    headers, _ = msme()
    app_id = submit(headers)["id"]
    other_business = sign_in(client, "msme", "9876500002")
    other_lender = lender("Demo Bank A", "9876522222")
    assert client.get(f"/v1/applications/{app_id}", headers=other_business).status_code == 404
    assert client.get(f"/v1/applications/{app_id}", headers=other_lender).status_code == 404
    assert decide(other_lender, app_id, action="approve_in_principle").status_code == 404
    assert decide(headers, app_id, action="approve_in_principle").status_code == 403  # a business can't decide
    assert client.get(f"/v1/applications/{app_id}", headers=headers).status_code == 200
    assert client.get(f"/v1/applications/{app_id}").status_code == 401


def test_unknown_application_and_product():
    headers, _ = msme()
    assert client.get("/v1/applications/APP-NOPE", headers=headers).status_code == 404
    assert client.post("/v1/applications", json=apply_body(product_id="nope"), headers=headers).status_code == 404


def test_demo_seed_fills_two_inboxes_once():
    store = get_store()
    seed_demo(store)
    seed_demo(store)  # idempotent
    assert store.count() == 3
    assert len(store.list(lender="Demo NBFC B")) == 2
    assert len(store.list(lender="Demo Bank A")) == 1


def test_seeded_applications_belong_to_seed_businesses_only():
    seed_demo(get_store())
    headers, _ = msme()
    assert client.get("/v1/applications", headers=headers).json() == []
    assert len(client.get("/v1/applications", headers=lender()).json()) == 2
