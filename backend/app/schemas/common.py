"""Building blocks shared by every MSME schema: provenance, checks, enums and format patterns.

Conventions
- Money is in rupees (float, 2 dp). Compare amounts with a tolerance of ₹0.01, never with ==.
- Dates are ISO dates (YYYY-MM-DD); months are "YYYY-MM".
- Bounding boxes are fractions of the page (0-1), so the dashboard can draw them at any zoom and the
  same box works for photos and PDFs.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field

# 1.1 added optional bank balances, Aadhaar year of birth, transaction references and input-kind values.
# 1.2 adds envelopes for bureau, financial statements, sanction letters and settlement reports, plus
# optional bureau detail. Readers continue accepting 1.0 and 1.1 payloads.
SCHEMA_VERSION = "1.2"

# Fields below this confidence go to the user to confirm (unless already confirmed).
REVIEW_CONFIDENCE = 0.85

# ---- Format patterns, for the validation step ---------------------------------------------------
# Extracted values are NOT constrained by these: a misread PAN must still be storable so validation
# can flag it with a failed check. Use the compiled versions in validators.

PAN_PATTERN = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
IFSC_PATTERN = r"^[A-Z]{4}0[A-Z0-9]{6}$"
UDYAM_PATTERN = r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$"
PINCODE_PATTERN = r"^[1-9][0-9]{5}$"
MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
ASSESSMENT_YEAR_PATTERN = r"^[0-9]{4}-[0-9]{2}$"

PAN_RE = re.compile(PAN_PATTERN)
GSTIN_RE = re.compile(GSTIN_PATTERN)
IFSC_RE = re.compile(IFSC_PATTERN)
UDYAM_RE = re.compile(UDYAM_PATTERN)
PINCODE_RE = re.compile(PINCODE_PATTERN)

# Privacy: only the last 4 digits of Aadhaar and bank account numbers are ever stored. This type is
# the enforcement point; a full number fails validation.
Last4 = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")]
Month = Annotated[str, StringConstraints(pattern=MONTH_PATTERN)]


class Schema(BaseModel):
    """Base for all MSME schemas: unknown fields are rejected, so nothing slips in unnoticed."""

    model_config = ConfigDict(extra="forbid")


# ---- Enums ---------------------------------------------------------------------------------------


class DocumentType(StrEnum):
    PAN_CARD = "pan_card"
    AADHAAR = "aadhaar"
    GST_REGISTRATION = "gst_registration"
    GSTR3B = "gstr3b"
    BANK_STATEMENT = "bank_statement"
    UDYAM = "udyam"
    ITR_V = "itr_v"
    BUREAU_REPORT = "bureau_report"
    FINANCIAL_STATEMENTS = "financial_statements"
    SANCTION_LETTER = "sanction_letter"
    SETTLEMENT_REPORT = "settlement_report"


REQUIRED_DOCUMENTS: tuple[DocumentType, ...] = (
    DocumentType.PAN_CARD,
    DocumentType.AADHAAR,
    DocumentType.GST_REGISTRATION,
    DocumentType.GSTR3B,
    DocumentType.BANK_STATEMENT,
    DocumentType.UDYAM,
)
OPTIONAL_DOCUMENTS: tuple[DocumentType, ...] = (
    DocumentType.ITR_V,
    DocumentType.BUREAU_REPORT,
    DocumentType.FINANCIAL_STATEMENTS,
    DocumentType.SANCTION_LETTER,
    DocumentType.SETTLEMENT_REPORT,
)


class Source(StrEnum):
    """Who produced a value."""

    PARSER = "parser"  # text layer of a digital PDF
    OCR = "ocr"
    VLM = "vlm"
    USER = "user"  # typed or corrected by the SME
    SYSTEM = "system"  # computed by our code


class CheckStatus(StrEnum):
    PASS = "pass"  # ✓
    WARN = "warn"  # ⚠ e.g. "R. Kumar" vs "Ravi Kumar"
    FAIL = "fail"  # ✗


class CrossCheck(StrEnum):
    """Stable ids for the cross-document checks, shared by validator, dashboard and readiness score."""

    PAN_IN_GSTIN = "cross.pan_in_gstin"  # GSTIN chars 3-12 == PAN card number
    NAME_MATCH = "cross.name_match"  # PAN, Aadhaar, GST, bank account holder (fuzzy)
    DOB_MATCH = "cross.dob_match"  # PAN vs Aadhaar
    ADDRESS_MATCH = "cross.address_match"  # Aadhaar, GST, Udyam
    GST_VS_BANK = "cross.gst_vs_bank"  # GSTR-3B turnover vs bank credits, same months
    BALANCE_MATH = "cross.balance_math"  # previous balance + credit - debit == balance, every row
    STATEMENT_GAPS = "cross.statement_gaps"  # no missing months in bank statement / GSTR-3B


class Constitution(StrEnum):
    PROPRIETORSHIP = "proprietorship"
    PARTNERSHIP = "partnership"
    LLP = "llp"
    PVT_LTD = "pvt_ltd"
    PUBLIC_LTD = "public_ltd"
    HUF = "huf"
    TRUST = "trust"
    SOCIETY = "society"
    OTHER = "other"


class MsmeCategory(StrEnum):
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"


# ---- Provenance ----------------------------------------------------------------------------------


class BBox(Schema):
    """Where on the page a value was read. Coordinates are fractions of page width/height."""

    page: int = Field(ge=1)
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


T = TypeVar("T")


class Extracted(BaseModel, Generic[T]):
    """One extracted field with its provenance.

    The dashboard draws `bbox` and shows `confidence`; the validator sends fields with
    `needs_review` to the user to confirm.
    """

    # Ignore (not forbid) extras so a serialized object, which includes `needs_review`, can be
    # validated again unchanged.
    model_config = ConfigDict(extra="ignore")

    value: T | None
    confidence: float = Field(ge=0, le=1)
    source: Source
    bbox: BBox | None = None
    raw_text: str | None = None  # text as read, before normalising (e.g. "abcpk 1234f")
    user_confirmed: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def needs_review(self) -> bool:
        return not self.user_confirmed and (self.value is None or self.confidence < REVIEW_CONFIDENCE)


class RowProvenance(Schema):
    """Provenance for one table row (transactions, GSTR-3B months): one record per row, not per cell."""

    source: Source
    confidence: float = Field(ge=0, le=1)
    bbox: BBox | None = None


class Address(Schema):
    text: str  # full address as one line, used for fuzzy matching
    city: str | None = None
    district: str | None = None
    state: str | None = None
    pincode: str | None = None


# ---- Checks and evidence -------------------------------------------------------------------------


class Check(Schema):
    """One ✓ / ⚠ / ✗ result with a plain-language message for the SME."""

    id: str  # "pan.format", "aadhaar.verhoeff", or a CrossCheck value
    status: CheckStatus
    message: str
    document_ids: list[str] = []
    fields: list[str] = []  # dotted paths, e.g. "data.pan_number"
    expected: str | None = None
    actual: str | None = None


class EvidenceRef(Schema):
    """Points a profile value back to the document field it came from."""

    document_id: str
    field: str  # dotted path inside the document envelope, e.g. "data.gstin"
    bbox: BBox | None = None


class Sourced(BaseModel, Generic[T]):
    """A profile value plus the evidence behind it. This is what lenders see as source-linked."""

    model_config = ConfigDict(extra="forbid")

    value: T
    evidence: list[EvidenceRef] = []
