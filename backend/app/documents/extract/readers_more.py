"""Text-pass readers for bureau reports, Udyam certificates, financial statements, sanction letters
and settlement reports. Same contract as readers.py: raw Hits, never validated here."""

from __future__ import annotations

import re
from typing import Any

from app.documents.extract.bank import _PERIOD
from app.documents.extract.common import _TO_ALPHA, _TO_DIGIT, Hit, Line, PageView, after_label, clean_value, parse_date, parse_inr
from app.documents.extract.readers import _DATE_VALUE, _NUMBERED, _PAN_TOKEN, _PIN, PageRead, _multiline_after

I = re.IGNORECASE


def _strip_parens(text: str) -> str:
    return re.sub(r"\([^)]*\)", " ", text)


def _last_int(lines: list[Line], label: re.Pattern[str], *, require: re.Pattern[str] | None = None) -> Hit | None:
    """Last whole number on the label's line (parenthetical ranges like '(last 24 months)' ignored)."""
    for line in lines:
        m = label.search(line.text)
        if not m or (require and not require.search(line.text)):
            continue
        ints = re.findall(r"(?<![\w.,])\d+(?![\w.,]\d)", _strip_parens(line.text[m.end():]))
        if ints:
            return Hit(ints[-1], line.confidence)
    return None


def _yes_no(lines: list[Line], label: re.Pattern[str]) -> Hit | None:
    for line in lines:
        m = label.search(line.text)
        if not m:
            continue
        rest = clean_value(line.text[m.end():])
        if t := re.match(r"(yes|no|nil|none|true|false|\d{1,3})\b", rest, I):
            return Hit(t.group(1), line.confidence)
    return None


def _money_after(lines: list[Line], label: re.Pattern[str], *, skip: re.Pattern[str] | None = None, minimum: float = 100) -> Hit | None:
    """First rupee amount (at least `minimum`, so '5th of the month' is not an amount) after the label."""
    for i, line in enumerate(lines):
        m = label.search(line.text)
        if not m or (skip and skip.search(line.text)):
            continue
        for text, conf in ((line.text[m.end():], line.confidence), (lines[i + 1].text if i + 1 < len(lines) else "", line.confidence)):
            for t in re.finditer(r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)", _strip_parens(text), I):
                value = parse_inr(t.group(1))
                if value is not None and value >= minimum:
                    return Hit(t.group(1), conf)
    return None


# ---------- Bureau report ----------

_BUREAU = re.compile(r"cibil|transunion|experian|equifax|crif(?:\s*high\s*mark)?|credit\s*(?:information\s*)?bureau", I)
_SCORE_NOISE = re.compile(r"range|factor|reason|model|version|between|scale|how |understand", I)
_SCORE = re.compile(r"score(?:\s*\([^)]*\))?[\s:=-]*(?:is\s*)?(NH|N/A|NA|-1|\d{3})(?![\w/.\d-])", I)
_NO_HISTORY = {"NH", "N/A", "NA", "-1", "000"}
_PAN_ANY = re.compile(r"(?<![A-Z0-9*])(?:[A-Z]{5}\d{4}[A-Z]|[X*]{4,8}\d{3}[A-Z])(?![A-Z0-9*])")

_ACCOUNT_COLUMNS = [
    ("account_number", r"account\s*(?:no|number|#)|acct|a/c"),
    ("status", r"status"),
    ("dpd", r"dpd|days\s*past|payment\s*history|history"),
    ("emi", r"emi|instal"),
    ("sanctioned", r"sanction|high\s*credit|credit\s*limit|loan\s*amount|limit"),
    ("outstanding", r"outstanding|current\s*balance|balance"),
    ("account_type", r"type|facility|product"),
    ("lender", r"member|lender|institution|bank|creditor|name"),
]


