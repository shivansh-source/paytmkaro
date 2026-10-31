"""Hosted VLM clients (Groq). The VLM is a fallback reader; code validates everything it returns."""

from __future__ import annotations

import threading

from app import config
from app.documents.ports import VlmClient
from app.documents.vlm.budget import VlmBudget
from app.documents.vlm.groq import GroqVlmClient
from app.documents.vlm.pool import GroqWorkerPool

_lock = threading.Lock()
_pool: GroqWorkerPool | None = None
_pool_keys: tuple[str, ...] = ()


def get_default_vlm() -> VlmClient | None:
    """The shared worker pool (one worker per configured Groq key), or None so the pipeline runs text/OCR only.

    One process-wide pool, so every upload sees the same worker busy/cooling state."""
    global _pool, _pool_keys
    keys = tuple(config.GROQ_API_KEYS) or ((config.GROQ_API_KEY,) if config.GROQ_API_KEY else ())
    if not keys:
        return None
    with _lock:
        if _pool is None or keys != _pool_keys:
            _pool = GroqWorkerPool.from_keys(keys)
            _pool_keys = keys
        return _pool


__all__ = ["GroqVlmClient", "GroqWorkerPool", "VlmBudget", "get_default_vlm"]
