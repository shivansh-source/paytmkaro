"""Language models for the human-facing parts (understanding and explaining), never for decisions.

Only `StructuredLLM` is part of the contract; callers get one from `get_llm()` and must cope with None
(no key configured) and `LLMError` (provider down, bad output) by falling back to deterministic logic.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx

from app import config


class LLMError(Exception):
    """The model could not be reached or returned something unusable."""


class StructuredLLM(Protocol):
    def extract(self, *, system: str, user: str, schema: dict[str, Any], name: str) -> dict[str, Any]:
        """Return a JSON object matching `schema` (validate it anyway: never trust the shape)."""
        ...


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class SarvamLLM:
    """Sarvam chat completions with Structured Outputs (json_schema)."""

    def __init__(self, api_key: str, *, base_url: str, model: str, timeout: float):
        self.api_key, self.base_url, self.model, self.timeout = api_key, base_url.rstrip("/"), model, timeout

    def extract(self, *, system: str, user: str, schema: dict[str, Any], name: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": 400,
            "reasoning_effort": "low",
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
        }
        headers = {"api-subscription-key": self.api_key, "Authorization": f"Bearer {self.api_key}"}
        try:
            response = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"] or ""
            parsed = json.loads(_FENCE.sub("", content))
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
            raise LLMError(f"Sarvam request failed: {type(e).__name__}") from e
        if not isinstance(parsed, dict):
            raise LLMError("Sarvam returned non-object JSON")
        return parsed


def get_llm() -> StructuredLLM | None:
    if not config.SARVAM_API_KEY:
        return None
    return SarvamLLM(
        config.SARVAM_API_KEY,
        base_url=config.SARVAM_BASE_URL,
        model=config.SARVAM_CHAT_MODEL,
        timeout=config.SARVAM_TIMEOUT_SECONDS,
    )