def read_bureau_report(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    for line in lines:
        if m := _BUREAU.search(line.text):
            read.put("bureau_name", Hit(m.group(0), line.confidence))
            break
    read.put("report_date", after_label(lines, re.compile(r"report\s*date|date\s*of\s*report|generated\s*on|date\s*of\s*issue|report\s*generated|as\s*on", I), _DATE_VALUE, ahead=1))
    for line in lines:
        if m := _PAN_ANY.search(line.text.upper()):
            read.put("pan_masked", Hit(m.group(0), line.confidence))  # masked by the model validator
            break
    for line in lines:
        if "score" not in line.text.lower() or _SCORE_NOISE.search(line.text):
            continue
        if m := _SCORE.search(line.text):
            token = m.group(1).upper()
            if token in _NO_HISTORY:
                read.put("no_credit_history", Hit("yes", line.confidence, f"report shows '{token}' instead of a score"))
            else:
                read.put("score", Hit(token, line.confidence))
            if t := re.search(r"(?:cibil|transunion|experian|equifax|crif)[A-Za-z ]{0,25}?score(?:\s*(?:v|version)?\s*\d(?:\.\d)?)?", line.text, I):
                read.put("score_type", Hit(t.group(0), line.confidence))
            break
    if "score" not in read.fields and "no_credit_history" not in read.fields:
        read.put("score", _boxed_score(lines))
    for line in lines:
        if m := re.search(r"\bCMR\b(?:[\s-]*(?:rank|score))?", line.text):
            if v := re.search(r"(?<![\d/.])(10|[1-9])(?![\d/.])", _strip_parens(line.text[m.end():])):
                read.put("cmr_rank", Hit(v.group(1), line.confidence))
                break
    read.put("active_accounts", _last_int(lines, re.compile(r"(?:active|open|live)\s*(?:credit\s*)?accounts?", I)))
    amounts = [
        ("total_outstanding", r"total\s*(?:current\s*)?(?:outstanding|balance)"),
        ("overdue_amount", r"(?:total\s*)?overdue(?:\s*amount)?|amount\s*overdue"),
    ]
    for name, pattern in amounts:
        read.put(name, _money_after(lines, re.compile(pattern, I), minimum=0))
    read.put("max_dpd_24m", _last_int(lines, re.compile(r"(?:max(?:imum)?|highest|worst)\s*dpd", I)))
    read.put("written_off_or_settled", _yes_no(lines, re.compile(r"written[\s-]*off\s*(?:/|and|or|&)?\s*(?:settled)?\s*(?:accounts?)?|settled\s*accounts?", I)))
    read.put("suit_filed_or_wilful_default", _yes_no(lines, re.compile(r"suit[\s-]*filed(?:\s*(?:/|or|and|&)\s*wilful\s*default)?|wilful\s*default(?:er)?", I)))
    read.put("enquiries_90d", _last_int(lines, re.compile(r"enquir(?:y|ies)", I), require=re.compile(r"90", I)))
    read.rows.extend(_bureau_accounts(view))
    return read


_SCORE_ANCHOR = re.compile(r"score", I)
_LONE_NUMBER = re.compile(r"^\W*(\d{3})\W*(?:/\s*900\W*)?$")
_SCORE_CAPTION = re.compile(r"score|cibil|transunion|experian|equifax|crif|your|credit|bureau", I)


def _boxed_score(lines: list[Line]) -> Hit | None:
    """A score printed large inside a box is its own OCR box, so it is a line holding only a 3-digit
    number, directly above or below the 'score' caption (or one captionless line away). Only a unique
    number strictly inside 300-900 counts: the ends of a printed '300 ... 900' scale are not the score,
    a CMR rank (1-10) has no 3 digits, and a lone number elsewhere on the page is never a candidate."""
    found: dict[int, float] = {}
    for i, line in enumerate(lines):
        if not _SCORE_ANCHOR.search(line.text) or _SCORE_NOISE.search(line.text) or _LONE_NUMBER.match(line.text):
            continue
        for step in (-1, 1):
            for distance in (1, 2):
                j = i + step * distance
                if not 0 <= j < len(lines):
                    break
                m = _LONE_NUMBER.match(lines[j].text)
                if m:
                    found[int(m.group(1))] = min(line.confidence, lines[j].confidence)
                    break
                if not (distance == 1 and _SCORE_CAPTION.search(lines[j].text)):
                    break
    candidates = {v: c for v, c in found.items() if 300 < v < 900}
    if len(candidates) != 1:
        return None
    (value, conf), = candidates.items()
    return Hit(str(value), conf * 0.85, "large number printed next to the score caption")


def _bureau_accounts(view: PageView) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in view.tables:
        cols: dict[str, int] = {}
        start = None
        for r, header in enumerate(table):
            found: dict[str, int] = {}
            for j, cell in enumerate(header):
                low = cell.strip().lower()
                for name, pattern in _ACCOUNT_COLUMNS:
                    if name not in found and name not in found.values() and re.search(pattern, low):
                        found[name] = j
                        break
            if "lender" in found and ("outstanding" in found or "sanctioned" in found):
                cols, start = found, r
                break
        if start is None:
            continue
        for cells in table[start + 1 :]:
            get = lambda name: cells[cols[name]].strip() if name in cols and cols[name] < len(cells) else ""  # noqa: E731
            if not get("lender"):
                continue
            row: dict[str, Any] = {"lender": get("lender"), "_confidence": 0.95}
            for src, dst in (("account_type", "account_type"), ("status", "status"), ("sanctioned", "sanctioned"), ("outstanding", "outstanding"), ("emi", "emi")):
                if get(src):
                    row[dst] = get(src)
            digits = re.sub(r"\D", "", get("account_number"))
            if len(digits) >= 4:
                row["account_last4"] = digits[-4:]  # only the last 4 digits leave the reader
            if dpd := get("dpd"):
                row["dpd_summary"] = dpd
                if ints := [int(x) for x in re.findall(r"\d{1,3}", dpd)]:
                    row["dpd_max"] = max(ints)
            rows.append(row)
    return rows


# ---------- Udyam ----------

_UDYAM = re.compile(r"UDYAM\s*[-–]\s*([A-Z0-9]{2})\s*[-–]\s*([A-Z0-9]{2})\s*[-–]\s*([A-Z0-9]{7})")
_NIC_LINE = re.compile(r"^\W*(\d{2,5})\s*[-–:|]\s*([A-Za-z].{2,100})$")


def read_udyam_certificate(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    for line in lines:
        if m := _UDYAM.search(line.text.upper()):
            state, district, serial = m.groups()
            fixed = (state.translate(_TO_ALPHA), district.translate(_TO_DIGIT), serial.translate(_TO_DIGIT))
            number = f"UDYAM-{fixed[0]}-{fixed[1]}-{fixed[2]}"
            if fixed == m.groups():
                read.put("udyam_number", Hit(number, line.confidence))
            else:
                read.put("udyam_number", Hit(number, min(line.confidence, 0.6), f"OCR letter/digit swaps corrected from {m.group(0)}"))
            break
    read.put("pan", after_label(lines, re.compile(r"\bPAN\b"), _PAN_TOKEN, ahead=1))
    read.put("enterprise_name", after_label(lines, re.compile(r"name\s*of\s*(?:the\s*)?enterprise|enterprise\s*name|unit\s*name", I), ahead=1, stop=_NUMBERED))
    kind = re.compile(r"\b(micro|small|medium)\b", I)
    read.put("enterprise_type", after_label(lines, re.compile(r"type\s*of\s*enterprise|enterprise\s*type|classification", I), kind, ahead=2))
    if "enterprise_type" not in read.fields:
        for line in lines:
            if m := re.match(r"^\W*(micro|small|medium)\b", line.text, I):
                read.put("enterprise_type", Hit(m.group(1), line.confidence))
                break
    read.put("organisation_type", after_label(lines, re.compile(r"type\s*of\s*organi[sz]ation", I), ahead=1, stop=_NUMBERED))
    read.put("date_of_incorporation", after_label(lines, re.compile(r"date\s*of\s*incorporation", I), _DATE_VALUE, ahead=1))
    read.put("date_of_commencement", after_label(lines, re.compile(r"date\s*of\s*commencement", I), _DATE_VALUE, ahead=1))
    read.put("registration_date", after_label(lines, re.compile(r"date\s*of\s*udyam\s*registration|udyam\s*registration\s*date", I), _DATE_VALUE, ahead=1))
    read.put("major_activity", after_label(lines, re.compile(r"major\s*activity", I), re.compile(r"manufacturing|services|trading", I), ahead=1))
    address = _multiline_after(lines, re.compile(r"official\s*address(?:\s*of\s*(?:the\s*)?enterprise)?|address\s*of\s*(?:the\s*)?(?:enterprise|unit)", I))
    read.put("address", address)
    if address and (pins := _PIN.findall(address.value)):
        read.put("pincode", Hit(pins[-1], address.confidence))
    read.put("state", after_label(lines, re.compile(r"^\W*state\b", I), ahead=0))

    nic: list[dict[str, str]] = []
    seen_nic = False
    conf = 1.0
    for line in lines:
        if re.search(r"\bNIC\b", line.text):
            seen_nic = True
            continue
        if seen_nic and re.match(r"^\W*\d{2,5}\s", line.text):
            # One line can hold several codes: "46 Wholesale trade 4690 Non-specialised 46900 ..."
            for chunk in re.split(r"(?=(?<!\d)\d{2,5}\s+[A-Za-z])", line.text):
                if m := re.match(r"\s*(\d{2,5})\s+(.+?)\s*$", chunk):
                    nic.append({"code": m.group(1), "description": clean_value(m.group(2))})
            conf = min(conf, line.confidence)
        elif seen_nic and (m := _NIC_LINE.match(line.text)):
            nic.append({"code": m.group(1), "description": clean_value(m.group(2))})
            conf = min(conf, line.confidence)
    for table in view.tables:
        for cells in table:
            if cells and re.fullmatch(r"\d{2,5}", cells[0].strip()) and len(cells) > 1 and re.search(r"[A-Za-z]{3}", cells[-1]):
                nic.append({"code": cells[0].strip(), "description": cells[-1].strip()})
    if nic:
        read.put("nic_codes", Hit(nic, conf))  # type: ignore[arg-type]  # list value, validated by the model
    return read


# ---------- Financial statements ----------

_FY_RANGE = re.compile(r"(?<!\d)(\d{4})\s*[-–/]\s*(\d{2})(?!\d)")
_FY_DATE = re.compile(r"\d{1,2}[./-]\d{1,2}[./-](\d{4})")
_FY_MARCH = re.compile(r"march[\s,.-]*(\d{4})", I)
_FIN_NUM = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
_UNIT_IN = re.compile(r"\bin\s+(?:rs\.?\s*|₹\s*)?(lakhs?|lacs?|crores?|crs?\b|thousands?|millions?|'000s?|000s)", I)
_UNIT_RUPEES = re.compile(r"\bin\s+(?:₹|rs\.?|inr|rupees)(?!\s*(?:lakh|lac|crore|thousand|million))", I)

FINANCIAL_ITEMS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern, I))
    for name, pattern in [
        ("total_equity_and_liabilities", r"total\s*equity\s*(?:and|&)\s*liabilities|total\s*liabilities\s*(?:and|&)\s*(?:equity|net\s*worth|shareholders)|total\s*capital\s*(?:and|&)\s*liabilities"),
        ("current_assets", r"total\s*current\s*assets"),
        ("current_liabilities", r"total\s*current\s*liabilities"),
        ("total_assets", r"total\s*assets"),
        ("total_liabilities", r"total\s*liabilities(?!\s*(?:and|&))"),
        ("net_worth", r"net\s*worth|total\s*equity(?!\s*(?:and|&))|shareholders'?\s*(?:funds|equity)|proprietor'?s?\s*(?:capital|funds)|partners'?\s*capital"),
        ("revenue", r"revenue\s*from\s*operations|net\s*sales|sales\s*\(net\)|\bturnover\b|^\W*sales\b"),
        ("other_income", r"other\s*income"),
        ("total_expenses", r"total\s*expenses?"),
        ("ebitda", r"\bebitda\b|operating\s*profit"),
        ("depreciation", r"depreciation"),
        ("interest_expense", r"finance\s*costs?|interest\s*expenses?|interest\s*and\s*finance|interest\s*paid"),
        ("profit_before_tax", r"profit(?:\s*/\s*\(?loss\)?)?\s*before\s*(?:exceptional\s*items\s*and\s*)?tax|\bpbt\b"),
        ("profit_after_tax", r"profit(?:\s*/\s*\(?loss\)?)?\s*(?:for\s*the\s*(?:year|period)|after\s*tax)|net\s*profit|\bpat\b"),
        ("long_term_borrowings", r"long[\s-]*term\s*borrowings?"),
        ("short_term_borrowings", r"short[\s-]*term\s*borrowings?"),
        ("trade_receivables", r"trade\s*receivables?|sundry\s*debtors"),
        ("trade_payables", r"trade\s*payables?|sundry\s*creditors"),
        ("inventory", r"inventor(?:y|ies)|stock[\s-]*in[\s-]*trade"),
        ("cash", r"cash\s*(?:and|&)\s*(?:cash|bank)\s*(?:equivalents|balances?)?"),
        ("principal_repayments", r"repayment\s*of\s*(?:long[\s-]*term\s*)?(?:borrowings?|loans?)|principal\s*repayments?"),
    ]
]


