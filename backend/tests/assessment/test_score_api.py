import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def score(applicant: str) -> dict:
    body = client.get(f"/v1/samples/{applicant}").json()
    response = client.post("/v1/score", json=body)
    assert response.status_code == 200
    return response.json()


def test_sample_applicants_score_through_the_api():
    a, b = score("a"), score("b")

    assert a["index"] > b["index"]
    assert (a["grade"], b["grade"]) == ("strong", "cautious")
    assert b["grade_capped_by"]  # the failed balance-math check caps B
    assert a["provisional"] and b["provisional"]  # mock bureau score
    assert 0 < a["coverage"]["coverage_pct"] < 100
    assert "not a credit decision" in a["disclaimer"].lower()
    # Every registry parameter is present, computed or pending with a reason.
    assert all(p["status"] == "computed" or p["reason"] for p in a["parameters"])


def test_score_response_carries_no_personal_identifiers():
    text = json.dumps(score("a"))
    for secret in ("ABCPK1234F", "KUMAR", "Karnataka"):
        assert secret.lower() not in text.lower()


def test_score_rejects_a_malformed_body():
    assert client.post("/v1/score", json={"sme_id": "x"}).status_code == 422
