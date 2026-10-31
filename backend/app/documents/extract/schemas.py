"""Field models per document type: the source of truth for validation and the v1 JSON schemas.

Every field is optional in the model so one bad value fails alone; `REQUIRED`
lists what must be present for status "ok". OCR values and VLM values are both
validated through `validate_field`.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, create_model

from app import config
from app.documents.models import DocumentType
from app.documents.extract.common import (
    CONSTITUTIONS,
    GST_STATES,
    PAN_HOLDER_TYPES,
    gstin_valid,
    normalize_constitution,
    parse_date,
    parse_inr,
)


def _upper_compact(v: Any) -> Any:
    return "".join(str(v).upper().split()) if isinstance(v, str) else v


def _date(v: Any) -> Any:
    if isinstance(v, str):
        parsed = parse_date(v)
        if parsed is None:
            raise ValueError(f"not a date: {v!r}")
        return parsed
    return v


def _plausible(d: date) -> date:
    if not date(1900, 1, 1) <= d <= date(2100, 1, 1):
        raise ValueError("date out of range")
    return d


def _amount(v: Any) -> Any:
    if isinstance(v, str):
        parsed = parse_inr(v)
        if parsed is None:
            raise ValueError(f"not an amount: {v!r}")
        return parsed
    return v


def _gstin_checksum(v: str) -> str:
    if not gstin_valid(v):
        raise ValueError("GSTIN check character or state code is wrong")
    return v


def _text(v: Any) -> Any:
    return " ".join(str(v).split()) if isinstance(v, str) else v


def _constitution(v: Any) -> Any:
    if isinstance(v, str):
        code = normalize_constitution(v)
        if code is None:
            raise ValueError(f"unknown constitution: {v!r}")
        return code
    return v


def _gender(v: Any) -> Any:
    if isinstance(v, str):
        low = v.strip().lower()
        for key, out in (("female", "female"), ("महिला", "female"), ("trans", "transgender"), ("male", "male"), ("पुरुष", "male")):
            if key in low:
                return out
        if low in {"m", "f"}:
            return {"m": "male", "f": "female"}[low]
    return v


def _assessment_year(v: Any) -> Any:
    if isinstance(v, str):
        digits = v.replace(" ", "")
        if m := re.fullmatch(r"(?:AY)?(\d{4})[-/](\d{2}|\d{4})", digits, re.IGNORECASE):
            start, end = int(m[1]), int(m[2][-2:])
            if (start + 1) % 100 != end:
                raise ValueError("assessment year must span consecutive years")
            return f"{start}-{end:02d}"
    return v


def _itr_form(v: Any) -> Any:
    if isinstance(v, str):
        if m := re.search(r"ITR\s*-?\s*([1-7])\b", v.upper()):
            return f"ITR-{m[1]}"
    return v


def _last4(v: Any) -> Any:
    if isinstance(v, (str, int)):
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        return digits[-4:] if len(digits) >= 4 else digits
    return v


Pan = Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$"), BeforeValidator(_upper_compact)]
Gstin = Annotated[
    str,
    Field(pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"), BeforeValidator(_upper_compact),
    AfterValidator(_gstin_checksum),
]
Ifsc = Annotated[str, Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$"), BeforeValidator(_upper_compact)]
IsoDate = Annotated[date, BeforeValidator(_date), AfterValidator(_plausible)]
Amount = Annotated[float, BeforeValidator(_amount)]
NonNegAmount = Annotated[float, Field(ge=0), BeforeValidator(_amount)]
# Person names: letters (Latin or Indic), spaces, dots, apostrophes, hyphens; no digits.
PersonName = Annotated[
    str, Field(min_length=2, max_length=100, pattern=r"^[A-Za-z\u0900-\u0DFF][A-Za-z\u0900-\u0DFF .'-]*$"), BeforeValidator(_text)
]
# Business names may contain digits and '&' ("A1 Traders & Co.").
BusinessName = Annotated[
    str, Field(min_length=2, max_length=160, pattern=r"^[A-Za-z0-9\u0900-\u0DFF][A-Za-z0-9\u0900-\u0DFF .,'&()/-]*$"), BeforeValidator(_text)
]
Address = Annotated[str, Field(min_length=8, max_length=400), BeforeValidator(_text)]
Pincode = Annotated[str, Field(pattern=r"^[1-9][0-9]{5}$"), BeforeValidator(_upper_compact)]
Last4 = Annotated[str, Field(pattern=r"^[0-9]{4}$"), BeforeValidator(_last4)]
Month = Annotated[str, Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
FinancialYear = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}$"), BeforeValidator(_assessment_year)]


class _Fields(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PanCardFields(_Fields):
    pan: Pan | None = None
    holder_type: Literal[tuple(PAN_HOLDER_TYPES.values())] | None = None  # type: ignore[valid-type]
    name: PersonName | None = None
    father_name: PersonName | None = None
    dob: IsoDate | None = None


class AadhaarFields(_Fields):
    name: PersonName | None = None
    dob: IsoDate | None = None
    year_of_birth: int | None = Field(default=None, ge=1900, le=2100)
    gender: Annotated[Literal["male", "female", "transgender"], BeforeValidator(_gender)] | None = None
    # Only the last 4 digits ever exist past ingest.
    aadhaar_last4: Last4 | None = None
    address: Address | None = None
    pincode: Pincode | None = None


class GstCertificateFields(_Fields):
    gstin: Gstin | None = None
    pan_from_gstin: Pan | None = None
    state_code: Literal[tuple(GST_STATES)] | None = None  # type: ignore[valid-type]
    state: str | None = None
    legal_name: BusinessName | None = None
    trade_name: BusinessName | None = None
    constitution_of_business: Annotated[Literal[tuple(CONSTITUTIONS)], BeforeValidator(_constitution)] | None = None  # type: ignore[valid-type]
    date_of_liability: IsoDate | None = None
    validity_from: IsoDate | None = None
    registration_date: IsoDate | None = None
    address: Address | None = None
    pincode: Pincode | None = None
    type_of_registration: BusinessName | None = None


class Gstr3bPeriod(_Fields):
    period: Month
    taxable_outward_value: NonNegAmount
    igst: NonNegAmount | None = None
    cgst: NonNegAmount | None = None
    sgst: NonNegAmount | None = None
    cess: NonNegAmount | None = None
    # Provenance added by the extractor.
    source: Literal["text_layer", "ocr", "vlm"] | None = None
    page_index: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class Gstr3bFields(_Fields):
    gstin: Gstin | None = None
    legal_name: BusinessName | None = None
    financial_year: FinancialYear | None = None
    period_from: Month | None = None
    period_to: Month | None = None
    months_filed: int | None = Field(default=None, ge=0)
    # Computed in code from the per-month 3.1(a) rows, never read from the VLM.
    total_taxable_outward_value: NonNegAmount | None = None
    total_tax: NonNegAmount | None = None


class ItrFields(_Fields):
    pan: Pan | None = None
    name: PersonName | None = None
    assessment_year: FinancialYear | None = None
    form_type: Annotated[str, Field(pattern=r"^ITR-[1-7]$"), BeforeValidator(_itr_form)] | None = None
    acknowledgement_number: Annotated[str, Field(pattern=r"^[0-9]{15}$"), BeforeValidator(_upper_compact)] | None = None
    filing_date: IsoDate | None = None
    gross_total_income: NonNegAmount | None = None
    total_income: NonNegAmount | None = None
    tax_payable: NonNegAmount | None = None
    business_turnover: NonNegAmount | None = None


class BankTransaction(_Fields):
    date: IsoDate
    narration: str = ""
    ref: str | None = None
    debit: NonNegAmount | None = None
    credit: NonNegAmount | None = None
    balance: Amount | None = None
    # Added by the extractor: balance math result (None = no previous balance to check against),
    # debit/credit decided by Dr/Cr marker or narration because balance math could not, provenance.
    balance_ok: bool | None = None
    direction_inferred: bool | None = None
    source: Literal["text_layer", "ocr", "vlm"] | None = None
    page_index: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class BankStatementFields(_Fields):
    account_holder_name: BusinessName | None = None
    bank_name: BusinessName | None = None
    ifsc: Ifsc | None = None
    account_number_last4: Last4 | None = None
    period_from: IsoDate | None = None
    period_to: IsoDate | None = None
    opening_balance: Amount | None = None
    closing_balance: Amount | None = None
    # Computed in code from the transaction rows.
    transaction_count: int | None = Field(default=None, ge=0)
    total_credits: NonNegAmount | None = None
    total_debits: NonNegAmount | None = None
    months_covered: int | None = Field(default=None, ge=0)
    balance_breaks: int | None = Field(default=None, ge=0)
    missing_months: list[Month] | None = None


# ---------- Round 2: bureau, Udyam, financial statements, sanction letter, settlements ----------

NO_HISTORY_TOKENS = {"NH", "NA", "N/A", "-1", "000", "0", "00", "NO HISTORY", "NOT AVAILABLE", "-"}
UNITS = {"units": 1, "thousands": 1_000, "lakhs": 100_000, "millions": 1_000_000, "crores": 10_000_000}


def _int(v: Any) -> Any:
    if isinstance(v, bool):
        raise ValueError("not a number")
    if isinstance(v, str):
        digits = v.replace(",", "").strip()
        if not re.fullmatch(r"-?\d+", digits):
            raise ValueError(f"not a whole number: {v!r}")
        return int(digits)
    return v


def _bool(v: Any) -> Any:
    if isinstance(v, str):
        low = v.strip().lower()
        if low in {"yes", "y", "true", "found", "present"}:
            return True
        if low in {"no", "n", "false", "nil", "none", "not found", "absent"}:
            return False
        if re.fullmatch(r"\d+", low):
            return int(low) > 0
        raise ValueError(f"not yes/no: {v!r}")
    if isinstance(v, int) and not isinstance(v, bool):
        return v > 0
    return v


def _score(v: Any) -> Any:
    if isinstance(v, str):
        if v.strip().upper() in NO_HISTORY_TOKENS:
            raise ValueError("no credit history is not a score")
        return _int(v)
    return v


def _bureau(v: Any) -> Any:
    if isinstance(v, str):
        low = v.lower()
        for key, out in (("cibil", "cibil"), ("transunion", "cibil"), ("experian", "experian"), ("equifax", "equifax"), ("crif", "crif"), ("high mark", "crif"), ("bureau", "other")):
            if key in low:
                return out
    return v


def _pan_masked(v: Any) -> Any:
    """Bureau PANs are kept as XXXXXX + last 4 characters; a full PAN is masked, never stored."""
    if isinstance(v, str):
        s = re.sub(r"[^A-Z0-9*]", "", v.upper()).replace("*", "X")
        if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", s):
            return "XXXXXX" + s[-4:]
        if m := re.fullmatch(r"X{4,8}(\d{3}[A-Z])", s):
            return "XXXXXX" + m[1]
    return v


def _lower(v: Any) -> Any:
    return v.strip().lower() if isinstance(v, str) else v


def _unit(v: Any) -> Any:
    if isinstance(v, str):
        low = v.lower()
        for pattern, out in (
            (r"crore|\bcr\b|\bcrs\b", "crores"),
            (r"lakh|lac", "lakhs"),
            (r"million|\bmn\b", "millions"),
            (r"thousand|'000|000s|\bk\b", "thousands"),
            (r"^(?:units?|rupees?|rs\.?|inr|₹)$", "units"),
        ):
            if re.search(pattern, low):
                return out
    return v


def _facility(v: Any) -> Any:
    if isinstance(v, str):
        low = v.lower()
        for pattern, out in (
            (r"term\s*loan|business loan|msme loan|\bterm\b", "term_loan"),
            (r"overdraft|\bod\b", "overdraft"),
            (r"cash\s*credit|\bcc\b", "cash_credit"),
            (r"working\s*capital|\bwcdl\b", "working_capital"),
        ):
            if re.search(pattern, low):
                return out
        return "other"
    return v


def _rate_type(v: Any) -> Any:
    if isinstance(v, str):
        low = v.lower()
        if re.search(r"floating|variable|mclr|eblr|repo|benchmark", low):
            return "floating"
        if "fixed" in low:
            return "fixed"
    return v


def _pct(v: Any) -> Any:
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%?\s*(?:p\.?a\.?)?\s*", v)
        if not m:
            raise ValueError(f"not a percentage: {v!r}")
        return float(m[1])
    return v


def _audit_status(v: Any) -> Any:
    return v.strip().lower().replace(" ", "_").replace("-", "_") if isinstance(v, str) else v


Bool = Annotated[bool, BeforeValidator(_bool)]
Count = Annotated[int, Field(ge=0, le=10_000_000), BeforeValidator(_int)]
Percent = Annotated[float, Field(ge=0, le=100), BeforeValidator(_pct)]
PanMasked = Annotated[str, Field(pattern=r"^X{6}[0-9]{3}[A-Z]$"), BeforeValidator(_pan_masked)]
ShortText = Annotated[str, Field(min_length=2, max_length=300), BeforeValidator(_text)]
Ratio = Annotated[float, BeforeValidator(_amount)]
Udin = Annotated[str, Field(pattern=r"^[0-9A-Z]{18}$"), BeforeValidator(_upper_compact)]
UdyamNumber = Annotated[str, Field(pattern=r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$"), BeforeValidator(_upper_compact)]


class BureauFields(_Fields):
    bureau_name: Annotated[Literal["cibil", "experian", "equifax", "crif", "other"], BeforeValidator(_bureau)] | None = None
    report_date: IsoDate | None = None
    # Full PAN is never stored: XXXXXX + last 4 characters, enough to compare with the PAN card.
    pan_masked: PanMasked | None = None
    # Consumer score, 300-900. Absent (never 0) when the report says NH / NA / -1 / 000.
    score: Annotated[int, Field(ge=300, le=900), BeforeValidator(_score)] | None = None
    no_credit_history: Bool | None = None
    score_type: ShortText | None = None
    # Commercial Credit Risk Rank, 1-10, LOWER IS BETTER. Its own field, never mapped to the score.
    cmr_rank: Annotated[int, Field(ge=1, le=10), BeforeValidator(_int)] | None = None
    active_accounts: Count | None = None
    total_outstanding: NonNegAmount | None = None
    overdue_amount: NonNegAmount | None = None
    max_dpd_24m: Annotated[int, Field(ge=0, le=999), BeforeValidator(_int)] | None = None
    written_off_or_settled: Bool | None = None
    suit_filed_or_wilful_default: Bool | None = None
    enquiries_90d: Count | None = None


class BureauAccount(_Fields):
    """One tradeline. Other lenders' account numbers keep the last 4 digits; phone numbers and
    street addresses are not fields, so they are dropped at validation."""

    lender: BusinessName
    account_type: ShortText | None = None
    status: ShortText | None = None
    account_last4: Last4 | None = None
    sanctioned: NonNegAmount | None = None
    outstanding: NonNegAmount | None = None
    emi: NonNegAmount | None = None
    dpd_max: Annotated[int, Field(ge=0, le=999), BeforeValidator(_int)] | None = None
    dpd_summary: Annotated[str, Field(min_length=1, max_length=300), BeforeValidator(_text)] | None = None
    source: Literal["text_layer", "ocr", "vlm"] | None = None
    page_index: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class NicCode(_Fields):
    code: Annotated[str, Field(pattern=r"^[0-9]{2,5}$"), BeforeValidator(_upper_compact)]
    description: ShortText | None = None


class UdyamFields(_Fields):
    udyam_number: UdyamNumber | None = None
    pan: Pan | None = None
    enterprise_name: BusinessName | None = None
    enterprise_type: Annotated[Literal["micro", "small", "medium"], BeforeValidator(_lower)] | None = None
    organisation_type: Annotated[Literal[tuple(CONSTITUTIONS)], BeforeValidator(_constitution)] | None = None  # type: ignore[valid-type]
    date_of_incorporation: IsoDate | None = None
    date_of_commencement: IsoDate | None = None
    registration_date: IsoDate | None = None
    nic_codes: list[NicCode] | None = None
    major_activity: Annotated[Literal["manufacturing", "services", "trading"], BeforeValidator(_lower)] | None = None
    address: Address | None = None
    state: ShortText | None = None
    pincode: Pincode | None = None


FINANCIAL_AMOUNTS = (
    "revenue", "other_income", "total_expenses", "ebitda", "depreciation", "interest_expense",
    "profit_before_tax", "profit_after_tax", "total_assets", "current_assets", "current_liabilities",
    "total_liabilities", "total_equity_and_liabilities", "net_worth", "long_term_borrowings",
    "short_term_borrowings", "trade_receivables", "trade_payables", "inventory", "cash", "principal_repayments",
)
_financial_columns: dict[str, Any] = {}
for _name in FINANCIAL_AMOUNTS:
    # Amounts are stored in RUPEES: the extractor scales from the unit printed on the statement.
    _financial_columns[_name] = (Amount | None, None)
    _financial_columns[f"prior_{_name}"] = (Amount | None, None)
FinancialStatementsFields = create_model(
    "FinancialStatementsFields",
    __base__=_Fields,
    audit_status=(Annotated[Literal["audited", "ca_certified", "provisional", "unknown"], BeforeValidator(_audit_status)] | None, None),
    financial_year=(FinancialYear | None, None),
    prior_financial_year=(FinancialYear | None, None),
    auditor_name=(PersonName | None, None),
    auditor_firm=(BusinessName | None, None),
    # Format-checked only (18 characters); not verified with ICAI.
    udin=(Udin | None, None),
    unit=(Annotated[Literal[tuple(UNITS)], BeforeValidator(_unit)] | None, None),
    unit_scale=(Annotated[int, Field(ge=1)] | None, None),
    current_ratio=(Ratio | None, None),
    debt_to_equity=(Ratio | None, None),
    net_margin=(Ratio | None, None),
    dscr=(Ratio | None, None),
    **_financial_columns,
)


class SanctionLetterFields(_Fields):
    lender_name: BusinessName | None = None
    facility_type: Annotated[Literal["term_loan", "overdraft", "cash_credit", "working_capital", "other"], BeforeValidator(_facility)] | None = None
    sanctioned_amount: NonNegAmount | None = None
    interest_rate_pct: Percent | None = None
    rate_type: Annotated[Literal["fixed", "floating"], BeforeValidator(_rate_type)] | None = None
    apr_pct: Percent | None = None
    tenure_months: Annotated[int, Field(gt=0, le=600), BeforeValidator(_int)] | None = None
    emi_amount: NonNegAmount | None = None
    # Computed in code from principal, rate and tenure (reducing balance); compared with emi_amount.
    emi_recomputed: NonNegAmount | None = None
    processing_fee: NonNegAmount | None = None
    processing_fee_pct: Percent | None = None
    security: ShortText | None = None
    fd_lien_or_margin: Bool | None = None
    sanction_date: IsoDate | None = None
    validity_date: IsoDate | None = None
    cooling_off_days: Annotated[int, Field(ge=0, le=90), BeforeValidator(_int)] | None = None


class SettlementFields(_Fields):
    provider: BusinessName | None = None
    merchant_id_last4: Last4 | None = None
    period_from: IsoDate | None = None
    period_to: IsoDate | None = None
    # Computed in code from the settlement rows.
    total_gross: NonNegAmount | None = None
    total_fees: NonNegAmount | None = None
    total_net: NonNegAmount | None = None
    fee_pct: Annotated[float, Field(ge=0)] | None = None
    transaction_count: Count | None = None
    months_covered: Count | None = None
    missing_months: list[Month] | None = None


class SettlementRow(_Fields):
    """One settlement. Payer UPI IDs, phone numbers, card numbers and customer names are other
    people's data: they have no field here, so they cannot be stored."""

    date: IsoDate
    gross_amount: NonNegAmount
    fees: NonNegAmount | None = None
    net_settled: NonNegAmount | None = None
    txn_count: Count | None = None
    mode: Annotated[str, Field(min_length=1, max_length=30), BeforeValidator(_text)] | None = None
    net_ok: bool | None = None
    source: Literal["text_layer", "ocr", "vlm"] | None = None
    page_index: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class SettlementMonth(_Fields):
    month: Month
    gross: NonNegAmount
    fees: NonNegAmount
    net: NonNegAmount
    fee_pct: float
    txn_count: int | None = None


