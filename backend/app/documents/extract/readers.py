"""Text-pass readers: regex + label proximity over one page's ordered lines.

A reader returns raw strings (Hits); it never validates. The extractor runs
every Hit through app.documents.extract.schemas.validate_field, the same as VLM values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.documents.extract.common import (
    DATE_PATTERN,
    DATE_RE,
    MONTHS,
    GSTIN_RE,
    PAN_RE,
    Hit,
    Line,
    PageView,
    after_label,
    clean_value,
    gstin_valid,
    parse_date,
    parse_inr,
    repair_gstin,
    repair_pan,
)

I = re.IGNORECASE


@dataclass
class PageRead:
    fields: dict[str, Hit] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def put(self, name: str, hit: Hit | None) -> None:
        if hit is not None and name not in self.fields:
            self.fields[name] = hit


_DATE_VALUE = re.compile(DATE_PATTERN, I)
_PERSON = re.compile(r"[A-Za-z][A-Za-z .']*[A-Za-z.]")
_NUMBER_TOKEN = re.compile(r"(?<![\w.])-?(?:₹|rs\.?)?\s*\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?(?![\d,])|(?<![\w.,-])-?\d+(?:\.\d{1,2})?(?![\d,]|-\d)", I)


def _token_search(lines: list[Line], pattern: re.Pattern[str]) -> Hit | None:
    for line in lines:
        if m := pattern.search(line.text.upper()):
            return Hit(m.group(0), line.confidence)
    return None


def _amount_after(lines: list[Line], label: re.Pattern[str]) -> Hit | None:
    """Last number on the label's line (after the label), else on the next line. Schedule
    numbers like '(5+6)' before the amount are skipped because the amount is printed last."""
    for i, line in enumerate(lines):
        m = label.search(line.text)
        if not m:
            continue
        for text, conf in ((line.text[m.end():], line.confidence), (lines[i + 1].text if i + 1 < len(lines) else "", line.confidence)):
            text = re.sub(r"\([^)]*\)", " ", text)
            tokens = [t.group(0) for t in _NUMBER_TOKEN.finditer(text)]
            tokens = [t for t in tokens if parse_inr(t) is not None]
            if tokens:
                return Hit(tokens[-1].strip(), conf)
    return None


# ---------- PAN card ----------

_PAN_TOKEN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_PAN_LOOSE = re.compile(r"\b[A-Z0-9]{10}\b")
_NAME_LABEL = re.compile(r"(?<!father's )(?<!fathers )(?<!father )(?<!bank )(?<!branch )\bname\b(?!\s*of\b)", I)
_FATHER_LABEL = re.compile(r"father'?s?\s*name|पिता", I)
_DOB_LABEL = re.compile(r"date\s*of\s*birth|\bd\.?o\.?b\b|जन्म\s*(?:की\s*)?तिथि|जन्म\s*की\s*तारीख", I)
_PAN_STOP = re.compile(r"father|date of birth|signature|permanent account|हस्ताक्षर|\d{2}/\d{2}/\d{4}", I)
_PAN_HEADER = re.compile(r"income\s*tax|govt|government|permanent|account|number|card|भारत|आयकर", I)


def read_pan_card(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    if hit := _token_search(lines, _PAN_TOKEN):
        read.put("pan", hit)
    else:
        for line in lines:
            for m in _PAN_LOOSE.finditer(line.text.upper()):
                fixed = repair_pan(m.group(0))
                if fixed != m.group(0) and PAN_RE.match(fixed) and re.search(r"\d", m.group(0)):
                    read.put("pan", Hit(fixed, min(line.confidence, 0.6), f"OCR letter/digit swaps corrected from {m.group(0)}"))
                    break
    read.put("father_name", after_label(lines, _FATHER_LABEL, _PERSON, stop=_PAN_STOP))
    read.put("name", after_label(lines, _NAME_LABEL, _PERSON, stop=_PAN_STOP))
    read.put("dob", after_label(lines, _DOB_LABEL, _DATE_VALUE))
    if "name" not in read.fields:
        # Old-format card: unlabelled NAME then FATHER'S NAME lines under the header, then DOB.
        names = [l for l in lines if re.fullmatch(r"[A-Z][A-Z .']{2,}", clean_value(l.text)) and not _PAN_HEADER.search(l.text)]
        if names:
            read.put("name", Hit(clean_value(names[0].text), names[0].confidence * 0.8, "unlabelled old-format card"))
        if len(names) > 1:
            read.put("father_name", Hit(clean_value(names[1].text), names[1].confidence * 0.8, "unlabelled old-format card"))
    if "dob" not in read.fields:
        for line in lines:
            if m := DATE_RE.search(line.text):
                read.put("dob", Hit(m.group(0), line.confidence * 0.9))
                break
    return read


# ---------- Aadhaar ----------

_LAST4 = re.compile(r"X{4}\s*X{4}\s*(\d{4})\b", I)
_YOB_LABEL = re.compile(r"year\s*of\s*birth|\byob\b|जन्म\s*वर्ष", I)
_GENDER = re.compile(r"\b(female|male|transgender)\b|महिला|पुरुष", I)
_ADDRESS_LABEL = re.compile(r"\baddress\b|पता", I)
_PIN = re.compile(r"(?<!\d)[1-9]\d{5}(?!\d)")
_AADHAAR_HEADER = re.compile(r"government|india|aadhaar|aadhar|uidai|enrol|issue|download|unique|authority|help|www|vid", I)


def read_aadhaar(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    for line in lines:
        if m := _LAST4.search(line.text):
            read.put("aadhaar_last4", Hit(m.group(1), line.confidence))
            break
    dob = after_label(lines, _DOB_LABEL, _DATE_VALUE, ahead=1)
    read.put("dob", dob)
    yob = after_label(lines, _YOB_LABEL, re.compile(r"(?:19|20)\d{2}"), ahead=1)
    read.put("year_of_birth", yob)
    for line in lines:
        if m := _GENDER.search(line.text):
            read.put("gender", Hit(m.group(0), line.confidence))
            break
    read.put("name", after_label(lines, _NAME_LABEL, _PERSON, ahead=1, stop=_DOB_LABEL))
    if "name" not in read.fields:
        # Front side: the English name is the Latin-script line just above the DOB/YOB line.
        anchor = next((i for i, l in enumerate(lines) if _DOB_LABEL.search(l.text) or _YOB_LABEL.search(l.text)), None)
        if anchor is not None:
            for line in reversed(lines[max(0, anchor - 3) : anchor]):
                text = clean_value(line.text)
                if re.fullmatch(r"[A-Za-z][A-Za-z .']+", text) and not _AADHAAR_HEADER.search(text):
                    read.put("name", Hit(text, line.confidence * 0.9, "line above date of birth"))
                    break
    for i, line in enumerate(lines):
        m = _ADDRESS_LABEL.search(line.text)
        if not m:
            continue
        parts, conf = [clean_value(line.text[m.end():])], line.confidence
        for nxt in lines[i + 1 : i + 7]:
            if _PIN.search(parts[-1] or "") or _LAST4.search(nxt.text) or _AADHAAR_HEADER.search(nxt.text):
                break
            parts.append(clean_value(nxt.text))
            conf = min(conf, nxt.confidence)
        address = ", ".join(p.strip(", ") for p in parts if p)
        if address:
            read.put("address", Hit(address, conf))
            if pins := _PIN.findall(address):
                read.put("pincode", Hit(pins[-1], conf))
        break
    return read


# ---------- GST REG-06 ----------

_GSTIN_TOKEN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
_GSTIN_LOOSE = re.compile(r"\b[0-9A-Z]{15}\b")
_NUMBERED = re.compile(r"^\s*\(?\d{1,2}[.)]\s|^\s*\(?[a-h]\)\s", I)


def _gstin(lines: list[Line]) -> Hit | None:
    """Prefer a GSTIN whose check character verifies; else a positional OCR repair that verifies;
    else the first well-formed one (it will fail validation and be reported, never kept)."""
    loose: Hit | None = None
    for line in lines:
        for m in _GSTIN_TOKEN.finditer(line.text.upper()):
            if gstin_valid(m.group(0)):
                return Hit(m.group(0), line.confidence)
            loose = loose or Hit(m.group(0), line.confidence)
    for line in lines:
        for m in _GSTIN_LOOSE.finditer(line.text.upper()):
            fixed = repair_gstin(m.group(0))
            if fixed != m.group(0) and gstin_valid(fixed):
                return Hit(fixed, min(line.confidence, 0.75), f"OCR letter/digit swaps corrected from {m.group(0)}; check character verifies")
    return loose


def _multiline_after(lines: list[Line], label: re.Pattern[str], max_lines: int = 4) -> Hit | None:
    for i, line in enumerate(lines):
        m = label.search(line.text)
        if not m:
            continue
        parts, conf = [clean_value(line.text[m.end():])], line.confidence
        for nxt in lines[i + 1 : i + 1 + max_lines]:
            if _NUMBERED.search(nxt.text) or re.search(r"date of|type of|particulars", nxt.text, I):
                break
            parts.append(clean_value(nxt.text))
            conf = min(conf, nxt.confidence)
        text = ", ".join(p.strip(", ") for p in parts if p)
        return Hit(text, conf) if text else None
    return None


def read_gst_certificate(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    stop = _NUMBERED
    read.put("gstin", _gstin(lines))
    read.put("legal_name", after_label(lines, re.compile(r"legal\s*name(?:\s*of\s*business)?", I), stop=stop, ahead=1))
    trade = after_label(lines, re.compile(r"(?<!additional )trade\s*name(?:,?\s*if\s*any)?", I), stop=stop, ahead=1)
    if trade and not re.fullmatch(r"(?:na|n/a|nil|-+)", trade.value, I):
        read.put("trade_name", trade)
    read.put("constitution_of_business", after_label(lines, re.compile(r"constitution\s*of\s*business", I), stop=stop, ahead=1))
    address = _multiline_after(lines, re.compile(r"address\s*of\s*principal\s*place\s*of\s*business", I))
    read.put("address", address)
    if address and (pins := _PIN.findall(address.value)):
        read.put("pincode", Hit(pins[-1], address.confidence))
    read.put("date_of_liability", after_label(lines, re.compile(r"date\s*of\s*liability", I), _DATE_VALUE, ahead=1))
    read.put("validity_from", after_label(lines, re.compile(r"(?:date|period)\s*of\s*validity\s*:?\s*(?:from)?", I), _DATE_VALUE, ahead=1))
    read.put("type_of_registration", after_label(lines, re.compile(r"type\s*of\s*registration", I), stop=stop, ahead=1))
    issue = after_label(lines, re.compile(r"date\s*of\s*issue(?:\s*of\s*certificate)?", I), _DATE_VALUE, ahead=1)
    # Registration date: start of validity, else date of liability, else issue date (in that order).
    for source, hit in (("date of validity (from)", read.fields.get("validity_from")), ("date of liability", read.fields.get("date_of_liability")), ("certificate issue date", issue)):
        if hit:
            read.put("registration_date", Hit(hit.value, hit.confidence, f"from {source}"))
            break
    return read


# ---------- GSTR-3B ----------

_MONTH_WORD = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
_FY = re.compile(r"(?:financial\s*)?year\s*:?\s*(\d{4}\s*-\s*\d{2,4})", I)
_PERIOD_NAMED = re.compile(rf"(?:tax\s*)?period\s*:?\s*({_MONTH_WORD})\b[\s,-]*(\d{{4}})?", I)
_PERIOD_NUMERIC = re.compile(r"(?:tax\s*)?period\s*:?\s*(\d{1,2})\s*[/-]\s*(\d{4})", I)
_ROW_A = re.compile(r"^\W*\(?a\)?\s*outward\s*taxable\s*supplies", I)


def _period_key(month: int, year: int | None, fy_start: int | None) -> str | None:
    if year is None:
        if fy_start is None:
            return None
        year = fy_start if month >= 4 else fy_start + 1
    return f"{year:04d}-{month:02d}"


def _numbers(text: str) -> list[str]:
    return [t.group(0).strip() for t in _NUMBER_TOKEN.finditer(text) if parse_inr(t.group(0)) is not None]


def read_gstr_3b(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    read.put("gstin", _gstin(lines))
    read.put("legal_name", after_label(lines, re.compile(r"legal\s*name(?:\s*of\s*the\s*registered\s*person)?", I), ahead=1, stop=_NUMBERED))
    fy_start: int | None = None
    period: str | None = None
    for i, line in enumerate(lines):
        text = line.text
        if m := _FY.search(text):
            read.put("financial_year", Hit(m.group(1).replace(" ", ""), line.confidence))
            fy_start = int(m.group(1)[:4])
        if m := _PERIOD_NUMERIC.search(text):
            period = _period_key(int(m[1]), int(m[2]), fy_start)
        elif m := _PERIOD_NAMED.search(text):
            period = _period_key(MONTHS[m[1][:3].lower()], int(m[2]) if m[2] else None, fy_start)
        if _ROW_A.search(text):
            tail = text[text.rfind(")") + 1 :] if ")" in text[5:] else text[_ROW_A.search(text).end() :]
            values = _numbers(tail)
            if not values and i + 1 < len(lines):
                values = _numbers(lines[i + 1].text)
            if not values:
                read.warnings.append(f"Page {view.index + 1}: GSTR-3B row 3.1(a) found but no amounts could be read")
                continue
            if period is None:
                read.warnings.append(f"Page {view.index + 1}: GSTR-3B row 3.1(a) found but its return period could not be read")
                continue
            row = {"period": period, "taxable_outward_value": values[0], "_confidence": line.confidence}
            for key, value in zip(("igst", "cgst", "sgst", "cess"), values[1:]):
                row[key] = value
            read.rows.append(row)
    read.rows.extend(_gstr3b_tables(view))
    return read


def _gstr3b_tables(view: PageView) -> list[dict[str, Any]]:
    """Spreadsheet summaries: a header row with a period/month column and a taxable value column."""
    rows: list[dict[str, Any]] = []
    for table in view.tables:
        cols: dict[str, int] = {}
        for r, header in enumerate(table):
            low = [c.lower() for c in header]
            for j, c in enumerate(low):
                if re.search(r"period|month", c):
                    cols.setdefault("period", j)
                elif re.search(r"taxable", c):
                    cols.setdefault("taxable_outward_value", j)
                elif re.search(r"integrated|igst", c):
                    cols.setdefault("igst", j)
                elif re.search(r"central|cgst", c):
                    cols.setdefault("cgst", j)
                elif re.search(r"state|sgst|utgst", c):
                    cols.setdefault("sgst", j)
                elif re.search(r"cess", c):
                    cols.setdefault("cess", j)
            if {"period", "taxable_outward_value"} <= cols.keys():
                for cells in table[r + 1 :]:
                    raw = cells[cols["period"]] if cols["period"] < len(cells) else ""
                    key = _table_period(raw)
                    if key is None:
                        continue
                    row = {"period": key, "_confidence": 0.95}
                    for name, j in cols.items():
                        if name != "period" and j < len(cells):
                            row[name] = cells[j]
                    rows.append(row)
                break
            cols = {}
    return rows


def _table_period(raw: str) -> str | None:
    raw = raw.strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", raw):
        return f"{int(m[1]):04d}-{int(m[2]):02d}"
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{4})", raw):
        return f"{int(m[2]):04d}-{int(m[1]):02d}"
    if m := re.fullmatch(rf"({_MONTH_WORD})[\s,'-]*(\d{{2}}|\d{{4}})", raw, I):
        year = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
        return f"{year:04d}-{MONTHS[m[1][:3].lower()]:02d}"
    if d := parse_date(raw):
        return f"{d.year:04d}-{d.month:02d}"
    return None


# ---------- ITR ----------

_ITR_FORM_LABEL = re.compile(r"form\s*(?:no\.?|number|type)\s*:?", I)
_ACK_LABEL = re.compile(r"acknowledge?ment\s*(?:no\.?|number)", I)


def read_itr(view: PageView) -> PageRead:
    read = PageRead()
    lines = view.lines
    read.put("assessment_year", after_label(lines, re.compile(r"assessment\s*year", I), re.compile(r"\d{4}\s*-\s*\d{2,4}"), ahead=1))
    read.put("pan", after_label(lines, re.compile(r"\bPAN\b"), _PAN_TOKEN, ahead=1) or _token_search(lines, _PAN_TOKEN))
    read.put("name", after_label(lines, _NAME_LABEL, _PERSON, ahead=1, stop=re.compile(r"\bPAN\b|address|form", I)))
    read.put("form_type", after_label(lines, _ITR_FORM_LABEL, re.compile(r"ITR\s*-?\s*[1-7]\b", I), ahead=1))
    if "form_type" not in read.fields:
        for line in lines:
            forms = re.findall(r"ITR\s*-?\s*[1-7]\b", line.text, I)
            if len(forms) == 1 and re.search(r"filed|form", line.text, I):
                read.put("form_type", Hit(forms[0], line.confidence))
                break
    read.put("acknowledgement_number", after_label(lines, _ACK_LABEL, re.compile(r"(?<!\d)\d{15}(?!\d)"), ahead=1))
    read.put("filing_date", after_label(lines, re.compile(r"date\s*of\s*filing|filed\s*on|e-?filing\s*date", I), _DATE_VALUE, ahead=1))
    read.put("gross_total_income", _amount_after(lines, re.compile(r"gross\s*total\s*income", I)))
    read.put("total_income", _amount_after(lines, re.compile(r"(?<!gross )(?<!gross)\btotal\s*income", I)))
    read.put("tax_payable", _amount_after(lines, re.compile(r"(?:net\s*)?tax\s*payable", I)))
    read.put("business_turnover", _amount_after(lines, re.compile(r"gross\s*(?:turnover|receipts)|total\s*turnover", I)))
    return read
