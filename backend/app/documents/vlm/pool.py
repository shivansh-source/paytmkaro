"""A pool of Groq workers, one per API key, behind the same VlmClient interface.

Why: every key has its own tokens-per-minute limit, and a single key's limit is what makes uploads slow (or time
out) when several documents need the vision model together. Each request goes to a free worker, so documents
spread over the keys and are read in parallel.

How a request is routed:
- A worker handles one request at a time (it holds its key's "slot").
- Among free workers with token room in their last minute, the least recently used one is chosen, so concurrent
  documents land on different keys.
- A 429 from a key benches only that worker (for the provider's Retry-After, at most a minute) and the request
  moves straight to another worker. Nothing sleeps inside a worker.
- If every worker is busy or benched, the request waits for one to free up, but never longer than
  `max_wait` seconds. After that it raises VlmBudgetExceeded and the upload carries on without the vision model.
  That cap, not the number of keys, is what keeps an upload inside the web proxy's time limit.

Keys never appear in names, logs, reprs or errors: workers are called "worker 1", "worker 2" ...

Only use keys you are entitled to use at the same time. Providers set their own rules about multiple accounts.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from app import config
from app.documents.ports import VlmBudgetExceeded, VlmClient, VlmError

log = logging.getLogger(__name__)

IMAGE_TOKENS = 2048  # Groq counts every image as 2,048 input tokens
WINDOW_SECONDS = 60.0  # the tokens-per-minute window
MAX_BENCH_SECONDS = 60.0
DEFAULT_BENCH_SECONDS = 20.0  # used when a 429 carries no Retry-After
POLL_SECONDS = (0.05, 0.5)  # shortest and longest pause while waiting for a free worker


def estimate_tokens(prompt: str, images: Sequence[bytes], max_tokens: int) -> int:
    """What a request will count against a key's per-minute limit: images, prompt, and the requested reply size."""
    return IMAGE_TOKENS * len(images) + len(prompt) // 3 + 80 + max_tokens


class _Worker:
    def __init__(self, index: int, client: VlmClient):
        self.index = index
        self.name = f"worker {index}"
        self.client = client
        self.busy = False
        self.benched_until = 0.0
        self.last_used = 0.0
        self.requests = 0
        self.rate_limited = 0
        self.window: deque[tuple[float, int]] = deque()  # (time, estimated tokens) of recent requests

    def used(self, now: float) -> int:
        while self.window and now - self.window[0][0] >= WINDOW_SECONDS:
            self.window.popleft()
        return sum(tokens for _, tokens in self.window)

    def has_room(self, now: float, cost: int, limit: int) -> bool:
        used = self.used(now)
        # A request bigger than a whole window can never fit: let it through on an empty window.
        return used + cost <= limit or used == 0

    def next_available(self, now: float, cost: int, limit: int) -> float:
        """Earliest time this worker could take `cost` more tokens (ignoring that it may be busy)."""
        when = max(self.benched_until, now)
        if self.has_room(now, cost, limit):
            return when
        used = self.used(now)
        for stamp, tokens in self.window:
            used -= tokens
            if used + cost <= limit or used <= 0:
                return max(when, stamp + WINDOW_SECONDS)
        return max(when, now)


class GroqWorkerPool:
    """VlmClient that spreads requests over several workers (see the module docstring)."""

    def __init__(
        self,
        clients: Sequence[VlmClient],
        *,
        tpm_limit: int | None = None,
        max_wait: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not clients:
            raise VlmError("a worker pool needs at least one client")
        self._workers = [_Worker(i, client) for i, client in enumerate(clients, start=1)]
        # Keep a little headroom under the published limit: our token estimate is not Groq's exact count.
        self._limit = int((tpm_limit if tpm_limit is not None else config.VLM_TPM_LIMIT) * 0.9)
        self._max_wait = max_wait if max_wait is not None else config.VLM_MAX_WAIT_SECONDS
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()

    @classmethod
    def from_keys(cls, keys: Sequence[str], **kwargs: Any) -> GroqWorkerPool:
        from app.documents.vlm.groq import GroqVlmClient

        # A 429 must fail over at once, not sleep; transient 5xx / network errors still get a short retry.
        clients = [GroqVlmClient(api_key=key, max_retries=2, retry_rate_limit=False) for key in keys]
        return cls(clients, **kwargs)

    def __len__(self) -> int:
        return len(self._workers)

    def __repr__(self) -> str:
        return f"GroqWorkerPool({len(self._workers)} workers)"

    def stats(self) -> list[dict[str, Any]]:
        """Per-worker counters, for logs and tests. Never contains a key."""
        now = self._clock()
        with self._lock:
            return [
                {"worker": w.name, "requests": w.requests, "rate_limited": w.rate_limited,
                 "tokens_last_minute": w.used(now), "benched": w.benched_until > now}
                for w in self._workers
            ]

    # ----- routing -----

    def _try_acquire(self, cost: int) -> tuple[_Worker | None, float]:
        """Reserve the best free worker, or report how long to wait before looking again."""
        with self._lock:
            now = self._clock()
            free = [w for w in self._workers if not w.busy and w.benched_until <= now and w.has_room(now, cost, self._limit)]
            if free:
                worker = min(free, key=lambda w: (w.last_used, w.index))
                worker.busy = True
                worker.last_used = now
                worker.requests += 1
                worker.window.append((now, cost))
                return worker, 0.0
            idle = [w for w in self._workers if not w.busy]
            soonest = min((w.next_available(now, cost, self._limit) for w in idle), default=now)
            return None, max(soonest - now, 0.0)

    def _release(self, worker: _Worker, *, bench_for: float | None = None, refund: int | None = None) -> None:
        with self._lock:
            worker.busy = False
            if bench_for is not None:
                worker.rate_limited += 1
                worker.benched_until = self._clock() + min(max(bench_for, 1.0), MAX_BENCH_SECONDS)
            if refund is not None:  # the request did not count against the key
                for item in reversed(worker.window):
                    if item[1] == refund:
                        worker.window.remove(item)
                        break

    def complete_json(self, prompt: str, images: Sequence[bytes] = (), *, max_tokens: int = 2048) -> dict[str, Any]:
        cost = estimate_tokens(prompt, images, max_tokens)
        deadline = self._clock() + self._max_wait
        while True:
            worker, wait = self._try_acquire(cost)
            if worker is None:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise VlmBudgetExceeded("The AI reader is busy right now; carrying on without it", retry_after=wait or None)
                self._sleep(min(max(wait, POLL_SECONDS[0]), POLL_SECONDS[1], remaining))
                continue
            log.info("VLM request on %s (about %d tokens)", worker.name, cost)
            try:
                reply = worker.client.complete_json(prompt, images, max_tokens=max_tokens)
            except VlmBudgetExceeded as exc:
                log.warning("%s hit its rate limit; trying another worker", worker.name)
                self._release(worker, bench_for=exc.retry_after or DEFAULT_BENCH_SECONDS, refund=cost)
                continue
            except BaseException:
                self._release(worker)
                raise
            self._release(worker)
            return reply