FIELD_MODELS: dict[DocumentType, type[_Fields]] = {
    DocumentType.PAN_CARD: PanCardFields,
    DocumentType.AADHAAR: AadhaarFields,
    DocumentType.GST_CERTIFICATE: GstCertificateFields,
    DocumentType.GSTR_3B: Gstr3bFields,
    DocumentType.ITR: ItrFields,
    DocumentType.BANK_STATEMENT: BankStatementFields,
    DocumentType.BUREAU_REPORT: BureauFields,
    DocumentType.UDYAM_CERTIFICATE: UdyamFields,
    DocumentType.FINANCIAL_STATEMENTS: FinancialStatementsFields,
    DocumentType.SANCTION_LETTER: SanctionLetterFields,
    DocumentType.SETTLEMENT_REPORT: SettlementFields,
}

REQUIRED: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.PAN_CARD: ("pan", "name", "dob"),
    DocumentType.AADHAAR: ("name", "aadhaar_last4"),  # plus dob or year_of_birth, checked in extract
    DocumentType.GST_CERTIFICATE: ("gstin", "legal_name", "constitution_of_business", "registration_date"),
    DocumentType.GSTR_3B: ("gstin", "period_from", "period_to"),
    DocumentType.ITR: ("pan", "name", "assessment_year", "total_income"),
    DocumentType.BANK_STATEMENT: ("account_holder_name", "account_number_last4", "period_from", "period_to"),
    # A score is not required: commercial reports carry a CMR rank, and thin files have no score.
    DocumentType.BUREAU_REPORT: ("bureau_name", "report_date"),
    DocumentType.UDYAM_CERTIFICATE: ("udyam_number", "enterprise_name", "enterprise_type"),
    DocumentType.FINANCIAL_STATEMENTS: ("financial_year", "revenue", "profit_after_tax", "total_assets"),
    DocumentType.SANCTION_LETTER: ("lender_name", "facility_type", "sanctioned_amount"),
    DocumentType.SETTLEMENT_REPORT: ("period_from", "period_to"),
}

