"""Per-document extraction schemas and the envelope that wraps every uploaded document.

Extractors (parser / OCR / VLM) fill the document models; the validator appends checks to the envelope;
the dashboard reads the envelope to draw highlight boxes and ✓ / ⚠ / ✗ marks.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from app.schemas.common import (
    SCHEMA_VERSION,
    Address,
    Check,
    Constitution,
    DocumentType,
    Extracted,
    Last4,
    Month,
    MsmeCategory,
    RowProvenance,
    Schema,
    Source,
)

# ---- One model per document type -----------------------------------------------------------------


class PanCard(Schema):
    document_type: Literal["pan_card"] = "pan_card"
    pan_number: Extracted[str]
    name: Extracted[str]
    father_name: Extracted[str] | None = None
    dob: Extracted[date]


class Aadhaar(Schema):
    """Masked at upload: the full number is checked (Verhoeff) and then discarded."""

    document_type: Literal["aadhaar"] = "aadhaar"
    aadhaar_last4: Extracted[Last4]
    verhoeff_valid: bool | None = None  # computed on the full number before it was discarded
    name: Extracted[str]
    # Older cards print only a year of birth. At least one of the two must be present; a field that
    # was looked for but unreadable is an Extracted with value None, so validation can report it.
    dob: Extracted[date] | None = None
    year_of_birth: Extracted[int] | None = None
    gender: Extracted[Literal["male", "female", "other"]] | None = None
    address: Extracted[Address]

    @model_validator(mode="after")
    def _has_a_birth_date(self) -> Aadhaar:
        if self.dob is None and self.year_of_birth is None:
            raise ValueError("Aadhaar needs a dob or a year_of_birth (use an Extracted with value None if unreadable)")
        return self


class GstRegistration(Schema):
    """GST REG-06 certificate."""

    document_type: Literal["gst_registration"] = "gst_registration"
    gstin: Extracted[str]
    legal_name: Extracted[str]
    trade_name: Extracted[str] | None = None
    constitution: Extracted[Constitution]
    registration_date: Extracted[date]
    principal_address: Extracted[Address]


class Gstr3bMonth(Schema):
    period: Month
    outward_taxable_value: float = Field(ge=0)  # rupees
    filing_date: date | None = None
    due_date: date | None = None  # to check "filed on time"
    provenance: RowProvenance | None = None


class Gstr3b(Schema):
    """One or more monthly GSTR-3B returns for the same GSTIN."""

    document_type: Literal["gstr3b"] = "gstr3b"
    gstin: Extracted[str]
    months: list[Gstr3bMonth]


TransactionTag = Literal["bounce", "emi", "nach", "charges", "cash", "upi", "gst_payment"]


class Transaction(Schema):
    date: date
    narration: str
    ref: str | None = None  # cheque / reference number column, kept apart from the narration
    debit: float = Field(default=0, ge=0)
    credit: float = Field(default=0, ge=0)
    # Running balance after this row; can be negative on overdraft accounts. None when the statement does not
    # print one: the row is kept (its credit or debit still counts) but cannot be checked on its own.
    balance: float | None = None
    tags: list[TransactionTag] = []  # "bounce" from RTN / INSUFFICIENT FUNDS / NACH RETURN, etc.
    provenance: RowProvenance | None = None


class BankStatement(Schema):
    document_type: Literal["bank_statement"] = "bank_statement"
    account_holder_name: Extracted[str]
    account_number_last4: Extracted[Last4]
    ifsc: Extracted[str]
    bank_name: Extracted[str] | None = None
    period_from: Extracted[date]
    period_to: Extracted[date]
    opening_balance: Extracted[float] | None = None  # many statements never print it; the first row is then not checked
    closing_balance: Extracted[float]
    transactions: list[Transaction]


class Udyam(Schema):
    document_type: Literal["udyam"] = "udyam"
    udyam_number: Extracted[str]
    enterprise_name: Extracted[str]
    enterprise_type: Extracted[MsmeCategory]
    major_activity: Extracted[Literal["manufacturing", "services", "trading"]]
    date_of_incorporation: Extracted[date] | None = None
    date_of_registration: Extracted[date] | None = None
    address: Extracted[Address]


class ItrV(Schema):
    document_type: Literal["itr_v"] = "itr_v"
    pan_number: Extracted[str]
    assessment_year: Extracted[str]  # "2025-26"
    itr_form: Extracted[str]  # "ITR-3", "ITR-4"
    gross_total_income: Extracted[float]
    acknowledgement_number: Extracted[str]
    filing_date: Extracted[date] | None = None


DocumentData = Annotated[
    Union[PanCard, Aadhaar, GstRegistration, Gstr3b, BankStatement, Udyam, ItrV],
    Field(discriminator="document_type"),
]

# ---- Envelope ------------------------------------------------------------------------------------


class FileInfo(Schema):
    file_name: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    pages: int | None = Field(default=None, ge=1)
    sha256: str


class Triage(Schema):
    """Which extractor the triage step chose, and whether it had to fall back."""

    input_kind: Literal["digital_pdf", "scanned_pdf", "photo", "spreadsheet", "word", "text"]
    extractor: Literal[Source.PARSER, Source.OCR, Source.VLM]
    fell_back_to_vlm: bool = False
    fallback_reason: str | None = None  # "low OCR confidence", "OCR and VLM disagree on PAN"
    ocr_mean_confidence: float | None = Field(default=None, ge=0, le=1)
    password_protected: bool = False


DocumentStatus = Literal["queued", "extracting", "needs_review", "verified", "failed"]


class DocumentEnvelope(Schema):
    schema_version: Literal["1.0", "1.1"] = SCHEMA_VERSION
    document_id: str
    sme_id: str
    document_type: DocumentType
    status: DocumentStatus
    uploaded_at: datetime
    file: FileInfo
    triage: Triage | None = None  # set once triage has run
    data: DocumentData | None = None  # set once extraction has run
    checks: list[Check] = []  # this document's own checks (format, checksum, balance math...)
    error: str | None = None  # when status == "failed"

    @model_validator(mode="after")
    def _data_matches_type(self) -> DocumentEnvelope:
        if self.data is not None and self.data.document_type != self.document_type:
            raise ValueError(f"data is {self.data.document_type}, envelope says {self.document_type}")
        return self
