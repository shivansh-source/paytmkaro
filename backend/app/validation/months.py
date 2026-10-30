"""Month helpers. Months are "YYYY-MM" strings throughout."""

from __future__ import annotations

from datetime import date


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_label(month: str) -> str:
    """"2026-07" -> "Jul 2026", for messages the SME reads."""
    y, m = month.split("-")
    return f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m) - 1]} {y}"


def month_range(first: str, last: str) -> list[str]:
    """Inclusive list of months from first to last."""
    y, m = map(int, first.split("-"))
    end = tuple(map(int, last.split("-")))
    out: list[str] = []
    while (y, m) <= end:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def months_between(start: date, end: date) -> int:
    """Whole months from start to end (14 for 20 Aug 2025 -> 31 Oct 2026)."""
    return (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    days = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(d.day, days[month - 1]))