# Row tables per type: ExtractionResult.tables[key] rows follow this model.
TABLE_MODELS: dict[DocumentType, tuple[str, type[_Fields]]] = {
    DocumentType.GSTR_3B: ("periods", Gstr3bPeriod),
    DocumentType.BANK_STATEMENT: ("transactions", BankTransaction),
    DocumentType.BUREAU_REPORT: ("accounts", BureauAccount),
    DocumentType.SETTLEMENT_REPORT: ("settlements", SettlementRow),
}
# Types whose rows the VLM is asked for when the text pass found none (bureau accounts are optional).
ROW_REQUIRED = {DocumentType.GSTR_3B, DocumentType.BANK_STATEMENT, DocumentType.SETTLEMENT_REPORT}
# Additional computed row tables.
EXTRA_TABLES: dict[DocumentType, dict[str, type[_Fields]]] = {DocumentType.SETTLEMENT_REPORT: {"monthly": SettlementMonth}}

# Values with a real code check (pattern, checksum, range, date parse). Free text such as names
# and addresses only counts as validated when two independent reads agree.
FREE_TEXT = {
    "name", "father_name", "legal_name", "trade_name", "address", "account_holder_name", "bank_name", "type_of_registration",
    "state", "enterprise_name", "auditor_name", "auditor_firm", "lender_name", "security", "provider", "score_type", "nic_codes",
}

