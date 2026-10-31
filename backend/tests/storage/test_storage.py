"""Accounts, sessions, progress and encryption at rest (SQLite + local files here; same code on Supabase)."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import get_db
from app.storage.crypto import SecretMissing, _fernet
from tests.conftest import sign_in

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def test_wrong_otp_and_unknown_institution_are_refused():
    body = {"role": "msme", "name": "A", "organisation": "B", "mobile": "9876500001", "otp": "000000"}
    assert client.post("/v1/auth/login", json=body).status_code == 401
    body |= {"role": "lender", "otp": "123456", "organisation": "Not A Real Bank"}
    assert client.post("/v1/auth/login", json=body).status_code == 400


def test_login_is_idempotent_per_role_and_mobile():
    a = sign_in(client)
    b = sign_in(client)
    me = client.get("/v1/auth/me", headers=a).json()
    assert me == client.get("/v1/auth/me", headers=b).json()
    assert me["id"] == "SME-9876500001" and me["role"] == "msme"


def test_logout_and_expiry_end_the_session():
    headers = sign_in(client)
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
    db = get_db()
    db.upsert_account(account_id="SME-9876500003", role="msme", mobile="9876500003", name="X", organisation="Y")
    db.create_session("SME-9876500003", "old-token", datetime.now(timezone.utc) - timedelta(minutes=1))
    assert client.get("/v1/auth/me", headers={"Authorization": "Bearer old-token"}).status_code == 401


def test_progress_round_trips_per_account():
    owner, other = sign_in(client), sign_in(client, "msme", "9876500002")
    assert client.get("/v1/progress", headers=owner).json() is None
    state = {"request": {"amount": 500000, "tenure_months": 24}, "questionnaire": "skipped"}
    assert client.put("/v1/progress", json=state, headers=owner).status_code == 204
    assert client.get("/v1/progress", headers=owner).json() == state
    assert client.get("/v1/progress", headers=other).json() is None


def test_personal_data_is_encrypted_at_rest(tmp_path):
    headers = sign_in(client)
    client.post("/v1/documents", files={"file": ("gst.pdf", (FIXTURES / "gst_reg06.pdf").read_bytes())}, headers=headers)
    client.put("/v1/progress", json={"name": "KUMAR TRADERS"}, headers=headers)
    with sqlite3.connect(tmp_path / "test.sqlite3") as raw:
        bodies = [r[0] for r in raw.execute("SELECT body FROM documents UNION ALL SELECT body FROM progress")]
        tokens = [r[0] for r in raw.execute("SELECT token_hash FROM sessions")]
    assert bodies and not any("KUMAR" in b or "27ABCDE1234F1Z0" in b for b in bodies)
    assert headers["Authorization"].split()[1] not in tokens  # only the hash is stored
    files = list((tmp_path / "uploads").rglob("*"))
    stored = [f for f in files if f.is_file()]
    assert stored and b"%PDF" not in stored[0].read_bytes()


def test_production_refuses_to_start_without_a_secret(monkeypatch):
    monkeypatch.setattr("app.config.CREDITSETU_ENV", "production")
    monkeypatch.setattr("app.config.CREDITSETU_SECRET", None)
    _fernet.cache_clear()
    try:
        with pytest.raises(SecretMissing):
            _fernet()
    finally:
        _fernet.cache_clear()
