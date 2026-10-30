"""Declarative evidence tables: what each document type looks like.

Two kinds of evidence, both scored once per page per entry:
- KEYWORDS: phrases (English + Hindi variants). Long phrases are OCR-tolerant
  (squashed + fuzzy, see text.py); short ones are whole-token matches.
- FEATURES: counts computed in code by `extract_features` (ID-number patterns,
  transaction rows, bank column headers). A feature scores
  `weight + per_extra * (count - min_count)`, capped at `cap`.

Weights: ~5-7 = decisive on its own (form names), 2-4 = typical, <= 1 = shared or
generic ("Government of India"). Negative weights mark look-alike documents we don't
support (Udyam certificate, Form 16, tax invoice) so they fall to UNKNOWN instead of
the nearest supported type. Adding a document type = adding its rows here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.documents.classify.text import PageText, fold, squash, token_regex
from app.documents.models import DocumentType as T


@dataclass(frozen=True)
class Keyword:
    doc_type: T
    weight: float
    variants: tuple[str, ...]
    label: str = ""
    # Short variants (< 6 chars squashed) or token=True match as whole tokens only.
    token: bool = False
    # Form codes ("GSTR-3B", "REG-06") differ by one or two characters, so no fuzzy match.
    fuzzy: bool = True
    _compiled: tuple[tuple[str, re.Pattern[str] | None], ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        compiled = []
        for v in self.variants:
            sq = squash(fold(v))
            compiled.append((sq, token_regex(v) if self.token or len(sq) < 6 else None))
        object.__setattr__(self, "_compiled", tuple(compiled))
        if not self.label:
            object.__setattr__(self, "label", self.variants[0])

    def match(self, page: PageText) -> tuple[float, str]:
        """Best (quality, variant): quality 1.0 exact, the fuzzy ratio, or 0."""
        best, which = 0.0, self.label
        for variant, (sq, rx) in zip(self.variants, self._compiled, strict=True):
            q = (1.0 if rx.search(page.folded) else 0.0) if rx else page.find(sq, fuzzy=self.fuzzy)
            if q > best:
                best, which = q, variant
            if best == 1.0:
                break
        return best, which


def K(doc_type: T, weight: float, *variants: str, token: bool = False, fuzzy: bool = True) -> Keyword:
    return Keyword(doc_type, weight, variants, token=token, fuzzy=fuzzy)


KEYWORDS: list[Keyword] = [
    # ---- Aadhaar (front, back, e-Aadhaar letter) ----
    K(T.AADHAAR, 6, "Unique Identification Authority of India"),
    K(T.AADHAAR, 6, "भारतीय विशिष्ट पहचान प्राधिकरण"),
    K(T.AADHAAR, 4, "UIDAI"),
    K(T.AADHAAR, 4, "help@uidai.gov.in", "www.uidai.gov.in", "uidai.gov.in"),
    K(T.AADHAAR, 5, "Mera Aadhaar, Meri Pehchan", "मेरा आधार, मेरी पहचान"),
    K(T.AADHAAR, 4, "Aadhaar - Aam Admi ka Adhikar", "आधार - आम आदमी का अधिकार", "आम आदमी का अधिकार"),
    K(T.AADHAAR, 5, "Aadhaar is a proof of identity, not of citizenship", "आधार पहचान का प्रमाण है, नागरिकता का नहीं"),
    K(T.AADHAAR, 4, "Your Aadhaar No", "आपका आधार क्रमांक", "Aadhaar No."),
    K(T.AADHAAR, 3, "Enrolment No", "Enrollment No", "नामांकन क्रम"),
    K(T.AADHAAR, 2, "Aadhaar", "Aadhar", "Adhaar", token=True),
    # "आधार" alone also means "basis" ("के आधार पर"), so it stays weak.
    K(T.AADHAAR, 1, "आधार", token=True),
    K(T.AADHAAR, 2, "VID", token=True),
    K(T.AADHAAR, 1, "DOB", "जन्म तिथि", "Year of Birth", "जन्म वर्ष"),
    K(T.AADHAAR, 1, "Male", "Female", "पुरुष", "महिला", token=True),
    K(T.AADHAAR, 1, "पता"),
    K(T.AADHAAR, 1, "Government of India", "Govt. of India", "भारत सरकार"),
    # ---- PAN card ----
    K(T.PAN_CARD, 4, "Permanent Account Number"),
    K(T.PAN_CARD, 4, "स्थायी लेखा संख्या"),
    K(T.PAN_CARD, 2.5, "Income Tax Department", "आयकर विभाग"),
    K(T.PAN_CARD, 2, "Father's Name", "Fathers Name", "पिता का नाम"),
    K(T.PAN_CARD, 3, "e-PAN", token=True),
    K(T.PAN_CARD, 1, "Signature", "हस्ताक्षर"),
    K(T.PAN_CARD, 1, "Government of India", "Govt. of India", "भारत सरकार"),
    K(T.PAN_CARD, 0.5, "Date of Birth", "जन्म की तारीख"),
    # ---- GST registration certificate (Form GST REG-06) ----
    K(T.GST_CERTIFICATE, 7, "Form GST REG-06", "GST REG-06", "REG-06", fuzzy=False),
    K(T.GST_CERTIFICATE, 3, "Registration Certificate", "Certificate of Registration"),
    K(T.GST_CERTIFICATE, 3, "Constitution of Business"),
    K(T.GST_CERTIFICATE, 3, "Address of Principal Place of Business"),
    K(T.GST_CERTIFICATE, 3, "Date of Liability"),
    K(T.GST_CERTIFICATE, 2, "Period of Validity", "Date of Validity"),
    K(T.GST_CERTIFICATE, 2.5, "Type of Registration"),
    K(T.GST_CERTIFICATE, 2.5, "Particulars of Approving Authority"),
    K(T.GST_CERTIFICATE, 1.5, "Details of Managing / Authorized Partners", "Details of Proprietor"),
    K(T.GST_CERTIFICATE, 1.5, "Registration Number"),
    K(T.GST_CERTIFICATE, 1.5, "Legal Name"),
    K(T.GST_CERTIFICATE, 1.5, "Trade Name"),
    K(T.GST_CERTIFICATE, 1, "Goods and Services Tax", "Government of India"),
    K(T.GST_CERTIFICATE, 1, "Annexure A", "Annexure B"),
    # ---- GSTR-3B return ----
    K(T.GSTR_3B, 7, "GSTR-3B", "GSTR 3B", "Form GSTR-3B", fuzzy=False),
    K(T.GSTR_3B, 3, "Outward taxable supplies", "Details of outward supplies"),
    K(T.GSTR_3B, 3, "Eligible ITC"),
    K(T.GSTR_3B, 2, "Inward supplies", "liable to reverse charge"),
    K(T.GSTR_3B, 2, "Payment of tax"),
    K(T.GSTR_3B, 1.5, "Interest and late fee", "Interest & late fee"),
    K(T.GSTR_3B, 1.5, "Integrated tax"),
    K(T.GSTR_3B, 1.5, "Central tax"),
    K(T.GSTR_3B, 1.5, "State/UT tax", "State tax"),
    K(T.GSTR_3B, 1.5, "Tax period", "Return period"),
    K(T.GSTR_3B, 1, "nil rated", "zero rated", "non-GST outward supplies"),
    K(T.GSTR_3B, 0.5, "Legal name of the registered person", "Trade name"),
    # ---- ITR (return form or ITR-V acknowledgement) ----
    K(T.ITR, 7, "Indian Income Tax Return Acknowledgement", "Income Tax Return Acknowledgement"),
    K(T.ITR, 5, "ITR-V", token=True),
    K(T.ITR, 4, "e-Filing Acknowledgement Number", "Acknowledgement Number"),
    K(T.ITR, 3, "Income Tax Return", "आयकर विवरणी"),
    K(T.ITR, 3, "Assessment Year", "निर्धारण वर्ष"),
    K(T.ITR, 3, "Gross Total Income", "सकल कुल आय"),
    K(T.ITR, 3, "SUGAM", "SAHAJ", token=True),
    K(T.ITR, 2, "SARAL", token=True),
    K(T.ITR, 2.5, "Deductions under Chapter VI-A", "Chapter VI-A"),
    K(T.ITR, 2.5, "Central Processing Centre", "Centralized Processing Center"),
    K(T.ITR, 1.5, "Date of filing", "Filed u/s", "Return filed under section"),
    K(T.ITR, 1.5, "Taxes paid", "Total tax payable", "Tax payable"),
    K(T.ITR, 1, "Total Income"),
    K(T.ITR, 1, "Income Tax Department", "आयकर विभाग"),
    # ---- Bank statement ----
    K(T.BANK_STATEMENT, 5, "Statement of Account", "Statement of Accounts", "खाता विवरण"),
    K(T.BANK_STATEMENT, 4, "Account Statement", "Bank Statement", "A/c Statement"),
    K(T.BANK_STATEMENT, 2.5, "Opening Balance", "प्रारंभिक शेष"),
    K(T.BANK_STATEMENT, 2.5, "Closing Balance", "अंतिम शेष"),
    K(T.BANK_STATEMENT, 2, "Transaction Date", "Value Date", "Txn Date"),
    K(T.BANK_STATEMENT, 1.5, "Brought Forward", "Carried Forward", "B/F", "C/F", token=True),
    K(T.BANK_STATEMENT, 1.5, "MICR"),
    K(T.BANK_STATEMENT, 1, "Account Number", "Account No", "A/c No"),
    K(T.BANK_STATEMENT, 1, "Customer ID", "CIF No", "Cust ID"),
    K(T.BANK_STATEMENT, 1, "Branch", "IFSC", token=True),
    K(T.BANK_STATEMENT, 1, "Withdrawal", "Deposit", "निकासी", "जमा"),
    # ---- Credit bureau report (consumer or commercial) ----
    K(T.BUREAU_REPORT, 6, "Credit Information Report", "Commercial Credit Report", "Consumer Credit Report"),
    K(T.BUREAU_REPORT, 5, "CIBIL Score", "CIBIL Rank", "CIBIL MSME Rank", "MSME Rank", "क्रेडिट स्कोर"),
    K(T.BUREAU_REPORT, 3, "CIBIL", "TransUnion", "Trans Union", "Experian", "Equifax", token=True),
    K(T.BUREAU_REPORT, 4, "CRIF High Mark", "CRIF Highmark"),
    K(T.BUREAU_REPORT, 4, "CMR", token=True),
    K(T.BUREAU_REPORT, 3, "Control Number"),
    K(T.BUREAU_REPORT, 3, "Enquiry Information", "Inquiry Information"),
    K(T.BUREAU_REPORT, 2, "Account Information"),
    K(T.BUREAU_REPORT, 3, "Days Past Due"),
    K(T.BUREAU_REPORT, 2, "DPD", token=True),
    K(T.BUREAU_REPORT, 2, "Written-off", "Written off", "Suit-filed", "Suit filed", "Wilful Default"),
    K(T.BUREAU_REPORT, 2, "Credit Facility", "Credit Facilities"),
    K(T.BUREAU_REPORT, 1.5, "Date Reported", "Date Opened", "Current Balance", "Amount Overdue"),
    # ---- Udyam registration certificate ----
    K(T.UDYAM_CERTIFICATE, 7, "Udyam Registration Certificate", "उद्यम पंजीकरण प्रमाणपत्र"),
    K(T.UDYAM_CERTIFICATE, 3, "Udyam Registration", "UDYAM", token=True),
    K(T.UDYAM_CERTIFICATE, 4, "Ministry of Micro, Small and Medium Enterprises", "Ministry of MSME"),
    K(T.UDYAM_CERTIFICATE, 3, "Type of Enterprise"),
    K(T.UDYAM_CERTIFICATE, 2.5, "Name of Enterprise", "Name of Unit"),
    K(T.UDYAM_CERTIFICATE, 2.5, "NIC 2 Digit", "NIC 4 Digit", "NIC 5 Digit", "National Industry Classification"),
    K(T.UDYAM_CERTIFICATE, 2.5, "Date of Commencement of Production", "Date of Commencement of Business"),
    K(T.UDYAM_CERTIFICATE, 1.5, "Date of Incorporation"),
    K(T.UDYAM_CERTIFICATE, 1, "Micro", "Small", "Medium", token=True),
    # ---- Financial statements (audited / CA certified / provisional) ----
    K(T.FINANCIAL_STATEMENTS, 5, "Balance Sheet", "तुलन पत्र"),
    K(T.FINANCIAL_STATEMENTS, 4, "Profit and Loss Account", "Statement of Profit and Loss", "Profit & Loss Account"),
    K(T.FINANCIAL_STATEMENTS, 5, "Independent Auditor's Report", "Independent Auditors Report", "Auditor's Report"),
    K(T.FINANCIAL_STATEMENTS, 2, "Chartered Accountants", "Chartered Accountant"),
    K(T.FINANCIAL_STATEMENTS, 3, "UDIN", token=True),
    K(T.FINANCIAL_STATEMENTS, 3, "Notes to Accounts", "Notes forming part of"),
    K(T.FINANCIAL_STATEMENTS, 3, "Sundry Debtors", "Sundry Creditors", "Trade Receivables", "Trade Payables"),
    K(T.FINANCIAL_STATEMENTS, 2.5, "Share Capital", "Proprietor's Capital", "Partners' Capital", "Capital Account"),
    K(T.FINANCIAL_STATEMENTS, 3, "Reserves and Surplus", "Reserves & Surplus"),
    K(T.FINANCIAL_STATEMENTS, 2, "Total Assets", "Total Liabilities", "Fixed Assets", "Current Assets", "Current Liabilities"),
    K(T.FINANCIAL_STATEMENTS, 1.5, "in lakhs", "in crores", "Amount in ₹", "Amount in Rs"),
    K(T.FINANCIAL_STATEMENTS, 2, "CA certified", "Provisional Financial", "Audited Financial"),
    K(T.FINANCIAL_STATEMENTS, 1, "Schedule", "Provisional", token=True),
    # ---- Sanction letter / Key Fact Statement ----
    K(T.SANCTION_LETTER, 6, "Sanction Letter", "Letter of Sanction", "Sanction Advice"),
    K(T.SANCTION_LETTER, 5, "Key Fact Statement"),
    K(T.SANCTION_LETTER, 3, "KFS", token=True),
    K(T.SANCTION_LETTER, 4, "Sanctioned Amount", "Sanctioned Limit", "Amount Sanctioned"),
    K(T.SANCTION_LETTER, 2, "Rate of Interest"),
    K(T.SANCTION_LETTER, 3, "Annualised Percentage Rate", "Annualized Percentage Rate"),
    K(T.SANCTION_LETTER, 1.5, "APR", token=True),
    K(T.SANCTION_LETTER, 1, "EMI", token=True),
    K(T.SANCTION_LETTER, 2, "Processing Fee"),
    K(T.SANCTION_LETTER, 1.5, "Tenure", "Loan Tenure"),
    K(T.SANCTION_LETTER, 1.5, "Collateral", "Primary Security", "Collateral Security"),
    K(T.SANCTION_LETTER, 1, "Terms and Conditions"),
    K(T.SANCTION_LETTER, 3, "Cooling-off", "Cooling off", "Look-up period", "Lookup period"),
    K(T.SANCTION_LETTER, 1.5, "Overdraft", "Cash Credit", "Term Loan", "Working Capital Loan"),
    K(T.SANCTION_LETTER, 0.5, "Facility", token=True),
    # ---- Payment settlement report (aggregator / POS / UPI merchant) ----
    K(T.SETTLEMENT_REPORT, 6, "Settlement Report", "Settlement Summary", "Settlement Statement", "सेटलमेंट रिपोर्ट"),
    K(T.SETTLEMENT_REPORT, 3, "Net Settlement", "Settlement Amount", "Settlement Date", "Settled Amount"),
    K(T.SETTLEMENT_REPORT, 2, "Payout", token=True),
    K(T.SETTLEMENT_REPORT, 3, "Merchant ID", "Merchant Id"),
    K(T.SETTLEMENT_REPORT, 3, "Terminal ID", "Terminal Id"),
    K(T.SETTLEMENT_REPORT, 1.5, "MID", "TID", "UTR", token=True),
    K(T.SETTLEMENT_REPORT, 2.5, "MDR", token=True),
    K(T.SETTLEMENT_REPORT, 2, "Gross Amount"),
    K(T.SETTLEMENT_REPORT, 1.5, "Payment Mode", "Transaction Fee", "Commission"),
    K(T.SETTLEMENT_REPORT, 0.5, "Razorpay", "Paytm", "PhonePe", "Pine Labs", "Cashfree", "PayU", token=True),
    # ---- look-alikes we don't support: evidence against ----
    # Udyog Aadhaar (the old MSME memorandum) is unsupported; Udyam (its successor) is supported.
    K(T.GST_CERTIFICATE, -4, "Udyog Aadhaar", "Udyam Registration", "उद्यम पंजीकरण"),
    K(T.AADHAAR, -4, "Udyog Aadhaar"),
    K(T.UDYAM_CERTIFICATE, -8, "Udyog Aadhaar"),
    K(T.BANK_STATEMENT, -3, "Settlement Report", "Settlement Summary", "Merchant ID"),
    K(T.ITR, -5, "Certificate under section 203", "Form No. 16", "Form 16A"),
    K(T.BANK_STATEMENT, -3, "Tax Invoice", "Bill of Supply"),
    K(T.GSTR_3B, -3, "Tax Invoice", "Bill of Supply"),
]


# ---------- Features computed in code ----------


@dataclass(frozen=True)
class Feature:
    doc_type: T
    name: str  # key in extract_features()
    weight: float  # score at min_count
    label: str  # "{n}" is replaced with the count
    min_count: int = 1
    per_extra: float = 0.0
    cap: float = 0.0  # 0 = weight is the cap

    def score(self, count: int) -> float:
        if count < self.min_count:
            return 0.0
        return min(self.weight + self.per_extra * (count - self.min_count), self.cap or self.weight)


FEATURES: list[Feature] = [
    Feature(T.PAN_CARD, "pan", 2, "pattern: PAN-format number"),
    Feature(T.ITR, "pan", 1, "pattern: PAN-format number"),
    Feature(T.AADHAAR, "masked_aadhaar", 3, "pattern: masked Aadhaar number"),
    Feature(T.AADHAAR, "uidai_helpline", 4, "pattern: UIDAI helpline 1800 300 1947"),
    Feature(T.GST_CERTIFICATE, "gstin", 2, "pattern: GSTIN"),
    Feature(T.GSTR_3B, "gstin", 1.5, "pattern: GSTIN"),
    Feature(T.GSTR_3B, "gstr3b_sections", 1.5, "pattern: {n} GSTR-3B table numbers (3.1, 4(A), 6.1...)", 2),
    Feature(T.ITR, "itr_form", 3, "pattern: ITR form number"),
    Feature(T.ITR, "assessment_year", 2, "pattern: assessment year (A.Y.)"),
    Feature(T.BANK_STATEMENT, "ifsc", 2, "pattern: IFSC code"),
    Feature(T.BANK_STATEMENT, "txn_rows", 1.5, "rows: {n} dated rows with amounts", 3, 0.25, 5),
    Feature(T.BANK_STATEMENT, "txn_tokens", 1, "rows: {n} NEFT/IMPS/UPI/RTGS-style references", 2, 0.25, 2.5),
    Feature(T.BANK_STATEMENT, "bank_header", 4, "table: bank statement column headers"),
    Feature(T.UDYAM_CERTIFICATE, "udyam_number", 6, "pattern: Udyam registration number"),
    Feature(T.SETTLEMENT_REPORT, "settlement_header", 5, "table: settlement column headers"),
    Feature(T.BANK_STATEMENT, "settlement_header", -4, "table: settlement column headers (not a bank statement)"),
    Feature(T.BUREAU_REPORT, "score_range", 2, "pattern: score range 300-900"),
]

# Position-aware OCR coercion for ID numbers: a letter slot accepts a digit that OCR
# commonly confuses with a letter and vice versa.
_TO_LETTER = str.maketrans("0125846", "OIZSBAG")
_TO_DIGIT = str.maketrans("OIZSBLDQG", "012581006")
_PAN_ENTITY = set("ABCFGHLJPT")  # 4th PAN character: holder type


def _coerce(s: str, shape: str) -> str | None:
    """Coerce `s` to `shape` ('A' letter, '9' digit, '*' either); None if impossible."""
    out = []
    for ch, kind in zip(s, shape, strict=True):
        if kind == "A":
            ch = ch.translate(_TO_LETTER)
            if not ("A" <= ch <= "Z"):
                return None
        elif kind == "9":
            ch = ch.translate(_TO_DIGIT)
            if not ch.isdigit():
                return None
        out.append(ch)
    return "".join(out)


_GSTIN_CAND = re.compile(r"(?<![A-Z0-9])((?:[A-Z0-9]\s?){14}[A-Z0-9])(?![A-Z0-9])")
_PAN_CAND = re.compile(r"(?<![A-Z0-9])((?:[A-Z0-9]\s?){9}[A-Z0-9])(?![A-Z0-9])")
_IFSC = re.compile(r"(?<![A-Z0-9])[A-Z]{4}[0O][A-Z0-9]{6}(?![A-Z0-9])")
# Ingest's mask is always "XXXX XXXX 1234"; "XXXXXXXX4532" is a masked bank account number.
_MASKED = re.compile(r"(?<![X×*\d])[X×*]{4}[ -][X×*]{4}[ -]\d{4}(?!\d)", re.IGNORECASE)
_HELPLINE = re.compile(r"(?<![\d,.])1800[\s-]?300[\s-]?1947(?![\d,.])")
_ITR_FORM = re.compile(r"(?<![A-Z0-9])ITR\s?[-–]?\s?[1-7I](?![0-9A-Za-z])", re.IGNORECASE)
# GSTR-3B table numbers at the start of a line, so amounts like "1,31,150.00" don't count.
_GSTR3B_SECTION = re.compile(r"^\s*(3\.[1-2]|4\s?\([A-D]\)|5\.1|6\.1)(?![\d,])", re.MULTILINE)
_UDYAM = re.compile(r"UDYAM\s?[-–]?\s?([A-Z0-9]{2})\s?[-–]?\s?([A-Z0-9]{2})\s?[-–]?\s?([A-Z0-9]{7})(?![A-Z0-9])")
_SCORE_RANGE = re.compile(r"(?<!\d)300\s?(?:-|–|to)\s?900(?!\d)", re.IGNORECASE)
_AY = re.compile(r"(?<![a-z])a\.?\s?y\.?\s*[:\-]?\s*20\d{2}\s?[-–/]\s?\d{2,4}", re.IGNORECASE)
_DATE = re.compile(
    r"(?<!\d)(\d{1,2}[/\-.](\d{1,2}|[A-Za-z]{3})[/\-.](\d{2}|\d{4})|\d{1,2}\s[A-Za-z]{3}\s\d{2,4}|\d{4}-\d{2}-\d{2})(?!\d)"
)
_AMOUNT = re.compile(r"(?<![\d.])\d{1,3}(,\d{2,3})*\.\d{2}(?!\d)|(?<![\d.,])\d{4,}\.\d{2}(?!\d)")
_TXN_TOKEN = re.compile(r"(?<![A-Z])(NEFT|IMPS|UPI|RTGS|NACH|ECS|ATM|POS|CHQ|CLG|INT\.?PD|ACH)(?![A-Z])", re.IGNORECASE)

# Bank statement column headers, grouped by meaning; a header line hits >= 3 groups.
_HEADER_GROUPS = [
    ("date", "txn date", "value date", "tran date", "तारीख", "दिनांक"),
    ("narration", "particulars", "description", "details", "remarks", "विवरण"),
    ("chq", "cheque", "ref no", "reference", "chq/ref"),
    ("withdrawal", "debit", "dr", "withdrawals", "निकासी", "नामे"),
    ("deposit", "credit", "cr", "deposits", "जमा"),
    ("balance", "bal", "शेष"),
]
_HEADER_RX = [
    re.compile("|".join(rf"(?<![a-z]){re.escape(fold(w))}(?![a-z])" for w in group)) for group in _HEADER_GROUPS
]


_SETTLE_GROUPS = [
    ("transaction id", "txn id", "order id", "payment id", "transaction ref"),
    ("amount", "gross amount", "transaction amount"),
    ("mdr", "fee", "fees", "commission", "charges"),
    ("settlement amount", "net amount", "net settlement", "payout amount", "settled amount"),
    ("settlement date", "settled on", "payout date", "settled date"),
    ("payment mode", "payment method", "mode", "instrument"),
]
_SETTLE_RX = [
    re.compile("|".join(rf"(?<![a-z]){re.escape(fold(w))}(?![a-z])" for w in group)) for group in _SETTLE_GROUPS
]


def _is_settlement_header(line: str) -> bool:
    folded = fold(line)
    return sum(1 for rx in _SETTLE_RX if rx.search(folded)) >= 4


def _udyam_numbers(upper: str) -> int:
    n = 0
    for m in _UDYAM.finditer(upper):
        if _coerce(m.group(1), "AA") and _coerce(m.group(2), "99") and _coerce(m.group(3), "9999999"):
            n += 1
    return n


def _gstins(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    found, spans = [], []
    for m in _GSTIN_CAND.finditer(text):
        compact = m.group(1).replace(" ", "")
        g = _coerce(compact, "99AAAAA9999A*A*")
        if g and g[13] == "Z":
            found.append(g)
            spans.append(m.span(1))
    return found, spans


def _pans(text: str) -> list[str]:
    found = []
    for m in _PAN_CAND.finditer(text):
        p = _coerce(m.group(1).replace(" ", ""), "AAAAA9999A")
        if p and p[3] in _PAN_ENTITY:
            found.append(p)
    return found


def _is_header(line: str) -> bool:
    folded = fold(line)
    return sum(1 for rx in _HEADER_RX if rx.search(folded)) >= 3


def _txn_rows(lines: list[str]) -> int:
    return sum(1 for line in lines if _DATE.search(line) and _AMOUNT.search(line))


def extract_features(text: str, table_lines: Sequence[str], ocr_rows: Sequence[str] = ()) -> dict[str, int]:
    """Counts for every FEATURES name.

    `text` is page text (case kept), `table_lines` are table rows joined with ' | ', and
    `ocr_rows` are OCR boxes regrouped into visual rows (OCR text has one box per line, so
    a statement row's date and amount would otherwise sit on different lines). ID patterns
    run on text + tables; row/header checks take the best of the three line sources.
    A PAN found only inside a GSTIN is not counted.
    """
    raw = text + "\n" + "\n".join(table_lines)
    upper = raw.upper()
    gstins, spans = _gstins(upper)
    # Blank out GSTINs before looking for PANs: every GSTIN embeds its holder's PAN.
    chars = list(upper)
    for a, b in spans:
        chars[a:b] = " " * (b - a)
    pans = _pans("".join(chars))
    sources = [text.splitlines(), list(table_lines), list(ocr_rows)]
    return {
        "pan": len(set(pans)),
        "gstin": len(set(gstins)),
        "masked_aadhaar": len(_MASKED.findall(raw)),
        "uidai_helpline": len(_HELPLINE.findall(raw)),
        "gstr3b_sections": len(set(_GSTR3B_SECTION.findall(raw))),
        "itr_form": len(_ITR_FORM.findall(raw)),
        "assessment_year": len(_AY.findall(raw)),
        "ifsc": len({c for c in _IFSC.findall(upper) if any(ch.isdigit() for ch in c[5:])}),
        "txn_rows": max(_txn_rows(lines) for lines in sources),
        "txn_tokens": len(_TXN_TOKEN.findall(raw)),
        "udyam_number": _udyam_numbers(upper),
        "score_range": len(_SCORE_RANGE.findall(raw)),
        "settlement_header": int(any(_is_settlement_header(line) for lines in sources for line in lines)),
        "bank_header": int(any(_is_header(line) for lines in sources for line in lines)),
    }