SCHEMA_FILES: dict[DocumentType, str] = {
    DocumentType.PAN_CARD: "pan_card.schema.json",
    DocumentType.AADHAAR: "aadhaar.schema.json",
    DocumentType.GST_CERTIFICATE: "gst_reg06.schema.json",
    DocumentType.GSTR_3B: "gstr_3b.schema.json",
    DocumentType.ITR: "itr.schema.json",
    DocumentType.BANK_STATEMENT: "bank_statement.schema.json",
    DocumentType.BUREAU_REPORT: "bureau_report.schema.json",
    DocumentType.UDYAM_CERTIFICATE: "udyam_certificate.schema.json",
    DocumentType.FINANCIAL_STATEMENTS: "financial_statements.schema.json",
    DocumentType.SANCTION_LETTER: "sanction_letter.schema.json",
    DocumentType.SETTLEMENT_REPORT: "settlement_report.schema.json",
}

TITLES = {
    DocumentType.PAN_CARD: "PAN Card",
    DocumentType.AADHAAR: "Aadhaar (masked)",
    DocumentType.GST_CERTIFICATE: "GST REG-06",
    DocumentType.GSTR_3B: "GSTR-3B",
    DocumentType.ITR: "ITR",
    DocumentType.BANK_STATEMENT: "Bank Statement",
    DocumentType.BUREAU_REPORT: "Credit Bureau Report",
    DocumentType.UDYAM_CERTIFICATE: "Udyam Registration Certificate",
    DocumentType.FINANCIAL_STATEMENTS: "Financial Statements",
    DocumentType.SANCTION_LETTER: "Loan Sanction Letter",
    DocumentType.SETTLEMENT_REPORT: "Merchant Settlement Report",
}


