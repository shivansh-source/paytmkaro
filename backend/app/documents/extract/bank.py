"""Bank statements: header fields, transaction rows, balance math and coverage checks.

Rows come from Page.tables (spreadsheets/CSV) or from text lines (PDF text layer
or OCR). Debit vs credit on two-amount lines is decided by balance math.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.documents.extract.common import (
    _TO_ALPHA,
    DATE_PATTERN,
    Hit,
    Line,
    PageView,
    after_label,
    amount_tokens,
    clean_value,
    money,
    month_key,
    month_label,
    month_range,
    parse_date,
    parse_inr,
)
from app.documents.extract.readers import PageRead

I = re.IGNORECASE
TOLERANCE = 0.01

_DATE_VALUE = re.compile(DATE_PATTERN, I)
_ROW_START = re.compile(rf"^\s*({DATE_PATTERN})\s+(?:({DATE_PATTERN})\s+)?", I)
_HOLDER_LABEL = re.compile(r"(?:account|a/c|customer)\s*(?:holder'?s?\s*)?name|^\s*name\b", I)
_HEADER_STOP = re.compile(r"account\s*(?:no|number|type)|a/c\s*no|ifsc|branch|address|period|statement|customer\s*id|currency", I)
_ACCOUNT_LABEL = re.compile(r"(?:account|a/c)\s*(?:no|number|#)\.?", I)
_ACCOUNT_VALUE = re.compile(r"[X*x\d][X*x\d\s-]{4,}\d{4}")
_TO_ZERO = str.maketrans({"O": "0", "D": "0", "Q": "0"})
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_PERIOD = re.compile(rf"({DATE_PATTERN})\s*(?:to|till|-|–)\s*({DATE_PATTERN})", I)
_FOOTER = re.compile(r"opening\s*balance|closing\s*balance|total|page\s*\d|statement|generated|end of|\*\*|computer", I)

CREDIT_HINT = re.compile(r"\b(?:CR|BY|DEP|DEPOSIT|CREDIT|REFUND|INTEREST|INT\.?PD|SALARY|RECEIVED|RCVD|COLLECTION)\b|-CR\b|/CR/", I)
DEBIT_HINT = re.compile(r"\b(?:DR|TO|WDL|ATM|PURCHASE|EMI|NACH|ECS|ACH|POS|PAID|CHG|CHGS|CHARGES|FEE|BILL)\b|-DR\b|/DR/", I)


def read_header(view: PageView, read: PageRead) -> None:
    lines = view.lines
    read.put("account_holder_name", after_label(lines, _HOLDER_LABEL, ahead=1, stop=_HEADER_STOP))
    read.put("bank_name", after_label(lines, re.compile(r"bank\s*name", I), ahead=1, stop=_HEADER_STOP))
    if "bank_name" not in read.fields:
        for line in lines[:6]:
            text = clean_value(line.text)
            if re.search(r"\bbank\b", text, I) and not re.search(r"statement|name|account", text, I) and len(text) <= 60:
                read.put("bank_name", Hit(text, line.confidence))
                break
    for line in lines:
        if m := _IFSC.search(line.text.upper()):
            read.put("ifsc", Hit(m.group(0), line.confidence))
            break
    if "ifsc" not in read.fields:
        read.put("ifsc", _repaired_ifsc(lines))
    account = after_label(lines, _ACCOUNT_LABEL, _ACCOUNT_VALUE, ahead=1)
    if account:
        # Only the last 4 digits are kept; the full number never enters the result.
        read.put("account_number_last4", Hit(re.sub(r"\D", "", account.value)[-4:], account.confidence))
    for line in lines:
        if re.search(r"period|from|statement", line.text, I) and (m := _PERIOD.search(line.text)):
            read.put("period_from", Hit(m.group(1), line.confidence))
            read.put("period_to", Hit(m.group(2), line.confidence))
            break
    read.put("opening_balance", _balance_after(lines, re.compile(r"opening\s*balance", I)))
    read.put("closing_balance", _balance_after(lines, re.compile(r"closing\s*balance", I)))


_IFSC_LABELLED = re.compile(r"\bIFSC(?:\s*code)?\b\s*[:.\-–]?\s*([A-Z0-9]{11})\b", I)


def repair_ifsc(raw: str) -> str:
    """IFSC = 4 letters, the digit 0, then 6 letters/digits. Fixes letter/digit swaps in the first
    five positions only (DEM00001234 -> DEMO0001234); the last six are free, so they are left as read."""
    s = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if len(s) != 11:
        return s
    return s[:4].translate(_TO_ALPHA) + s[4:5].translate(_TO_ZERO) + s[5:]


def _repaired_ifsc(lines: list[Line]) -> Hit | None:
    """Only next to an 'IFSC' label: an 11-character token elsewhere on the page proves nothing."""
    for line in lines:
        if m := _IFSC_LABELLED.search(line.text.upper()):
            fixed = repair_ifsc(m.group(1))
            if fixed != m.group(1) and _IFSC.fullmatch(fixed):
                return Hit(fixed, min(line.confidence, 0.6), f"OCR letter/digit swaps corrected from {m.group(1)}")
    return None


def _balance_after(lines: list[Line], label: re.Pattern[str]) -> Hit | None:
    for line in lines:
        if (m := label.search(line.text)) and not _ROW_START.match(line.text):
            tokens = amount_tokens(line.text[m.end():])
            if tokens:
                return Hit(tokens[0].group(0), line.confidence)
    return None


# ---------- Rows ----------


def _row_from(date_text: str, body: str, confidence: float) -> dict[str, Any] | None:
    """One transaction from its date and the rest of the line(s): narration, then amounts."""
    tokens = amount_tokens(body)
    if not tokens:
        return None
    narration = body[: tokens[0].start()].strip(" |")
    values = [t.group(0) for t in tokens]
    row: dict[str, Any] = {"date": date_text, "narration": narration, "ref": None, "_confidence": confidence}
    parts = narration.rsplit(" ", 1)
    if len(parts) == 2 and re.fullmatch(r"\d{6,}", parts[1]):
        row["narration"], row["ref"] = parts[0].strip(), parts[1]
    if len(values) >= 3:
        row["debit"], row["credit"], row["balance"] = values[-3], values[-2], values[-1]
    elif len(values) == 2:
        row["_amount"], row["balance"] = values[0], values[1]
    elif re.search(r"opening\s*balance|b/f|brought\s*forward", narration, I):
        row["_opening"] = values[0]
    else:
        return None
    return row


def _text_rows(view: PageView) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    continuing = False
    pending: tuple[str, str, float] | None = None  # a dated line whose amounts wrap onto the next line
    for line in view.lines:
        text = line.text
        start = _ROW_START.match(text)
        if start and parse_date(start.group(1)) is not None:
            body = text[start.end():]
            row = _row_from(start.group(1), body, line.confidence)
            pending = None if row else (start.group(1), body.strip(), line.confidence)
            if row:
                rows.append(row)
            continuing = row is not None and "_opening" not in row
            continue
        if pending and amount_tokens(text) and not _FOOTER.search(text):
            date_text, head, conf = pending
            row = _row_from(date_text, f"{head} {text.strip()}", min(conf, line.confidence))
            pending = None
            if row:
                rows.append(row)
                continuing = True
                continue
        # Wrapped narration: a line with no date and no amounts right after a row.
        if continuing and rows and not amount_tokens(text) and not _FOOTER.search(text):
            rows[-1]["narration"] = f"{rows[-1]['narration']} {text.strip()}".strip()
        else:
            continuing = False
    return rows


_COLUMNS = [
    ("date", r"^(?:txn|tran|transaction|value)?\s*date$|^date$|^txn\s*date|^tran\s*date|^transaction\s*date|^date\b"),
    ("narration", r"narration|description|particulars|remarks|details"),
    ("ref", r"ref|chq|cheque|instrument"),
    ("debit", r"debit|withdrawal|^dr\.?$|paid\s*out"),
    ("credit", r"credit|deposit|^cr\.?$|paid\s*in"),
    ("balance", r"balance"),
    ("amount", r"^amount|amount\s*\(inr\)|^amt"),
    ("type", r"^(?:dr\s*/\s*cr|cr\s*/\s*dr|type)$"),
]


def _table_rows(view: PageView) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in view.tables:
        cols: dict[str, int] = {}
        header_at = None
        for r, cells in enumerate(table):
            found: dict[str, int] = {}
            for j, cell in enumerate(cells):
                low = cell.strip().lower()
                for name, pattern in _COLUMNS:
                    if name not in found and re.search(pattern, low):
                        found[name] = j
                        break
            if "date" in found and "balance" in found and ({"debit", "credit"} <= found.keys() or "amount" in found):
                cols, header_at = found, r
                break
        if header_at is None:
            continue
        for cells in table[header_at + 1 :]:
            get = lambda name: cells[cols[name]].strip() if name in cols and cols[name] < len(cells) else ""  # noqa: E731
            if parse_date(get("date")) is None:
                if rows and get("narration") and not any(get(k) for k in ("debit", "credit", "balance", "amount")):
                    rows[-1]["narration"] = f"{rows[-1]['narration']} {get('narration')}".strip()
                continue
            row: dict[str, Any] = {"date": get("date"), "narration": get("narration"), "ref": get("ref") or None, "balance": get("balance") or None, "_confidence": 0.95}
            if "debit" in cols:
                row["debit"], row["credit"] = get("debit") or None, get("credit") or None
            else:
                kind = get("type").lower()
                amount = get("amount")
                if kind.startswith("d"):
                    row["debit"] = amount
                elif kind.startswith("c"):
                    row["credit"] = amount
                else:
                    row["_amount"] = amount
            rows.append(row)
    return rows


def read_bank_statement(view: PageView) -> PageRead:
    read = PageRead()
    read_header(view, read)
    read.rows = _table_rows(view) or _text_rows(view)
    return read


# ---------- Resolution and checks ----------


def _fits(prev: float | None, debit: float, credit: float, balance: float | None) -> bool | None:
    if prev is None or balance is None:
        return None
    return abs(prev - debit + credit - balance) <= TOLERANCE


def resolve_rows(rows: list[dict[str, Any]], opening: float | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse amounts, order rows oldest-first, decide debit/credit for single-amount rows, and check
    every row: previous printed balance - debit + credit must equal this row's printed balance.
    Each row is checked against the previous *printed* balance, so an edited amount breaks one
    row and an edited balance breaks that row and the next one."""
    warnings: list[str] = []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if "_opening" in row:
            opening = opening if opening is not None else parse_inr(row["_opening"])
            continue
        d = parse_date(row["date"]) if not isinstance(row["date"], date) else row["date"]
        if d is None:
            warnings.append(f"Skipped a row with an unreadable date: {row['date']!r}")
            continue
        balance_raw = row.get("balance")
        balance = parse_inr(balance_raw)
        out = {
            "date": d,
            "narration": " ".join(str(row.get("narration") or "").split()),
            "ref": row.get("ref"),
            "debit": parse_inr(row.get("debit")),
            "credit": parse_inr(row.get("credit")),
            "balance": balance,
            "_amount": parse_inr(row.get("_amount")),
            "_amount_raw": str(row.get("_amount") or ""),
            "_confidence": row.get("_confidence", 0.8),
            "_source": row.get("_source"),
            "_page": row.get("_page"),
        }
        for key in ("debit", "credit"):
            if out[key] is not None:
                out[key] = abs(out[key])
        # An amount that was printed but cannot be parsed stays None and is reported; it is never a 0.
        unreadable = [k for k in ("debit", "credit", "balance", "_amount") if str(row.get(k) or "").strip() not in {"", "-", "--", "—"} and out[k] is None]
        for key in unreadable:
            warnings.append(f"Row {d.strftime('%d/%m/%Y')}: the {key.strip('_')} {str(row.get(key))[:20]!r} could not be read as an amount; left empty")
        out["_unreadable"] = bool(unreadable)
        parsed.append(out)
    if len(parsed) > 1 and parsed[0]["date"] > parsed[-1]["date"]:
        parsed.reverse()
        warnings.append("Statement lists newest transactions first; rows were re-ordered oldest-first")

    prev = opening
    for n, row in enumerate(parsed, 1):
        amount = row.pop("_amount")
        raw = row.pop("_amount_raw")
        if amount is not None and row["debit"] is None and row["credit"] is None:
            amount = abs(amount)
            if _fits(prev, amount, 0, row["balance"]):
                row["debit"] = amount
            elif _fits(prev, 0, amount, row["balance"]):
                row["credit"] = amount
            else:
                # Balance math cannot decide: fall back to the printed Dr/Cr marker, then narration words.
                marker = re.search(r"(cr|dr)\s*$", raw, I)
                is_credit = marker.group(1).lower() == "cr" if marker else bool(CREDIT_HINT.search(row["narration"])) and not DEBIT_HINT.search(row["narration"])
                row["credit" if is_credit else "debit"] = amount
                row["direction_inferred"] = True
        debit, credit = row["debit"] or 0.0, row["credit"] or 0.0
        ok = None if row.pop("_unreadable") else _fits(prev, debit, credit, row["balance"])
        row["balance_ok"] = ok
        if ok is False:
            expected = prev - debit + credit
            warnings.append(
                f"Balance math breaks at row {n} ({row['date'].strftime('%d/%m/%Y')} '{row['narration'][:40]}'): "
                f"previous balance {money(prev)} - debit {money(debit)} + credit {money(credit)} = {money(expected)}, "
                f"but the statement shows {money(row['balance'])}"
            )
        if row["balance"] is not None:
            prev = row["balance"]
    return parsed, warnings


def missing_months(rows: list[dict[str, Any]], start: date, end: date) -> list[str]:
    """Calendar months inside the statement period with no transactions at all."""
    seen = {month_key(r["date"]) for r in rows}
    return [m for m in month_range(start, end) if m not in seen]


def coverage_warnings(gaps: list[str]) -> list[str]:
    return [f"No transactions in {month_label(m)}: a page or month may be missing from the statement" for m in gaps]
