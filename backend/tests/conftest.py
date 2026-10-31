import pytest
from fastapi.testclient import TestClient

from app.applications import get_store
from app.storage import get_db


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Tests never call Sarvam, even when backend/.env has a key: the free-text tests inject a fake model."""
    monkeypatch.setattr("app.config.SARVAM_API_KEY", None)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite database and uploads folder, never Supabase (even when
    backend/.env points at it), and no demo seed unless a test asks."""
    for name in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        monkeypatch.setattr(f"app.config.{name}", None)
    monkeypatch.setenv("CREDITSETU_DB", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("CREDITSETU_UPLOADS", str(tmp_path / "uploads"))
    monkeypatch.setenv("CREDITSETU_SEED", "0")
    get_store.cache_clear()
    get_db.cache_clear()
    yield
    get_store.cache_clear()
    get_db.cache_clear()


def sign_in(client: TestClient, role: str = "msme", mobile: str = "9876500001", organisation: str = "Kumar Stores") -> dict:
    """Log in through the API and return the Authorization header for later calls."""
    response = client.post("/v1/auth/login", json={"role": role, "name": "Test User", "organisation": organisation,
                                                     "mobile": mobile, "otp": "123456"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}
