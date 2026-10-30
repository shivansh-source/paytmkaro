"""Checks each document can run on its own (format, checksum, internal consistency).

Every check carries a plain-language message for the SME. Field paths are relative to the envelope
(e.g. "data.pan_number") so the dashboard can highlight the right box.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from app.schemas.common import (
    GSTIN_RE,
    IFSC_RE,
    PAN_RE,
    UDYAM_RE,
    Check,
    CheckStatus,
    DocumentType,
    Extracted,
)
from app.schemas.documents import (
    Aadhaar,
    BankStatement,
    DocumentEnvelope,
    GstRegistration,
    Gstr3b,
    ItrV,
    PanCard,
    Udyam,
)
from app.validation.checksums import GST_STATE_CODES, gstin_checksum_valid
from app.validation.months import month_key, month_label, month_range

TOLERANCE = 0.01  # rupees
MIN_STATEMENT_MONTHS = 6
MIN_GSTR3B_MONTHS = 6

FIELD_LABELS = {
    "pan_number": "PAN",
    "name": "name",
    "father_name": "father's name",
    "dob": "date of birth",
    "aadhaar_last4": "Aadhaar last 4 digits",
    "address": "address",
    "gender": "gender",
    "gstin": "GSTIN",
    "legal_name": "legal name",
    "trade_name": "trade name",
    "constitution": "business type",
    "registration_date": "registration date",
    "principal_address": "business address",
    "account_holder_name": "account holder name",
    "account_number_last4": "account number",
    "ifsc": "IFSC",
    "bank_name": "bank name",
    "period_from": "statement start date",
    "period_to": "statement end date",
    "opening_balance": "opening balance",
    "closing_balance": "closing balance",
    "udyam_number": "Udyam number",
    "enterprise_name": "enterprise name",
    "enterprise_type": "MSME category",
    "major_activity": "major activity",
    "date_of_incorporation": "date of incorporation",
    "date_of_registration": "Udyam registration date",
    "assessment_year": "assessment year",
    "itr_form": "ITR form",
    "gross_total_income": "gross total income",
    "acknowledgement_number": "acknowledgement number",
    "filing_date": "filing date",
}


def _check(id: str, ok: bool | None, passed: str, failed: str, fields: list[str], *, warn_only: bool = False, **kw) -> Check:
    if ok is None:
        status = CheckStatus.WARN
        message = f"Couldn't read the {', '.join(FIELD_LABELS.get(f.split('.')[-1], f) for f in fields)}"
    elif ok:
        status, message = CheckStatus.PASS, passed
    else:
        status, message = (CheckStatus.WARN if warn_only else CheckStatus.FAIL), failed
    return Check(id=id, status=status, message=message, fields=fields, **kw)


def _value(field: Extracted | None):
    return field.value if field is not None else None


def _review_check(prefix: str, data) -> Check | None:
    """One warning listing every low-confidence field the user should confirm."""
    names = [
        name
        for name in type(data).model_fields
        if isinstance(getattr(data, name), Extracted) and getattr(data, name).needs_review
    ]
    if not names:
        return None
    labels = ", ".join(FIELD_LABELS.get(n, n) for n in names)
    return Check(
        id=f"{prefix}.needs_review",
        status=CheckStatus.WARN,
        message=f"Please confirm: {labels}",
        fields=[f"data.{n}" for n in names],
    )


# ---- Per document --------------------------------------------------------------------------------


def check_pan(d: PanCard, as_of: date) -> list[Check]:
    pan = (_value(d.pan_number) or "").upper()
    dob = _value(d.dob)
    age = (as_of - dob).days // 365 if dob else None
    return [
        _check("pan.format", PAN_RE.match(pan) is not None if pan else None, "PAN format is valid",
               f"'{pan}' is not a valid PAN (expected 5 letters, 4 digits, 1 letter)", ["data.pan_number"]),
        _check("pan.holder_type", pan[3] == "P" if len(pan) == 10 else None,
               "PAN belongs to an individual, as expected for a proprietor",
               f"4th letter is '{pan[3] if len(pan) > 3 else '?'}', not P: this PAN is not an individual's",
               ["data.pan_number"], warn_only=True),
        _check("pan.dob_plausible", 18 <= age <= 100 if age is not None else None,
               "Date of birth looks right", f"Date of birth gives an age of {age}; please check it",
               ["data.dob"], warn_only=True),
    ]


def check_aadhaar(d: Aadhaar, as_of: date) -> list[Check]:
    return [
        _check("aadhaar.checksum", d.verhoeff_valid, "Aadhaar number passed the checksum",
               "Aadhaar number failed the checksum: it may be misread or invalid", ["data.aadhaar_last4"]),
    ]


def check_gst_registration(d: GstRegistration, as_of: date) -> list[Check]:
    gstin = (_value(d.gstin) or "").upper()
    fmt = GSTIN_RE.match(gstin) is not None if gstin else None
    return [
        _check("gst.format", fmt, "GSTIN format is valid", f"'{gstin}' is not a valid GSTIN", ["data.gstin"]),
        _check("gst.state_code", gstin[:2] in GST_STATE_CODES if fmt else None, "GSTIN state code is valid",
               f"'{gstin[:2]}' is not a GST state code", ["data.gstin"]),
        _check("gst.checksum", gstin_checksum_valid(gstin) if fmt else None, "GSTIN check digit is correct",
               "GSTIN check digit doesn't match: it may be misread", ["data.gstin"]),
    ]


def _missing_months(present: set[str], expected: list[str]) -> list[str]:
    return [m for m in expected if m not in present]


def check_gstr3b(d: Gstr3b, as_of: date) -> list[Check]:
    months = sorted({m.period for m in d.months})
    checks = [
        _check("gstr3b.format", GSTIN_RE.match((_value(d.gstin) or "").upper()) is not None if _value(d.gstin) else None,
               "GSTIN format is valid", "GSTIN on the return is not valid", ["data.gstin"]),
    ]
    if months:
        missing = _missing_months(set(months), month_range(months[0], months[-1]))
        checks.append(
            _check("gstr3b.missing_months", not missing, f"All {len(months)} months from {month_label(months[0])} to {month_label(months[-1])} are present",
                   f"Missing GSTR-3B for {', '.join(map(month_label, missing))}", ["data.months"])
        )
    checks.append(
        _check("gstr3b.enough_months", len(months) >= MIN_GSTR3B_MONTHS, f"{len(months)} months of returns",
               f"Only {len(months)} months of returns; lenders usually ask for {MIN_GSTR3B_MONTHS}", ["data.months"],
               warn_only=True)
    )
    late = [m.period for m in d.months if m.filing_date and m.due_date and m.filing_date > m.due_date]
    checks.append(
        _check("gstr3b.on_time", not late, "Every return was filed on time", f"Filed late: {', '.join(map(month_label, late))}",
               ["data.months"], warn_only=True)
    )
    return checks


def balance_breaks(d: BankStatement) -> list[int]:
    """Indexes of rows where previous balance + credit - debit != balance."""
    breaks: list[int] = []
    previous = _value(d.opening_balance)
    for i, txn in enumerate(d.transactions):
        if previous is not None and abs(previous + txn.credit - txn.debit - txn.balance) > TOLERANCE:
            breaks.append(i)
        previous = txn.balance
    return breaks


def check_bank_statement(d: BankStatement, as_of: date) -> list[Check]:
    ifsc = (_value(d.ifsc) or "").upper()
    checks = [_check("bank.ifsc_format", IFSC_RE.match(ifsc) is not None if ifsc else None, "IFSC format is valid",
                     f"'{ifsc}' is not a valid IFSC", ["data.ifsc"])]

    breaks = balance_breaks(d)
    detail = ", ".join(f"{d.transactions[i].date:%d %b %Y}" for i in breaks[:3])
    checks.append(
        _check("bank.balance_math", not breaks, "Every row adds up: previous balance + credit - debit = balance",
               f"Balance doesn't add up on {len(breaks)} row(s) ({detail}): possible edit or misread",
               [f"data.transactions.{i}" for i in breaks] or ["data.transactions"])
    )

    last = d.transactions[-1].balance if d.transactions else _value(d.opening_balance)
    closing = _value(d.closing_balance)
    if closing is not None and last is not None:
        checks.append(
            _check("bank.closing_balance", abs(closing - last) <= TOLERANCE, "Closing balance matches the last row",
                   f"Closing balance {closing:,.2f} doesn't match the last row ({last:,.2f})", ["data.closing_balance"])
        )

    dates = [t.date for t in d.transactions]
    checks.append(_check("bank.date_order", dates == sorted(dates), "Transactions are in date order",
                         "Transactions are out of date order", ["data.transactions"], warn_only=True))

    start, end = _value(d.period_from), _value(d.period_to)
    if start and end:
        expected = month_range(month_key(start), month_key(end))
        missing = _missing_months({month_key(t.date) for t in d.transactions}, expected)
        checks.append(
            _check("bank.missing_months", not missing, f"Transactions in every month, {month_label(expected[0])} to {month_label(expected[-1])}",
                   f"No transactions in {', '.join(map(month_label, missing))}: pages may be missing", ["data.transactions"])
        )
        checks.append(
            _check("bank.enough_months", len(expected) >= MIN_STATEMENT_MONTHS, f"{len(expected)} months of statement",
                   f"Only {len(expected)} months; lenders usually ask for {MIN_STATEMENT_MONTHS}-12",
                   ["data.period_from", "data.period_to"], warn_only=True)
        )
    return checks


def check_udyam(d: Udyam, as_of: date) -> list[Check]:
    number = (_value(d.udyam_number) or "").upper()
    return [
        _check("udyam.format", UDYAM_RE.match(number) is not None if number else None, "Udyam number format is valid",
               f"'{number}' is not a valid Udyam number (UDYAM-XX-00-0000000)", ["data.udyam_number"]),
    ]


def check_itr_v(d: ItrV, as_of: date) -> list[Check]:
    pan = (_value(d.pan_number) or "").upper()
    year = _value(d.assessment_year) or ""
    current_ay_start = as_of.year + (1 if as_of.month >= 4 else 0)  # AY 2026-27 starts April 2026
    recent = int(year[:4]) >= current_ay_start - 2 if year[:4].isdigit() else None
    return [
        _check("itr.pan_format", PAN_RE.match(pan) is not None if pan else None, "PAN on ITR-V is valid",
               f"'{pan}' on the ITR-V is not a valid PAN", ["data.pan_number"]),
        _check("itr.recent", recent, f"Assessment year {year} is recent", f"Assessment year {year} is old; upload a recent ITR-V",
               ["data.assessment_year"], warn_only=True),
    ]


CHECKERS: dict[DocumentType, tuple[str, Callable]] = {
    DocumentType.PAN_CARD: ("pan", check_pan),
    DocumentType.AADHAAR: ("aadhaar", check_aadhaar),
    DocumentType.GST_REGISTRATION: ("gst", check_gst_registration),
    DocumentType.GSTR3B: ("gstr3b", check_gstr3b),
    DocumentType.BANK_STATEMENT: ("bank", check_bank_statement),
    DocumentType.UDYAM: ("udyam", check_udyam),
    DocumentType.ITR_V: ("itr", check_itr_v),
}


def check_document(envelope: DocumentEnvelope, as_of: date) -> list[Check]:
    if envelope.data is None:
        return []
    prefix, checker = CHECKERS[envelope.document_type]
    checks = [*checker(envelope.data, as_of)]
    if (review := _review_check(prefix, envelope.data)) is not None:
        checks.append(review)
    for check in checks:
        check.document_ids = [envelope.document_id]
    return checks
