import json

from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_lenders_file_is_valid():
    response = client.get("/v1/lenders")

    assert response.status_code == 200
    assert len(response.json()) > 0


def test_match_returns_ranked_results():
    profile = json.loads((DATA_DIR / "sample_profiles" / "applicant_b.json").read_text(encoding="utf-8"))
    response = client.post("/v1/match", json=profile)

    assert response.status_code == 200
    statuses = [r["status"] for r in response.json()]
    assert statuses == sorted(statuses, key=lambda s: s != "matched")
    assert "not_yet" in statuses


def test_assess_then_match_then_offer():
    from app.samples import AS_OF, BUREAU_A, applicant_a

    body = {
        "sme_id": "SAMPLE-A",
        "documents": [d.model_dump(mode="json") for d in applicant_a()],
        "bureau": BUREAU_A.model_dump(mode="json"),
        "sector": "retail",
        "as_of": AS_OF.isoformat(),
    }
    assessed = client.post("/v1/assess", json=body)
    assert assessed.status_code == 200
    profile = assessed.json()["profile"]
    assert profile["readiness"]["band"] == "ready"

    matches = client.post("/v1/match/profile", json={"profile": profile, "request": {"sme_id": "SAMPLE-A", "amount": 500000, "tenure_months": 24}})
    assert matches.status_code == 200
    top = matches.json()[0]
    assert top["status"] == "matched"

    offer = client.get(f"/v1/offers/{top['product_id']}/explain", params={"amount": 500000, "tenure_months": 24})
    assert offer.status_code == 200


def test_sample_applicants_feed_assess():
    sample = client.get("/v1/samples/b").json()
    assert sample["sme_id"] == "SAMPLE-B" and len(sample["documents"]) == 6
    body = {k: sample[k] for k in ("sme_id", "documents", "bureau", "sector", "as_of")}
    profile = client.post("/v1/assess", json=body).json()["profile"]
    assert profile["readiness"]["band"] == "not_ready"
    assert client.get("/v1/samples/z").status_code == 422
