"""Data contracts for the document pipeline: ingest -> classify -> extract.

Every stage hands the next one these models, so they are the only coupling
between packages. Ingest turns any uploaded file into pages of text (+ images);
the classifier labels pages; the extractor reads fields with provenance.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentType(StrEnum):
    AADHAAR = "aadhaar"
    PAN_CARD = "pan_card"
    GST_CERTIFICATE = "gst_certificate"  # GST REG-06 registration certificate
    GSTR_3B = "gstr_3b"
    ITR = "itr"  # ITR acknowledgement (ITR-V) or return form
    BANK_STATEMENT = "bank_statement"
    BUREAU_REPORT = "bureau_report"  # CIBIL / Experian / Equifax / CRIF, consumer or commercial (CMR)
    UDYAM_CERTIFICATE = "udyam_certificate"  # MSME Udyam registration
    FINANCIAL_STATEMENTS = "financial_statements"  # audited, CA-certified or provisional P&L + balance sheet
    SANCTION_LETTER = "sanction_letter"  # loan / facility sanction letter, KFS
    SETTLEMENT_REPORT = "settlement_report"  # payment aggregator / POS / UPI merchant settlements
    UNKNOWN = "unknown"


class SourceFormat(StrEnum):
    """Detected from file content (magic bytes), never trusted from the extension."""

    PDF = "pdf"
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    TIFF = "tiff"
    BMP = "bmp"
    HEIC = "heic"
    DOCX = "docx"
    DOC = "doc"  # legacy Word: detected but not readable without LibreOffice
    XLSX = "xlsx"
    XLS = "xls"
    CSV = "csv"
    TXT = "txt"
    UNKNOWN = "unknown"


class LoadStatus(StrEnum):
    OK = "ok"
    PASSWORD_REQUIRED = "password_required"  # encrypted PDF/XLSX and no (or wrong) password
    UNSUPPORTED_FORMAT = "unsupported_format"  # e.g. .doc, .zip; message says what to upload instead
    UNREADABLE = "unreadable"  # corrupt file, or no text could be read at all
    TOO_LARGE = "too_large"  # over the byte or page limit in app.config


class TextSource(StrEnum):
    NATIVE = "native"  # text layer / cell values / docx runs
    OCR = "ocr"
    NONE = "none"


class OcrLine(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    # (x0, y0, x1, y1) in pixels of Page.image_png.
    bbox: tuple[float, float, float, float]


class Page(BaseModel):
    """One page of a document; a spreadsheet sheet or a docx body also counts as a page."""

    index: int = Field(ge=0)
    text: str = ""
    text_source: TextSource = TextSource.NONE
    # Rendered/decoded page image (PNG bytes), Aadhaar-redacted. None for
    # text-only sources (CSV, XLSX, docx without images). Never serialized.
    image_png: bytes | None = Field(default=None, exclude=True, repr=False)
    width: int | None = None
    height: int | None = None
    ocr_lines: list[OcrLine] = []
    # Verhoeff check of each Aadhaar number found on this page, computed on the FULL number before
    # it was masked (the full number never leaves ingest). Empty when none was found.
    aadhaar_verhoeff_valid: list[bool] = []
    # Tables as rows of cell strings: spreadsheet sheets, docx tables, or
    # tables reconstructed from a PDF text layer.
    tables: list[list[list[str]]] = []


class LoadedDocument(BaseModel):
    file_name: str
    sha256: str
    source_format: SourceFormat
    status: LoadStatus
    message: str | None = None  # user-facing explanation when status != ok
    pages: list[Page] = []
    warnings: list[str] = []

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text)


# ---------- Classification ----------

ClassifyMethod = Literal["rules", "vlm", "rules+vlm", "none"]
PageMethod = Literal["rules", "context", "vlm", "rules+vlm", "none"]


class PageClassification(BaseModel):
    page_index: int
    document_type: DocumentType
    confidence: float = Field(ge=0, le=1)
    method: PageMethod = "rules"
    # Human-readable evidence, e.g. "text: 'Permanent Account Number'", "pattern: PAN".
    signals: list[str] = []


class DocumentSegment(BaseModel):
    """A run of consecutive pages holding one document (a PDF can bundle PAN + Aadhaar)."""

    document_type: DocumentType
    page_indexes: list[int]
    confidence: float = Field(ge=0, le=1)


class ClassificationResult(BaseModel):
    file_name: str
    status: LoadStatus
    message: str | None = None
    # Dominant type across the file; UNKNOWN when nothing reached the threshold.
    document_type: DocumentType
    confidence: float = Field(ge=0, le=1)
    method: ClassifyMethod
    pages: list[PageClassification] = []
    segments: list[DocumentSegment] = []
    warnings: list[str] = []  # e.g. VLM failed or budget spent; rules result kept


# ---------- Extraction ----------


class FieldSource(StrEnum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    VLM = "vlm"
    COMPUTED = "computed"  # derived in code from other fields/rows (e.g. turnover, bounces)


class ExtractedField(BaseModel):
    """One field with provenance. A value that fails validation is not kept: the field goes to `missing`."""

    value: Any
    source: FieldSource
    page_index: int | None = None
    confidence: float = Field(ge=0, le=1)
    # True when code checked it (PAN regex, GSTIN check digit, Verhoeff, balance math, OCR agreement).
    validated: bool = False
    note: str | None = None


class ExtractionResult(BaseModel):
    document_type: DocumentType
    schema_version: str = "v1"
    status: Literal["ok", "partial", "failed"]
    fields: dict[str, ExtractedField] = {}
    # Required fields that could not be read or failed validation; never guessed.
    missing: list[str] = []
    # Row data, e.g. {"transactions": [{"date": ..., "debit": ..., "credit": ..., "balance": ...}]}.
    tables: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
