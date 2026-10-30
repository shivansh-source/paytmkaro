"""One pool of VLM requests, shared by everything that handles one uploaded file."""

from __future__ import annotations


class VlmBudget:
    """Counts VLM requests left. The classifier, the extractor and every segment of one upload
    should share one instance so the whole file stays under VLM_MAX_REQUESTS_PER_DOCUMENT."""

    def __init__(self, remaining: int):
        self.total = max(int(remaining), 0)
        self.remaining = self.total

    @property
    def used(self) -> int:
        return self.total - self.remaining

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def spend(self) -> bool:
        """Take one request from the pool; False (and nothing taken) when it is empty."""
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True

    def drain(self) -> None:
        """Stop all further VLM use (e.g. after a rate limit)."""
        self.remaining = 0
