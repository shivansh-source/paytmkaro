"""Deterministic building blocks: Indian numbers, dates, identifiers, and page lines.

Everything here is pure code, so OCR values and VLM values go through exactly
the same checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from statistics import median

from app.documents.models import FieldSource, Page, TextSource
from app.documents.privacy import mask_aadhaar_text

# ---------- Numbers ----------

_NUMBER = re.compile(r"(?<![\w.])(-?)(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d{1,2})?(?![\d,])", re.IGNORECASE)
# A currency prefix may be glued to the digits ("Rs658,000.00", "INR6,58,000.00"); it is part of the token so
# the digits after it are never read on their own (the "000.00" tail of "658,000.00" is not an amount).
_AMOUNT_TOKEN = re.compile(
    r"(?<![\w/.,-])(?:-?(?:₹|rs\.?|inr)\s?)?-?(?:\d{1,3}(?:,\d{2,3})*\.\d{2}|\d+\.\d{2})(?:\s?(?:cr|dr)\b)?(?!\d)",
    re.IGNORECASE,
)


def parse_inr(value: object) -> float | None:
    """'₹1,50,000.00' -> 150000.0; '(2,500.00)' and '2,500.00 Dr' -> -2500.0. None if not a number."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "—", "nil", "NIL", "Nil"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    suffix = re.search(r"\s*\b(dr|cr)\.?\s*$", text, re.IGNORECASE)
    if suffix:
        negative = negative or suffix.group(1).lower() == "dr"
        text = text[: suffix.start()]
    text = re.sub(r"\s*/-\s*$", "", text.strip())  # "Rs.6,58,000/-"
    text = re.sub(r"^(-?)\s*(?:₹|rs\.?|inr)\s*", r"\1", text, flags=re.IGNORECASE).replace(" ", "")
    if text.startswith("-"):
        negative, text = True, text[1:]
    if not re.fullmatch(r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?", text):
        return None
    amount = float(text.replace(",", ""))
    return -amount if negative else amount


def money(amount: float) -> str:
    """Indian grouping with paise: 150000.5 -> ₹1,50,000.50."""
    sign = "-" if amount < 0 else ""
    rupees, paise = divmod(round(abs(amount) * 100), 100)
    digits = str(rupees)
    head, groups = digits[:-3], [digits[-3:]]
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return f"{sign}₹{','.join(groups)}.{paise:02d}"


def amount_tokens(text: str) -> list[re.Match[str]]:
    """Money-looking tokens with paise (1,50,000.00 / 2500.00 Cr); integers are refs/cheque numbers, not amounts."""
    return list(_AMOUNT_TOKEN.finditer(text))


# ---------- Dates ----------

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_NAMES = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
DATE_PATTERN = (
    r"\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    rf"|\d{{1,2}}[\s-]*(?:{_MONTH_NAMES})[\s,-]*\d{{2,4}}"
)
DATE_RE = re.compile(rf"(?<!\d)(?:{DATE_PATTERN})(?!\d)", re.IGNORECASE)


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if len(y) == 2 else n


def parse_date(value: object) -> date | None:
    """dd/mm/yyyy, dd-mm-yy, dd-Mon-yyyy, 15 August 1985, ISO. Indian day-first order; None if invalid."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})", text):
            return date(_year(m[3]), int(m[2]), int(m[1]))
        if m := re.fullmatch(rf"(\d{{1,2}})[\s-]*({_MONTH_NAMES})[\s,-]*(\d{{4}}|\d{{2}})", text, re.IGNORECASE):
            return date(_year(m[3]), MONTHS[m[2][:3].lower()], int(m[1]))
    except ValueError:
        return None
    return None


def find_date(text: str) -> date | None:
    for m in DATE_RE.finditer(text):
        if parsed := parse_date(m.group(0)):
            return parsed
    return None


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_between(start: date, end: date) -> int:
    """Whole months from start to end: 2025-08-01 -> 2026-10-31 is 14 (a month counts once its day is reached)."""
    n = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        n -= 1
    return max(n, 0)


def month_range(start: date, end: date) -> list[str]:
    keys, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return keys


def month_label(key: str) -> str:
    y, m = key.split("-")
    return f"{list(MONTHS)[int(m) - 1].title()} {y}"


# ---------- Identifiers ----------

PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

PAN_HOLDER_TYPES = {
    "P": "individual",
    "C": "company",
    "H": "huf",
    "F": "firm",  # partnership firms and LLPs
    "A": "aop",
    "T": "trust",
    "B": "boi",
    "L": "local_authority",
    "J": "artificial_juridical_person",
    "G": "government",
}

GST_STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh (old)", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}


def gstin_check_char(first14: str) -> str:
    """Official GSTIN check character: mod-36 Luhn variant over the first 14 characters."""
    total = 0
    for i, ch in enumerate(first14):
        product = _GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_valid(gstin: str) -> bool:
    return bool(GSTIN_RE.match(gstin)) and gstin[:2] in GST_STATES and gstin_check_char(gstin[:14]) == gstin[14]


# OCR confusions, applied only where the position's character class is fixed.
_TO_DIGIT = str.maketrans({"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G"})


def repair_pan(raw: str) -> str:
    """Fix letter/digit OCR swaps by position (AAAAA9999A). The caller marks the result low-confidence."""
    s = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if len(s) != 10:
        return s
    return s[:5].translate(_TO_ALPHA) + s[5:9].translate(_TO_DIGIT) + s[9].translate(_TO_ALPHA)


def repair_gstin(raw: str) -> str:
    """Positional repair; only useful because the check character then has to agree."""
    s = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if len(s) != 15:
        return s
    return s[:2].translate(_TO_DIGIT) + repair_pan(s[2:12]) + s[12:]


# ---------- Constitution ----------

_CONSTITUTIONS = [
    (r"limited liability partnership|\bllp\b", "llp"),
    (r"one person company|\bopc\b", "opc"),
    (r"private limited|pvt\.? ?ltd|private ltd", "pvt_ltd"),
    (r"public limited|public ltd|public sector undertaking", "public_ltd"),
    (r"partnership", "partnership"),
    (r"propriet", "proprietorship"),
    (r"hindu undivided family|\bhuf\b", "huf"),
    (r"\btrust\b", "trust"),
    (r"society|club", "society"),
    (r"association of persons|body of individuals|\baop\b|\bboi\b", "aop"),
    (r"government|local authority|statutory body", "government"),
    (r"foreign company", "foreign_company"),
    (r"unlimited company", "unlimited_company"),
]
CONSTITUTIONS = sorted({code for _, code in _CONSTITUTIONS})


def normalize_constitution(text: str) -> str | None:
    """GST 'Constitution of Business' wording -> MatchInput.constitution vocabulary."""
    low = str(text).lower()
    if low.strip() in CONSTITUTIONS:
        return low.strip()
    for pattern, code in _CONSTITUTIONS:
        if re.search(pattern, low):
            return code
    return None


# ---------- Names ----------

_TITLES = re.compile(r"\b(mr|mrs|ms|miss|shri|sri|smt|kumari|dr|m/s|ms\.)\b\.?", re.IGNORECASE)


def normalize_name(name: str) -> str:
    text = _TITLES.sub(" ", str(name).replace("M/S", " ").replace("m/s", " "))
    text = re.sub(r"[^A-Za-z\u0900-\u0DFF ]", " ", text)
    return " ".join(text.upper().split())


# ---------- Page lines ----------


@dataclass(frozen=True)
class Line:
    text: str
    confidence: float


@dataclass(frozen=True)
class PageView:
    """A page as ordered text lines with confidences, ready for label-proximity parsing."""

    index: int
    source: FieldSource
    lines: list[Line]
    tables: list[list[list[str]]]
    # Document-level facts found by a pre-scan (e.g. financial statement column order).
    hints: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


NATIVE_CONFIDENCE = 0.95
OCR_TEXT_CONFIDENCE = 0.8  # OCR text without per-line scores


def _ocr_rows(page: Page) -> list[Line]:
    """Group OCR boxes into visual rows, left to right, so 'Name' and its value printed side by side
    become one line. A box joins a row when its centre is within half a median box height of the
    row's, OR when it shares at least 40% of the shorter box's height with a box already in the row
    (table cells: labels are centred in the row, values top-aligned, so their centres can be a full
    line apart while the boxes still overlap). A box never joins a row that already has a box in the
    same column (the second line of a wrapped value starts its own row). Row confidence is the
    weakest box."""
    boxes = sorted(page.ocr_lines, key=lambda l: ((l.bbox[1] + l.bbox[3]) / 2, l.bbox[0]))
    height = median(max(l.bbox[3] - l.bbox[1], 1) for l in boxes)
    tolerance = height / 2
    rows: list[list] = []  # [centre of the first box, members]

    def overlaps(a, b) -> bool:
        shorter = max(min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1]), 1)
        return min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1]) >= 0.4 * shorter

    def same_column(a, b) -> bool:
        narrower = max(min(a.bbox[2] - a.bbox[0], b.bbox[2] - b.bbox[0]), 1)
        return min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0]) > 0.3 * narrower

    for box in boxes:
        centre = (box.bbox[1] + box.bbox[3]) / 2
        target = None
        for row in reversed(rows[-6:]):  # only the last few rows can still be on the same line
            near = abs(centre - row[0]) <= tolerance or any(overlaps(box, m) for m in row[1])
            if near and not any(same_column(box, m) for m in row[1]):
                target = row
                break
        if target is not None:
            target[1].append(box)
        else:
            rows.append([centre, [box]])

    # A wrapped value is stacked in its cell and its label is centred beside the stack, so the label can
    # share a row with the stack's second line only: the first line then sits alone one row above. Pull a
    # lone box into the next row when that row has a label to its left and the box's own column directly
    # below it; the cell's lines then read in order after the label.
    merged: list[list] = []
    for row in rows:
        if merged and len(merged[-1][1]) == 1 and len(row[1]) >= 2:
            above = merged[-1][1][0]
            label = min(row[1], key=lambda l: l.bbox[0])
            below = [m for m in row[1] if m is not label and same_column(above, m) and -0.5 * height <= m.bbox[1] - above.bbox[3] <= 0.5 * height]
            beside = label.bbox[2] <= above.bbox[0] + 0.1 * (above.bbox[2] - above.bbox[0]) and not same_column(above, label)
            close = above.bbox[3] >= label.bbox[1] - 0.3 * height  # the stack's first line ends where the label starts
            if below and beside and close:
                merged.pop()
                row[1].append(above)
        merged.append(row)

    lines = []
    for _, members in merged:
        members.sort(key=lambda l: l.bbox[0])
        # Boxes stacked in one column read top to bottom, whatever their tiny left-edge differences.
        for i in range(len(members) - 1):
            for j in range(i + 1, len(members)):
                if same_column(members[i], members[j]) and members[j].bbox[1] < members[i].bbox[1]:
                    members[i], members[j] = members[j], members[i]
        lines.append(Line("  ".join(m.text for m in members), min(m.confidence for m in members)))
    return lines


def page_view(page: Page) -> PageView:
    """Lines from OCR boxes when present, else from the page text; Aadhaar masked again defensively."""
    context = page.text or " ".join(l.text for l in page.ocr_lines)
    if page.ocr_lines:
        lines, source = _ocr_rows(page), FieldSource.OCR
    else:
        conf = NATIVE_CONFIDENCE if page.text_source != TextSource.OCR else OCR_TEXT_CONFIDENCE
        lines = [Line(t, conf) for t in page.text.splitlines()]
        source = FieldSource.OCR if page.text_source == TextSource.OCR else FieldSource.TEXT_LAYER
    lines = [Line(mask_aadhaar_text(l.text, context).strip(), l.confidence) for l in lines]
    return PageView(page.index, source, [l for l in lines if l.text], page.tables)


_DEVANAGARI = re.compile(r"[\u0900-\u097F]+")


def clean_value(text: str) -> str:
    """Strip bilingual label noise ('/ नाम'), separators and extra spaces around a value."""
    text = _DEVANAGARI.sub(" ", text)
    text = re.sub(r"^[\s:/|.\-–'`‘’\"“”]+|[\s:/|\-–`‘’\"“”]+$", "", text)
    return " ".join(text.split())


@dataclass(frozen=True)
class Hit:
    """A raw value read near a label, with the line confidence it came from."""

    value: str
    confidence: float
    note: str | None = None


def after_label(
    lines: list[Line],
    label: re.Pattern[str],
    value: re.Pattern[str] | None = None,
    *,
    ahead: int = 2,
    stop: re.Pattern[str] | None = None,
    skip: re.Pattern[str] | None = None,
) -> Hit | None:
    """Value on the label's line (after the label) or on one of the next `ahead` lines.
    `value` constrains what counts; `stop` marks lines that are other labels (never a value)."""
    for i, line in enumerate(lines):
        m = label.search(line.text)
        if not m or (skip and skip.search(line.text)):
            continue
        rest = line.text[m.end():]
        while again := label.search(rest):  # bilingual label: 'पिता का नाम / Father's Name'
            rest = rest[again.end():]
        candidates = [(clean_value(rest), line.confidence)]
        for nxt in lines[i + 1 : i + 1 + ahead]:
            if stop and stop.search(nxt.text):
                break
            candidates.append((clean_value(nxt.text), min(line.confidence, nxt.confidence)))
        for text, conf in candidates:
            if not text:
                continue
            if value is None:
                return Hit(text, conf)
            if vm := value.search(text):
                return Hit(vm.group(0), conf)
    return None
