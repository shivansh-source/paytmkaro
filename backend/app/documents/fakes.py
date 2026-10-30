"""In-memory OcrEngine / VlmClient for tests and offline demos. No network, no models."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from app.documents.models import OcrLine
from app.documents.ports import VlmError


class FakeOcr:
    """Returns the same lines for every image, or lines chosen by a function of the image bytes."""

    def __init__(self, lines: list[OcrLine] | Callable[[bytes], list[OcrLine]] | None = None):
        self._lines = lines or []
        self.calls = 0

    def recognize(self, image_png: bytes) -> list[OcrLine]:
        self.calls += 1
        return self._lines(image_png) if callable(self._lines) else list(self._lines)


class FakeVlm:
    """Replays canned JSON replies in order and records every call (prompt, image count)."""

    def __init__(self, replies: Sequence[dict[str, Any] | Exception] = ()):
        self._replies = list(replies)
        self.calls: list[tuple[str, int]] = []

    def complete_json(self, prompt: str, images: Sequence[bytes] = (), *, max_tokens: int = 2048) -> dict[str, Any]:
        self.calls.append((prompt, len(images)))
        if not self._replies:
            raise VlmError("FakeVlm: no reply queued")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
