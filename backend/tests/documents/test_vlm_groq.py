"""GroqVlmClient over httpx.MockTransport: request shape, limits, retries, reply parsing. No network."""

import base64
import io
import json
import os

import httpx
import pytest
from PIL import Image

from app import config
from app.documents.ports import VlmBudgetExceeded, VlmError
from app.documents.vlm import GroqVlmClient, get_default_vlm
from app.documents.vlm.groq import parse_json_reply

KEY = "gsk_test_not_a_real_key"


def png(width: int = 40, height: int = 20) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def reply(content: str, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json={"choices": [{"message": {"role": "assistant", "content": content}}]}, headers=headers)


def client(handler, **kwargs) -> tuple[GroqVlmClient, list[float]]:
    sleeps: list[float] = []
    vlm = GroqVlmClient(KEY, base_url="https://api.groq.test/openai/v1", transport=httpx.MockTransport(handler), sleep=sleeps.append, **kwargs)
    return vlm, sleeps


def test_request_shape():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply('{"pan": "ABCPK1234F"}')

    vlm, _ = client(handler)
    assert vlm.complete_json("Read the card", [png(), png()], max_tokens=512) == {"pan": "ABCPK1234F"}

    request = seen[0]
    assert str(request.url) == "https://api.groq.test/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == config.GROQ_VLM_MODEL
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 512 and body["temperature"] == 0
    assert body["reasoning_effort"] == "none" and body["reasoning_format"] == "hidden"
    assert "include_reasoning" not in body  # mutually exclusive with reasoning_format
    content = body["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "Read the card"}
    images = [part for part in content if part["type"] == "image_url"]
    assert len(images) == 2
    url = images[0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).verify()


def test_reasoning_params_can_be_turned_off():
    bodies = []
    vlm, _ = client(lambda r: bodies.append(json.loads(r.content)) or reply("{}"), reasoning_effort=None, reasoning_format=None)
    vlm.complete_json("x")
    assert "reasoning_effort" not in bodies[0] and "reasoning_format" not in bodies[0]


def test_more_than_three_images_is_refused_before_sending():
    calls = []
    vlm, _ = client(lambda r: calls.append(r) or reply("{}"))
    with pytest.raises(VlmError, match="at most 3 images"):
        vlm.complete_json("x", [png()] * 4)
    assert calls == []


def test_large_image_is_downscaled():
    bodies = []
    vlm, _ = client(lambda r: bodies.append(json.loads(r.content)) or reply("{}"))
    vlm.complete_json("x", [png(4000, 1000)])
    url = bodies[0]["messages"][-1]["content"][1]["image_url"]["url"]
    image = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(image.size) == 1600 and image.format == "JPEG"


def test_429_backs_off_honouring_retry_after_then_succeeds():
    responses = iter([httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "rate limited"}}), httpx.Response(503), reply('{"ok": true}')])
    vlm, sleeps = client(lambda r: next(responses))
    assert vlm.complete_json("x") == {"ok": True}
    assert sleeps == [2.0, 2.0]  # Retry-After honoured, then exponential backoff (1 * 2**1)
    assert vlm.requests_sent == 3


def test_persistent_429_raises_budget_exceeded():
    vlm, sleeps = client(lambda r: httpx.Response(429), max_retries=3)
    with pytest.raises(VlmBudgetExceeded):
        vlm.complete_json("x")
    assert sleeps == [1.0, 2.0, 4.0] and vlm.requests_sent == 4


def test_persistent_5xx_and_network_errors_raise_vlm_error():
    vlm, _ = client(lambda r: httpx.Response(500), max_retries=1)
    with pytest.raises(VlmError) as exc:
        vlm.complete_json("x")
    assert not isinstance(exc.value, VlmBudgetExceeded)

    def boom(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    vlm, sleeps = client(boom, max_retries=2)
    with pytest.raises(VlmError, match="ConnectTimeout"):
        vlm.complete_json("x")
    assert len(sleeps) == 2


def test_client_error_is_not_retried_and_never_leaks_the_key():
    vlm, sleeps = client(lambda r: httpx.Response(400, json={"error": {"message": "json_validate_failed"}}))
    with pytest.raises(VlmError) as exc:
        vlm.complete_json("x")
    assert "json_validate_failed" in str(exc.value) and KEY not in str(exc.value)
    assert sleeps == []


def test_think_blocks_and_fences_are_stripped():
    assert parse_json_reply('<think>the PAN looks like ABC...</think>\n{"pan": "ABCPK1234F"}') == {"pan": "ABCPK1234F"}
    assert parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_reply('Here you go: {"a": 1} hope this helps') == {"a": 1}
    with pytest.raises(VlmError):
        parse_json_reply("<think>unterminated reasoning {")
    with pytest.raises(VlmError):
        parse_json_reply("[1, 2]")

    vlm, _ = client(lambda r: reply('<think>hmm</think>{"dob": "15/08/1985"}'))
    assert vlm.complete_json("x") == {"dob": "15/08/1985"}


def test_missing_key_fails_clearly_and_default_is_none(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    with pytest.raises(VlmError, match="GROQ_API_KEY"):
        GroqVlmClient()
    assert get_default_vlm() is None

    monkeypatch.setattr(config, "GROQ_API_KEY", KEY)
    default = get_default_vlm()
    assert isinstance(default, GroqVlmClient)
    default.close()


@pytest.mark.skipif(os.getenv("RUN_VLM_TESTS") != "1" or not config.GROQ_API_KEY, reason="live Groq call: set RUN_VLM_TESTS=1 and GROQ_API_KEY")
def test_live_groq_json_reply():
    vlm = GroqVlmClient()
    result = vlm.complete_json('Return {"status": "ok"} as JSON.', [png()], max_tokens=64)
    assert isinstance(result, dict)
