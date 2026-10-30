"""Groq's OpenAI-compatible chat completions API with a Qwen vision model, over httpx.

JSON mode (`response_format: json_object`) plus pydantic validation downstream;
structured json_schema output is not relied on with images. Images are
downscaled and re-encoded as JPEG before upload.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
from PIL import Image

from app import config
from app.documents.ports import VlmBudgetExceeded, VlmError

MAX_IMAGES = 3  # Groq limit for qwen/qwen3.8-27b
MAX_REQUEST_BYTES = 20 * 1024 * 1024  # Groq request limit with images
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_SIDE = 1600
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_WAIT = 30.0

_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def prepare_image(png: bytes, *, max_side: int = MAX_IMAGE_SIDE) -> str:
    """PNG bytes -> data URL: long side at most `max_side` px, JPEG under MAX_IMAGE_BYTES."""
    try:
        image = Image.open(io.BytesIO(png))
        image.load()
    except Exception as exc:  # noqa: BLE001 - any decode failure is a VLM input error
        raise VlmError(f"image could not be decoded: {exc}") from exc
    image = image.convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    for quality in (85, 70, 55, 40):
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=quality, optimize=True)
        if out.tell() <= MAX_IMAGE_BYTES:
            break
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def parse_json_reply(content: str) -> dict[str, Any]:
    """Strip <think> blocks and code fences, then parse one JSON object."""
    text = _FENCE.sub("", _THINK.sub("", content or "")).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise VlmError("VLM reply is not JSON") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise VlmError("VLM reply is not JSON") from exc
    if not isinstance(data, dict):
        raise VlmError("VLM reply is JSON but not an object")
    return data


class GroqVlmClient:
    """VlmClient for Groq. Retries 429/5xx/network errors with exponential backoff (honouring
    Retry-After); a 429 that outlasts the retries raises VlmBudgetExceeded."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff: float = 1.0,
        reasoning_effort: str | None = "none",
        reasoning_format: str | None = "hidden",
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        key = api_key or config.GROQ_API_KEY
        if not key:
            raise VlmError("GROQ_API_KEY is not set; the VLM fallback is unavailable (extraction runs text/OCR only)")
        self.model = model or config.GROQ_VLM_MODEL
        self.max_retries = max_retries
        self.backoff = backoff
        # Groq docs (2026-10-31): qwen/qwen3.8-27b accepts reasoning_effort none|default|low|medium|high
        # (default none); JSON mode needs reasoning_format parsed|hidden ("raw" is a 400).
        self.reasoning_effort = reasoning_effort
        self.reasoning_format = reasoning_format
        self._sleep = sleep
        self.requests_sent = 0
        self._http = httpx.Client(
            base_url=(base_url or config.GROQ_BASE_URL).rstrip("/") + "/",
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _body(self, prompt: str, images: Sequence[bytes], max_tokens: int) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": prepare_image(png)}} for png in images]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You read documents and reply with a single JSON object. Never invent values."},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_completion_tokens": max_tokens,
        }
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        if self.reasoning_format is not None:
            body["reasoning_format"] = self.reasoning_format
        return body

    def _wait(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None and (after := response.headers.get("retry-after")):
            try:
                return min(float(after), MAX_RETRY_WAIT)
            except ValueError:
                pass
        return min(self.backoff * 2**attempt, MAX_RETRY_WAIT)

    def complete_json(self, prompt: str, images: Sequence[bytes] = (), *, max_tokens: int = 2048) -> dict[str, Any]:
        if len(images) > MAX_IMAGES:
            raise VlmError(f"at most {MAX_IMAGES} images per request, got {len(images)}")
        body = self._body(prompt, images, max_tokens)
        payload = json.dumps(body).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            raise VlmError("request is over Groq's 20 MB limit")

        last_status: int | None = None
        for attempt in range(self.max_retries + 1):
            response: httpx.Response | None = None
            try:
                self.requests_sent += 1
                response = self._http.post("chat/completions", content=payload, headers={"Content-Type": "application/json"})
            except httpx.TransportError as exc:
                last_status = None
                if attempt == self.max_retries:
                    raise VlmError(f"Groq request failed: {type(exc).__name__}") from exc
                self._sleep(self._wait(attempt, None))
                continue
            if response.status_code in RETRY_STATUSES:
                last_status = response.status_code
                if attempt < self.max_retries:
                    self._sleep(self._wait(attempt, response))
                    continue
                break
            if response.status_code >= 400:
                raise VlmError(f"Groq HTTP {response.status_code}: {_error_message(response)}")
            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise VlmError("unexpected Groq response shape") from exc
            return parse_json_reply(content)

        if last_status == 429:
            raise VlmBudgetExceeded(f"Groq rate limit (429) persisted after {self.max_retries} retries")
        raise VlmError(f"Groq unavailable (HTTP {last_status or 'network error'}) after {self.max_retries} retries")


def _error_message(response: httpx.Response) -> str:
    try:
        err = response.json().get("error", {})
        return str(err.get("message") or err)[:200]
    except ValueError:
        return response.text[:200]
