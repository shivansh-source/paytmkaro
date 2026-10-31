import pytest

from app.applications import get_store


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Tests never call Sarvam, even when backend/.env has a key: the free-text tests inject a fake model."""
    monkeypatch.setattr("app.config.SARVAM_API_KEY", None)


@pytest.fixture(autouse=True)
def isolated_application_store(tmp_path, monkeypatch):
    """Every test gets its own empty applications database (no demo seed unless a test asks)."""
    monkeypatch.setenv("CREDITSETU_DB", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("CREDITSETU_SEED", "0")
    get_store.cache_clear()
    yield
    get_store.cache_clear()
