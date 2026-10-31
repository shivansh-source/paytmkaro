"""POST /v1/documents through HTTP, then the envelopes straight into /v1/assess."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def post(name: str, **form):
    files = {"file": (name, (FIXTURES / name).read_bytes())}
    response = client.post("/v1/documents", files=files, data={"sme_id": "T-API", **form})
    assert response.status_code == 200, response.text
    return response.json()


def test_uploaded_documents_feed_assess():
    documents = []
    for name, form in [("gst_reg06.pdf", {"document_type": "gst_registration"}),
                       ("bank_statement.pdf", {"document_type": "bank_statement"}),
                       ("e_aadhaar_encrypted.pdf", {"document_type": "aadhaar", "password": "KUMA1990"})]:
        documents += post(name, **form)["documents"]
    assert {d["document_type"] for d in documents} == {"gst_registration", "bank_statement", "aadhaar"}

    response = client.post("/v1/assess", json={"sme_id": "T-API", "documents": documents})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {d["status"] for d in body["documents"]} <= {"verified", "needs_review"}
    assert 0 <= body["profile"]["readiness"]["score"] <= 100


def test_password_and_unsupported_files_are_explained_not_errors():
    locked = post("e_aadhaar_encrypted.pdf")
    assert locked["status"] == "password_required" and "password" in locked["message"].lower()
    legacy = post("legacy_word.doc")
    assert legacy["status"] == "unsupported_format" and legacy["documents"] == []


def test_upload_needs_a_file_and_an_sme_id():
    assert client.post("/v1/documents", data={"sme_id": "T-API"}).status_code == 422
    files = {"file": ("x.pdf", b"%PDF-1.4")}
    assert client.post("/v1/documents", files=files).status_code == 422
    assert client.post("/v1/documents", files=files, data={"sme_id": "T", "document_type": "selfie"}).status_code == 422
