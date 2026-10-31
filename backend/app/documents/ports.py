"""Interfaces for the two external engines, so stages can be tested with fakes.

OCR runs locally (PaddleOCR). The VLM is hosted (Groq, Qwen vision) and is a
fallback: it reads, code validates and decides. Images handed to a VlmClient
must already be Aadhaar-redacted (see app.documents.privacy).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.documents.models import OcrLine


class OcrEngine(Protocol):
    def recognize(self, image_png: bytes) -> list[OcrLine]: ...


class VlmError(Exception):
    """Any VLM failure: network, HTTP error, non-JSON reply."""


class VlmBudgetExceeded(VlmError):
    """Rate limit (429) after retries, or the per-document request budget is spent."""

    def __init__(self, message: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after  # seconds the provider asked us to wait, when it said


class VlmClient(Protocol):
    def complete_json(self, prompt: str, images: Sequence[bytes] = (), *, max_tokens: int = 2048) -> dict[str, Any]:
        """Return the model's reply parsed as a JSON object. `images` are PNG bytes and may be
        empty (text-only input for XLSX/CSV/DOCX). Raises VlmError / VlmBudgetExceeded."""
        ...
