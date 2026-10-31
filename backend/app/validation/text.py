"""Fuzzy matching for names and addresses across documents.

Names: exact (after normalising) is a pass; initials or a near spelling ("R. Kumar", "Ravi Kumaar") is a
warning for the user to confirm, never a silent pass or a hard fail.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.schemas.common import CheckStatus

_HONORIFICS = {"MR", "MRS", "MS", "MISS", "SHRI", "SMT", "KUM", "DR", "M/S", "MS/"}
_PINCODE = re.compile(r"\b([1-9][0-9]{5})\b")
_ADDRESS_STOPWORDS = {"NO", "NEAR", "OPP", "ROAD", "RD", "STREET", "ST", "MAIN", "CROSS", "FLOOR", "SAMPLE"}


def normalize_name(name: str) -> str:
    tokens = re.sub(r"[^A-Z ]", " ", name.upper().replace("M/S", " ")).split()
    return " ".join(t for t in tokens if t not in _HONORIFICS)


def _initials_compatible(a: list[str], b: list[str]) -> bool:
    """'R KUMAR' ~ 'RAVI KUMAR': same length, each pair equal or one is the other's initial."""
    if len(a) != len(b):
        return False
    return all(x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)) for x, y in zip(a, b))


_BRACKETED = re.compile(r"^(.*?)\((.*?)\)(.*)$")
_RANK = {CheckStatus.PASS: 0, CheckStatus.WARN: 1, CheckStatus.FAIL: 2}


def _variants(name: str) -> list[str]:
    """Banks often add the business in brackets: 'R. KUMAR (KUMAR TRADERS)'. Try with and without it."""
    variants = [name]
    if m := _BRACKETED.match(name):
        variants += [m.group(1) + m.group(3), m.group(2)]
    return variants


def compare_names(a: str, b: str) -> CheckStatus:
    """Best result over bracket variants of either name; a different person still fails."""
    return min((_compare(x, y) for x in _variants(a) for y in _variants(b)), key=_RANK.__getitem__)


def _compare(a: str, b: str) -> CheckStatus:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return CheckStatus.FAIL
    if na == nb or sorted(na.split()) == sorted(nb.split()):
        return CheckStatus.PASS
    if _initials_compatible(na.split(), nb.split()) or SequenceMatcher(None, na, nb).ratio() >= 0.85:
        return CheckStatus.WARN
    return CheckStatus.FAIL


def pincode_of(text: str, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    found = _PINCODE.findall(text)
    return found[-1] if found else None


def _tokens(text: str) -> set[str]:
    return {t for t in re.sub(r"[^A-Z0-9 ]", " ", text.upper()).split() if t not in _ADDRESS_STOPWORDS and len(t) > 1}


def compare_addresses(a: str, b: str, pin_a: str | None = None, pin_b: str | None = None) -> CheckStatus:
    pa, pb = pincode_of(a, pin_a), pincode_of(b, pin_b)
    ta, tb = _tokens(a), _tokens(b)
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    if pa and pb and pa != pb:
        return CheckStatus.FAIL
    if pa and pa == pb:
        return CheckStatus.PASS if overlap >= 0.5 else CheckStatus.WARN
    return CheckStatus.WARN if overlap >= 0.5 else CheckStatus.FAIL
