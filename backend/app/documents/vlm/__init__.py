"""Hosted VLM clients (Groq). The VLM is a fallback reader; code validates everything it returns."""

from __future__ import annotations

from app import config
from app.documents.vlm.budget import VlmBudget
from app.documents.vlm.groq import GroqVlmClient


def get_default_vlm() -> GroqVlmClient | None:
    """A Groq client when GROQ_API_KEY is set, else None so the pipeline runs text/OCR only."""
    if not config.GROQ_API_KEY:
        return None
    return GroqVlmClient()


__all__ = ["GroqVlmClient", "VlmBudget", "get_default_vlm"]
