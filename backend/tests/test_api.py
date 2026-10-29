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
