import pytest


@pytest.fixture(autouse=True)
def no_real_engines(monkeypatch):
    """The upload route never runs real PaddleOCR or calls Groq in tests; tests that need OCR pass a FakeOcr."""
    monkeypatch.setattr("app.api.v1.documents.default_engines", lambda: (None, None))
