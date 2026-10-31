"""POST /v1/documents through HTTP, then the envelopes straight into /v1/assess."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import sign_in

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


@pytest.fixture(autouse=True)
def no_real_engines(monkeypatch):
    """The route never runs real PaddleOCR or calls Groq in tests."""
    monkeypatch.setattr("app.api.v1.documents.default_engines", lambda: (None, None))


def post(name: str, headers: dict | None = None, **form):
    files = {"file": (name, (FIXTURES / name).read_bytes())}
    response = client.post("/v1/documents", files=files, data=form, headers=headers or sign_in(client))
    assert response.status_code == 200, response.text
    return response.json()


def test_uploaded_documents_feed_assess_and_are_stored():
    headers = sign_in(client)
    envelopes = []
    for name, form in [("gst_reg06.pdf", {"document_type": "gst_registration"}),
                       ("bank_statement.pdf", {"document_type": "bank_statement"}),
                       ("e_aadhaar_encrypted.pdf", {"document_type": "aadhaar", "password": "KUMA1990"})]:
        envelopes += post(name, headers, **form)["envelopes"]
    assert {d["document_type"] for d in envelopes} == {"gst_registration", "bank_statement", "aadhaar"}

    stored = client.get("/v1/documents", headers=headers).json()
    assert {d["document_id"] for d in stored} == {d["document_id"] for d in envelopes}
    assert all(d["sme_id"] == "SME-9876500001" for d in stored)

    response = client.post("/v1/assess", json={"sme_id": "SME-9876500001", "documents": envelopes})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {d["status"] for d in body["documents"]} <= {"verified", "needs_review"}
    assert 0 <= body["profile"]["readiness"]["score"] <= 100


def test_password_and_unsupported_files_are_explained_not_errors():
    locked = post("e_aadhaar_encrypted.pdf")
    assert locked["status"] == "password_required" and "password" in locked["message"].lower()
    legacy = post("legacy_word.doc")
    assert legacy["status"] == "unsupported_format" and legacy["envelopes"] == []


def test_upload_needs_a_business_session_and_a_file():
    files = {"file": ("x.pdf", b"%PDF-1.4")}
    assert client.post("/v1/documents", files=files).status_code == 401
    headers = sign_in(client)
    assert client.post("/v1/documents", headers=headers).status_code == 422
    assert client.post("/v1/documents", files=files, data={"document_type": "selfie"}, headers=headers).status_code == 422
    lender = sign_in(client, "lender", "9876511111", organisation="Demo NBFC B")
    assert client.post("/v1/documents", files=files, headers=lender).status_code == 403


def test_documents_are_private_and_can_be_cleared():
    owner = sign_in(client)
    post("gst_reg06.pdf", owner)
    other = sign_in(client, "msme", "9876500002")
    assert client.get("/v1/documents", headers=other).json() == []
    assert len(client.get("/v1/documents", headers=owner).json()) == 1
    assert client.delete("/v1/documents", headers=owner).status_code == 204
    assert client.get("/v1/documents", headers=owner).json() == []


def test_a_new_upload_replaces_the_same_document_type():
    headers = sign_in(client)
    post("gst_reg06.pdf", headers)
    post("mixed_bundle.pdf", headers)  # another GST certificate (different file)
    stored = client.get("/v1/documents", headers=headers).json()
    assert [d["document_type"] for d in stored].count("gst_registration") == 1