def _fy_ends(text: str) -> list[int]:
    found: list[tuple[int, int]] = []
    for m in _FY_RANGE.finditer(text):
        start, tail = int(m.group(1)), int(m.group(2))
        if (start + 1) % 100 == tail:
            found.append((m.start(), start + 1))
    found += [(m.start(), int(m.group(1))) for m in _FY_DATE.finditer(text)]
    found += [(m.start(), int(m.group(1))) for m in _FY_MARCH.finditer(text)]
    return [year for _, year in sorted(found)]


def financial_layout(views: list[PageView]) -> list[int]:
    """Financial-year end years of the statement's columns, left to right (first header line with two)."""
    for view in views:
        for line in view.lines:
            years = _fy_ends(line.text)
            distinct = list(dict.fromkeys(years))
            if len(distinct) >= 2:
                return distinct[:2]
    for view in views:
        for line in view.lines:
            if years := _fy_ends(line.text):
                return years[:1]
    return []


def _fy_label(end_year: int) -> str:
    return f"{end_year - 1}-{end_year % 100:02d}"


def _numbers(text: str) -> list[float]:
    values = []
    for t in _FIN_NUM.finditer(text):
        raw = t.group(0)
        if raw.startswith("(") and not raw.endswith(")"):
            raw += ")"
        if (v := parse_inr(raw.replace("(-", "(").strip())) is not None:
            values.append(v)
    return values


