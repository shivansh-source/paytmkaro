"""Text normalization and OCR-tolerant phrase matching for the classifier.

Two views of a page's text are kept apart on purpose:
- `raw`: the text as read (case kept), used by the ID-number regexes in signals.py,
  which apply their own position-aware OCR coercion;
- `folded`: lowercased with common OCR confusions folded (0->o, 1/l/|->i, 5->s), used
  for keyword matching only, so "D0B" matches "dob" and "PERMANENT ACC0UNT" matches.

Keyword tables are passed through the same `fold()` at import, so Devanagari keywords
and page text go through identical NFKC normalization.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)
_OCR_FOLD = str.maketrans({"0": "o", "1": "i", "l": "i", "|": "i", "5": "s"})

# Fuzzy matching: phrases shorter than this (after squashing) must match exactly,
# since one OCR error in a short word is indistinguishable from a different word.
FUZZY_MIN_LEN = 10
FUZZY_MIN_RATIO = 0.85
# A phrase is only fuzzy-checked when this share of its trigrams occur in the page.
FUZZY_TRIGRAM_GATE = 0.5


def fold(text: str) -> str:
    """NFKC, drop zero-width chars, lowercase, fold OCR confusions, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).lower().translate(_OCR_FOLD)
    return re.sub(r"\s+", " ", text).strip()


def squash(folded: str) -> str:
    """Keep only letters, digits and combining marks (Devanagari matras), so dropped or
    extra spaces and punctuation don't matter: "statement of a/c" -> "statementofac"."""
    return "".join(ch for ch in folded if unicodedata.category(ch)[0] in "LNM")


def _trigrams(s: str) -> list[str]:
    return [s[i : i + 3] for i in range(len(s) - 2)]


@dataclass
class PageText:
    """One page's text prepared once for all signal checks."""

    raw: str
    folded: str = ""
    squashed: str = ""
    _index: dict[str, list[int]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.folded = fold(self.raw)
        self.squashed = squash(self.folded)
        index: dict[str, list[int]] = defaultdict(list)
        for i, gram in enumerate(_trigrams(self.squashed)):
            index[gram].append(i)
        self._index = dict(index)

    def find(self, phrase_squashed: str, *, fuzzy: bool = True) -> float:
        """1.0 for an exact (squashed) match, the fuzzy ratio (>= FUZZY_MIN_RATIO) for a
        near match, else 0.0."""
        if not phrase_squashed:
            return 0.0
        if phrase_squashed in self.squashed:
            return 1.0
        if not fuzzy or len(phrase_squashed) < FUZZY_MIN_LEN:
            return 0.0
        return self._fuzzy(phrase_squashed)

    def _fuzzy(self, phrase: str) -> float:
        grams = _trigrams(phrase)
        present = [(offset, g) for offset, g in enumerate(grams) if g in self._index]
        if len(present) < FUZZY_TRIGRAM_GATE * len(grams):
            return 0.0
        # Each shared trigram votes for where the phrase would start in the page.
        votes: Counter[int] = Counter()
        for offset, gram in present:
            for pos in self._index[gram][:50]:  # cap very common trigrams (e.g. "000")
                votes[pos - offset] += 1
        best = 0.0
        n = len(phrase)
        for start, _ in votes.most_common(3):
            for s in (start - 1, start, start + 1):
                for length in (n - 2, n - 1, n, n + 1, n + 2):
                    lo = max(s, 0)
                    window = self.squashed[lo : lo + length]
                    if window:
                        best = max(best, SequenceMatcher(None, window, phrase, autojunk=False).ratio())
        return best if best >= FUZZY_MIN_RATIO else 0.0


def token_regex(token: str) -> re.Pattern[str]:
    """Regex for a short folded token on `PageText.folded`: separators between characters
    are optional ("itr-v", "itr v", "itrv") and it may not touch other letters or digits."""
    chars = [re.escape(c) for c in squash(fold(token))]
    body = r"[\s\-./:]*".join(chars)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")