def validate_field(document_type: DocumentType, name: str, raw: Any) -> tuple[Any, str | None]:
    """(JSON-ready value, None) when `raw` passes the field's checks, else (None, reason)."""
    model = FIELD_MODELS[document_type]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "empty"
    try:
        parsed = model.model_validate({name: raw})
    except ValidationError as exc:
        return None, exc.errors()[0]["msg"]
    return parsed.model_dump(mode="json")[name], None


def validate_row(document_type: DocumentType, raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    _, model = TABLE_MODELS[document_type]
    try:
        return model.model_validate(raw).model_dump(mode="json"), None
    except ValidationError as exc:
        err = exc.errors()[0]
        return None, f"{'.'.join(map(str, err['loc']))}: {err['msg']}"


# ---------- JSON schema (v1 files are generated from the models above) ----------


def _collapse(node: Any) -> Any:
    """Turn pydantic's anyOf[X, null] into X and drop titles/defaults, recursively."""
    if isinstance(node, dict):
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            if len(options) == 1:
                rest = {k: v for k, v in node.items() if k != "anyOf"}
                node = {**options[0], **rest}
        return {k: _collapse(v) for k, v in node.items() if k not in {"title", "default"}}
    if isinstance(node, list):
        return [_collapse(v) for v in node]
    return node


def json_schema(document_type: DocumentType) -> dict[str, Any]:
    """JSON Schema 2020-12 for the extracted fields (+ row tables) of one document type."""
    model = FIELD_MODELS[document_type]
    properties = _collapse(model.model_json_schema())["properties"]
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{TITLES[document_type]} Extraction Schema v1",
        "type": "object",
        "required": list(REQUIRED[document_type]),
        "properties": properties,
    }
    tables = ([TABLE_MODELS[document_type]] if document_type in TABLE_MODELS else []) + list(EXTRA_TABLES.get(document_type, {}).items())
    for key, row_model in tables:
        row = _collapse(row_model.model_json_schema())
        schema["properties"][key] = {"type": "array", "items": {"type": "object", "required": row.get("required", []), "properties": row["properties"]}}
    return schema


def write_schema_files() -> None:
    """Regenerate backend/schemas/documents/v1/*.schema.json from the models."""
    for document_type, file_name in SCHEMA_FILES.items():
        path = config.DOCUMENT_SCHEMAS_DIR / file_name
        path.write_text(json.dumps(json_schema(document_type), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
