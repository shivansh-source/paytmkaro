import threading

import pytest

from app import config
from app.documents import process
from app.documents.ports import VlmBudgetExceeded, VlmError
from app.documents.vlm import get_default_vlm
from app.documents.vlm import pool as pool_module
from app.documents.vlm.pool import GroqWorkerPool


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Fake:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply or {"ok": True}, error, 0

    def complete_json(self, prompt, images=(), *, max_tokens=2048):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


def make(clients, **kw):
    clock = Clock()
    return GroqWorkerPool(clients, tpm_limit=8000, max_wait=kw.pop("max_wait", 15), clock=clock, sleep=clock.sleep, **kw), clock


def test_requests_spread_over_workers():
    a, b, c = Fake(), Fake(), Fake()
    pool, clock = make([a, b, c])
    for _ in range(3):
        pool.complete_json("x", [b"i"], max_tokens=100)
        clock.now += 0.01
    assert (a.calls, b.calls, c.calls) == (1, 1, 1)


def test_429_fails_over_and_benches_worker():
    limited, fine = Fake(error=VlmBudgetExceeded("429", retry_after=30)), Fake()
    pool, clock = make([limited, fine])
    assert pool.complete_json("x", max_tokens=100) == {"ok": True}
    assert limited.calls == 1 and fine.calls == 1
    for _ in range(3):
        clock.now += 1
        pool.complete_json("x", max_tokens=100)
    assert limited.calls == 1  # still benched
    clock.now += 40
    pool.complete_json("x", max_tokens=100); pool.complete_json("x", max_tokens=100)
    assert limited.calls == 2


def test_wait_is_capped_when_every_key_is_limited():
    pool, clock = make([Fake(error=VlmBudgetExceeded("429", retry_after=60)), Fake(error=VlmBudgetExceeded("429", retry_after=60))], max_wait=5)
    start = clock.now
    with pytest.raises(VlmBudgetExceeded):
        pool.complete_json("x")
    assert clock.now - start <= 5.5


def test_worker_released_after_exception():
    bad = Fake(error=VlmError("boom"))
    pool, _ = make([bad])
    with pytest.raises(VlmError):
        pool.complete_json("x")
    bad.error = None
    assert pool.complete_json("x") == {"ok": True}


def test_busy_workers_run_in_parallel_threads():
    gate, entered = threading.Event(), threading.Barrier(2, timeout=5)

    class Slow(Fake):
        def complete_json(self, *a, **k):
            entered.wait()
            return super().complete_json("x")

    a, b = Slow(), Slow()
    pool = GroqWorkerPool([a, b], tpm_limit=8000, max_wait=5)
    out = []
    ts = [threading.Thread(target=lambda: out.append(pool.complete_json("x"))) for _ in range(2)]
    [t.start() for t in ts]; [t.join(10) for t in ts]
    assert len(out) == 2 and a.calls == 1 and b.calls == 1


def test_no_key_in_repr_or_stats():
    pool = GroqWorkerPool.from_keys(["gsk_SECRETKEY1", "gsk_SECRETKEY2"])
    assert "SECRET" not in repr(pool) and "SECRET" not in str(pool.stats()) and len(pool) == 2


def test_config_key_parsing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEYS", " a , b,,a")
    monkeypatch.setenv("GROQ_API_KEY", "b")
    monkeypatch.setenv("GROQ_API_KEY_2", "c")
    monkeypatch.delenv("GROQ_API_KEY_3", raising=False)
    assert config._groq_keys() == ["a", "b", "c"]


def test_default_vlm_is_singleton(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEYS", ["k1", "k2"])
    monkeypatch.setattr(pool_module, "log", pool_module.log)
    assert get_default_vlm() is get_default_vlm()


def test_ocr_disabled_allows_vlm(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    monkeypatch.setattr(config, "GROQ_API_KEYS", ["k1"])
    ocr, vlm = process.default_engines()
    assert ocr is None and vlm is not None