def read_financial_statements(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    layout = view.hints.get("layout") or financial_layout([view])
    cur_col, pri_col = 0, 1
    if len(layout) == 2:
        if layout[0] < layout[1]:
            cur_col, pri_col = 1, 0
            read.warnings.append("Financial statement columns are oldest-year first; the latest year was read from the second column")
        read.put("financial_year", Hit(_fy_label(max(layout)), 0.9, "from column headers"))
        read.put("prior_financial_year", Hit(_fy_label(min(layout)), 0.9, "from column headers"))
    elif len(layout) == 1:
        read.put("financial_year", Hit(_fy_label(layout[0]), 0.9, "from the statement date"))

    for line in lines:
        if m := _UNIT_IN.search(line.text):
            read.put("unit", Hit(m.group(1), line.confidence))
            break
    if "unit" not in read.fields:
        for line in lines:
            if _UNIT_RUPEES.search(line.text):
                read.put("unit", Hit("units", line.confidence))
                break

    whole = " ".join(l.text for l in lines)
    if re.search(r"\bunaudited\b|provisional", whole, I):
        read.put("audit_status", Hit("provisional", 0.85))
    elif re.search(r"independent\s*auditor|auditor'?s'?\s*report|\baudited\b|statutory\s*audit", whole, I):
        read.put("audit_status", Hit("audited", 0.85))
    elif re.search(r"certif(?:ied|icate)", whole, I) and re.search(r"chartered\s*accountant|\bCA\b", whole, I):
        read.put("audit_status", Hit("ca_certified", 0.8))

    for line in lines:
        if m := re.search(r"UDIN\s*(?:no\.?)?\s*[:\-]?\s*([0-9A-Za-z]{6,24})", line.text, I):
            read.put("udin", Hit(m.group(1), line.confidence))
        if m := re.match(r"^\W*(?:for\s+)?(?:m/s\.?\s*)?(.+?)[,\s]*chartered\s*accountants", line.text, I):
            firm = clean_value(m.group(1))
            if len(firm) >= 3 and not re.fullmatch(r"(?:the|a)", firm, I):
                read.put("auditor_firm", Hit(firm, line.confidence))
        if m := re.search(r"\bCA\.?\s+(?!certif)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})", line.text):
            read.put("auditor_name", Hit(m.group(1), line.confidence))
    read.put("auditor_name", after_label(lines, re.compile(r"auditor'?s?\s*name|name\s*of\s*(?:the\s*)?auditor|partner\s*name", I), ahead=0))

    has_note = any(re.search(r"\bnotes?\b", l.text, I) for l in lines[:40])
    seen: set[str] = set()
    for line in lines:
        for name, pattern in FINANCIAL_ITEMS:
            if name in seen:
                continue
            m = pattern.search(line.text)
            if not m:
                continue
            nums = _numbers(line.text[m.end():])
            if not nums:
                continue
            if has_note and len(nums) >= 2 and float(nums[0]).is_integer() and 0 < abs(nums[0]) <= 60 and (len(nums) == 3 or abs(nums[1]) > 60):
                nums = nums[1:]
            nums = nums[-2:]
            seen.add(name)
            columns = {0: nums[0], 1: nums[1]} if len(nums) == 2 else {0: nums[0]}
            if cur_col in columns:
                read.put(name, Hit(columns[cur_col], line.confidence))  # type: ignore[arg-type]
            if pri_col in columns:
                read.put(f"prior_{name}", Hit(columns[pri_col], line.confidence))  # type: ignore[arg-type]
            break
    return read


# ---------- Sanction letter ----------

_PCT = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")
_FD = re.compile(r"lien\s*(?:marked\s*)?(?:on|against|over)?\s*(?:the\s*)?(?:fixed\s*deposits?|fds?\b)|fd\s*lien|100\s*%\s*margin|margin\s*money|secured\s*(?:against|by)\s*(?:a\s*)?(?:fixed\s*deposits?|fds?\b)|against\s*(?:fixed\s*deposits?|fds?\b)", I)


def _mask_long_numbers(text: str) -> str:
    return re.sub(r"\d{8,}", lambda m: "X" * (len(m.group(0)) - 4) + m.group(0)[-4:], text)


def read_sanction_letter(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    read.put("lender_name", after_label(lines, re.compile(r"(?:lender|bank|nbfc|financier)\s*name|name\s*of\s*(?:the\s*)?(?:lender|bank|nbfc)|sanctioned\s*by", I), ahead=0))
    if "lender_name" not in read.fields:
        for line in lines[:8]:
            text = clean_value(line.text)
            if re.search(r"\b(?:bank|finance|nbfc|capital|financial)\b", text, I) and len(text) <= 60 and not re.search(r"dear|sanction|letter|to,|subject", text, I):
                read.put("lender_name", Hit(text, line.confidence * 0.9, "letterhead"))
                break
    read.put("facility_type", after_label(lines, re.compile(r"type\s*of\s*(?:the\s*)?facility|facility\s*type|nature\s*of\s*(?:the\s*)?facility|\bfacility\s*:|\bproduct\s*:", I), ahead=0, skip=re.compile(r"amount|limit", I)))
    read.put(
        "sanctioned_amount",
        _money_after(lines, re.compile(r"sanction(?:ed)?\s*(?:amount|limit)|facility\s*amount|loan\s*amount|limit\s*sanctioned|amount\s*sanctioned", I), skip=re.compile(r"\bdate\b", I)),
    )

    rate_re = re.compile(r"rate\s*of\s*interest|interest\s*rate|\broi\b", I)
    for line in lines:
        if rate_re.search(line.text):
            tail = line.text[rate_re.search(line.text).end():]
            current = re.search(r"(?:currently|presently|effective|current)\D{0,20}?(\d{1,2}(?:\.\d+)?)\s*%", tail, I)
            first = _PCT.search(tail)
            if current or first:
                read.put("interest_rate_pct", Hit((current or first).group(1), line.confidence))
                read.put("rate_type", Hit(tail, line.confidence))
                break
    read.put("apr_pct", after_label(lines, re.compile(r"\bAPR\b|annuali[sz]ed\s*percentage\s*rate|annual\s*percentage\s*rate", I), re.compile(r"\d{1,2}(?:\.\d+)?\s*%"), ahead=0))
    for line in lines:
        if m := re.search(r"tenure|tenor|repayment\s*period|loan\s*term|term\s*of\s*(?:the\s*)?loan", line.text, I):
            t = re.search(r"(\d+)\s*(months?|mths?|years?|yrs?)", line.text[m.end():], I)
            if t:
                months = int(t.group(1)) * (12 if t.group(2).lower().startswith(("y")) else 1)
                read.put("tenure_months", Hit(str(months), line.confidence))
                break
    read.put("emi_amount", _money_after(lines, re.compile(r"\bEMI\b|equated\s*monthly|monthly\s*instal(?:l)?ment", I), skip=re.compile(r"date|day|due|bounce|penal|charge|first|start", I)))
    for line in lines:
        if m := re.search(r"processing\s*fees?", line.text, I):
            tail = line.text[m.end():]
            if p := _PCT.search(tail):
                read.put("processing_fee_pct", Hit(p.group(1), line.confidence))
            amount = _money_after([Line(tail, line.confidence)], re.compile(r"^"), minimum=100)
            if amount:
                read.put("processing_fee", amount)
            break
    security = after_label(lines, re.compile(r"^\W*(?:security|collateral)(?:\s*offered|\s*details)?\s*:", I), ahead=1, stop=_NUMBERED, skip=re.compile(r"interest|rate", I))
    if security:
        masked = Hit(_mask_long_numbers(security.value), security.confidence)
        read.put("security", masked)
    whole = "\n".join(l.text for l in lines)
    if _FD.search(whole):
        read.put("fd_lien_or_margin", Hit("yes", 0.9))
    elif security:
        read.put("fd_lien_or_margin", Hit("no", 0.7, "security stated, no FD lien or margin mentioned"))
    read.put("sanction_date", after_label(lines, re.compile(r"date\s*of\s*sanction|sanction(?:ed)?\s*date|sanctioned\s*on|letter\s*date", I), _DATE_VALUE, ahead=1))
    if "sanction_date" not in read.fields:
        read.put("sanction_date", after_label(lines, re.compile(r"^\W*date\b", I), _DATE_VALUE, ahead=0))
    read.put("validity_date", after_label(lines, re.compile(r"valid(?:ity)?\s*(?:till|until|upto|up\s*to|date)|validity", I), _DATE_VALUE, ahead=1))
    for line in lines:
        if re.search(r"cooling[\s-]*off", line.text, I):
            if m := re.search(r"(\d+)\s*(?:calendar\s*)?days?", line.text, I):
                read.put("cooling_off_days", Hit(m.group(1), line.confidence))
                break
    return read


# ---------- Settlement report ----------

_PII_COLUMN = re.compile(r"(?:^|[\s_])id$|\bid\b|_id\b|vpa|upi\s*id|payer|customer|cardholder|card|mobile|phone|msisdn|e-?mail|\bname\b|account\s*(?:no|number)|a/c|\bpan\b|aadhaar|utr|rrn|\bref", I)
_SETTLEMENT_COLUMNS = [
    ("date", re.compile(r"date|settled\s*on", I)),
    ("gross", re.compile(r"gross|total\s*(?:amount|sales|collections?)|sales?|collections?|transaction\s*amount|txn\s*amount|^amount", I)),
    ("net", re.compile(r"net|settled\s*amount|payout|amount\s*settled|credited|settlement\s*amount", I)),
    ("fees", re.compile(r"fees?|mdr|commission|charges?|deductions?|gst|tax|tds", I)),
    ("count", re.compile(r"count|no\.?\s*of|txns?|transactions?|orders?", I)),
    ("mode", re.compile(r"mode|method|channel|type|instrument", I)),
]


def read_settlement_report(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    read.put("provider", after_label(lines, re.compile(r"(?:payment\s*)?(?:provider|aggregator|acquirer|gateway|processor)(?:\s*name)?", I), ahead=0))
    for line in lines:
        if m := re.search(r"(?:merchant|mid)\s*(?:id|code|no\.?)?\s*[:#-]\s*([A-Za-z0-9]{4,24})", line.text, I):
            digits = re.sub(r"\D", "", m.group(1))
            if len(digits) >= 4:
                read.put("merchant_id_last4", Hit(digits[-4:], line.confidence))  # only the last 4 digits leave the reader
            break
    for line in lines:
        if re.search(r"period|from|report", line.text, I) and (m := _PERIOD.search(line.text)):
            read.put("period_from", Hit(m.group(1), line.confidence))
            read.put("period_to", Hit(m.group(2), line.confidence))
            break
    read.rows.extend(_settlement_rows(view))
    return read


def _settlement_rows(view: PageView) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in view.tables:
        cols: dict[str, list[int]] = {}
        start = None
        for r, header in enumerate(table):
            found: dict[str, list[int]] = {}
            for j, cell in enumerate(header):
                low = cell.strip().lower()
                if not low or _PII_COLUMN.search(low):
                    continue  # third-party personal data: never read
                for name, pattern in _SETTLEMENT_COLUMNS:
                    if pattern.search(low):
                        found.setdefault(name, []).append(j)
                        break
            if "date" in found and ("gross" in found or "net" in found):
                cols, start = found, r
                break
        if start is None:
            continue

        def cell(cells: list[str], name: str, k: int = 0) -> str:
            idx = cols.get(name, [])
            return cells[idx[k]].strip() if len(idx) > k and idx[k] < len(cells) else ""

        for cells in table[start + 1 :]:
            if parse_date(cell(cells, "date")) is None:
                continue
            gross, net = parse_inr(cell(cells, "gross")), parse_inr(cell(cells, "net"))
            fee_values = [v for k in range(len(cols.get("fees", []))) if (v := parse_inr(cell(cells, "fees", k))) is not None]
            fees = round(sum(abs(v) for v in fee_values), 2) if fee_values else None
            if gross is None and net is not None and fees is not None:
                gross = round(net + fees, 2)
            if gross is None:
                continue
            row: dict[str, Any] = {"date": cell(cells, "date"), "gross_amount": gross, "_confidence": 0.95}
            if fees is not None:
                row["fees"] = fees
            if net is not None:
                row["net_settled"] = net
            if (count := cell(cells, "count")) and re.fullmatch(r"[\d,]+", count):
                row["txn_count"] = count
            if mode := cell(cells, "mode"):
                row["mode"] = mode
            rows.append(row)
    return rows
