"""POST /v1/documents through HTTP, then the envelopes straight into /v1/assess."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


@pytest.fixture(autouse=True)
def no_real_engines(monkeypatch):
    """The route never runs real PaddleOCR or calls Groq in tests."""
    monkeypatch.setattr("app.api.v1.documents.default_engines", lambda: (None, None))


def post(name: str, **form):
    files = {"file": (name, (FIXTURES / name).read_bytes())}
    response = client.post("/v1/documents", files=files, data={"sme_id": "T-API", **form})
    assert response.status_code == 200, response.text
    return response.json()


def test_uploaded_documents_feed_assess():
    envelopes = []
    for name, form in [("gst_reg06.pdf", {"document_type": "gst_registration"}),
                       ("bank_statement.pdf", {"document_type": "bank_statement"}),
                       ("e_aadhaar_encrypted.pdf", {"document_type": "aadhaar", "password": "KUMA1990"})]:
        envelopes += post(name, **form)["envelopes"]
    assert {d["document_type"] for d in envelopes} == {"gst_registration", "bank_statement", "aadhaar"}

    response = client.post("/v1/assess", json={"sme_id": "T-API", "documents": envelopes})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {d["status"] for d in body["documents"]} <= {"verified", "needs_review"}
    assert 0 <= body["profile"]["readiness"]["score"] <= 100


def test_out_of_range_uploaded_bureau_score_is_flagged_without_failing_assessment():
    envelope = {
        "document_id": "bureau-out-of-range",
        "sme_id": "T-API",
        "document_type": "bureau_report",
        "status": "needs_review",
        "uploaded_at": "2026-10-31T00:00:00Z",
        "file": {"file_name": "bureau_report.pdf", "mime_type": "application/pdf", "size_bytes": 1, "sha256": "a" * 64},
        "data": {
            "document_type": "bureau_report",
            "score": {"value": 942, "confidence": 0.9, "source": "parser"},
        },
    }

    response = client.post("/v1/assess", json={"sme_id": "T-API", "documents": [envelope]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile"]["bureau"] is None
    score_check = next(check for check in body["documents"][0]["checks"] if check["id"] == "bureau.score_range")
    assert score_check["status"] == "fail"


def test_password_and_unsupported_files_are_explained_not_errors():
    locked = post("e_aadhaar_encrypted.pdf")
    assert locked["status"] == "password_required" and "password" in locked["message"].lower()
    legacy = post("legacy_word.doc")
    assert legacy["status"] == "unsupported_format" and legacy["envelopes"] == []


def test_upload_needs_a_file_and_an_sme_id():
    assert client.post("/v1/documents", data={"sme_id": "T-API"}).status_code == 422
    files = {"file": ("x.pdf", b"%PDF-1.4")}
    assert client.post("/v1/documents", files=files).status_code == 422
    assert client.post("/v1/documents", files=files, data={"sme_id": "T", "document_type": "selfie"}).status_code == 422
