"""Checksums for Indian identifiers.

- Aadhaar: Verhoeff. Run by the extractor on the full number BEFORE masking; only the boolean result and
  the last 4 digits are kept.
- GSTIN: the 15th character is a base-36 check digit over the first 14.
"""

from __future__ import annotations

# Verhoeff tables: multiplication (D5 group), permutation, inverse.
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_valid(number: str) -> bool:
    if not number.isdigit():
        return False
    check = 0
    for i, ch in enumerate(reversed(number)):
        check = _D[check][_P[i % 8][int(ch)]]
    return check == 0


def verhoeff_check_digit(number: str) -> str:
    check = 0
    for i, ch in enumerate(reversed(number)):
        check = _D[check][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[check])


def aadhaar_valid(number: str) -> bool:
    """12 digits, not starting with 0 or 1, Verhoeff-valid."""
    return len(number) == 12 and number.isdigit() and number[0] not in "01" and verhoeff_valid(number)


_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14.upper()):
        product = _BASE36.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _BASE36[(36 - total % 36) % 36]


def gstin_checksum_valid(gstin: str) -> bool:
    gstin = gstin.upper()
    if len(gstin) != 15 or any(ch not in _BASE36 for ch in gstin):
        return False
    return gstin_check_digit(gstin[:14]) == gstin[14]


# GST state codes in use (01-38) plus 97 (other territory) and 99 (centre jurisdiction).
GST_STATE_CODES = {f"{n:02d}" for n in range(1, 39)} | {"97", "99"}
