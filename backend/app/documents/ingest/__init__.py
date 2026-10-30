"""Ingest: turn any uploaded file into a LoadedDocument (pages of text + redacted images).

The classifier and extractor never see file formats. Every failure becomes a
LoadStatus with a user-facing message; no exception escapes load_document.
Aadhaar numbers are masked to the last 4 digits here, before anything leaves.
"""

from __future__ import annotations

import hashlib
import logging

from app import config
from app.documents.models import LoadedDocument, LoadStatus, Page, SourceFormat, TextSource
from app.documents.ports import OcrEngine
from app.documents.ingest.common import IngestError
from app.documents.ingest.detect import detect_format, ole_streams

__all__ = ["load_document", "detect_format"]

log = logging.getLogger(__name__)

SUPPORTED_HINT = "Upload a PDF, a photo (JPG, PNG, HEIC), a Word file (DOCX) or an Excel/CSV file."
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_IMAGES = {SourceFormat.JPEG, SourceFormat.PNG, SourceFormat.WEBP, SourceFormat.TIFF, SourceFormat.BMP, SourceFormat.HEIC}


def _encrypted_office_format(file_name: str) -> SourceFormat:
    # Encrypted DOCX/XLSX are an OLE2 wrapper around an encrypted zip: the content can't
    # say which, so the extension is only used for labelling, never for parsing.
    suffix = file_name.lower().rsplit(".", 1)[-1]
    if suffix.startswith("xls"):
        return SourceFormat.XLSX
    if suffix.startswith("doc"):
        return SourceFormat.DOCX
    return SourceFormat.UNKNOWN


def _unsupported_message(data: bytes) -> str:
    if data.startswith(b"PK\x03\x04"):
        return "This is a ZIP archive. Unzip it and upload the documents inside. " + SUPPORTED_HINT
    if data.startswith(_OLE2) and "PowerPoint Document" in ole_streams(data):
        return "PowerPoint files are not supported. Save it as PDF and upload again."
    return "This file type is not supported. " + SUPPORTED_HINT


def _load_pages(fmt: SourceFormat, data: bytes, password: str | None, ocr: OcrEngine | None, warnings: list[str]) -> list[Page]:
    # Loaders are imported lazily so a CSV upload never pays for pypdfium2/python-docx imports.
    if fmt is SourceFormat.PDF:
        from app.documents.ingest.pdf import load_pdf

        return load_pdf(data, password, ocr, warnings)
    if fmt in _IMAGES:
        from app.documents.ingest.images import load_image

        return load_image(data, ocr, warnings)
    if fmt is SourceFormat.DOCX:
        from app.documents.ingest.word import load_docx

        return load_docx(data, ocr, warnings)
    from app.documents.ingest import sheets

    if fmt is SourceFormat.XLSX:
        return sheets.load_xlsx(data, warnings)
    if fmt is SourceFormat.XLS:
        return sheets.load_xls(data, warnings)
    if fmt is SourceFormat.CSV:
        return sheets.load_csv(data, warnings)
    if fmt is SourceFormat.TXT:
        return sheets.load_txt(data)
    if fmt is SourceFormat.DOC:
        raise IngestError(LoadStatus.UNSUPPORTED_FORMAT, "Please save this Word file as PDF or DOCX and upload again.")
    raise IngestError(LoadStatus.UNSUPPORTED_FORMAT, _unsupported_message(data))


def load_document(
    data: bytes, file_name: str, *, password: str | None = None, ocr: OcrEngine | None = None
) -> LoadedDocument:
    """Detect the format from content and load it. `ocr=None` skips OCR: image pages keep
    text_source NONE (and cannot be checked for Aadhaar numbers) but still carry image_png."""
    sha256 = hashlib.sha256(data).hexdigest()
    fmt = SourceFormat.UNKNOWN
    warnings: list[str] = []

    def result(status: LoadStatus, message: str | None = None, pages: list[Page] | None = None) -> LoadedDocument:
        return LoadedDocument(
            file_name=file_name,
            sha256=sha256,
            source_format=fmt,
            status=status,
            message=message,
            pages=pages or [],
            warnings=warnings,
        )

    if len(data) > config.MAX_UPLOAD_BYTES:
        limit_mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        return result(LoadStatus.TOO_LARGE, f"This file is larger than {limit_mb} MB. Upload a smaller file.")
    if not data.strip():
        return result(LoadStatus.UNREADABLE, "This file is empty. Please upload it again.")

    try:
        fmt = detect_format(data)
        if fmt is SourceFormat.UNKNOWN and data.startswith(_OLE2) and "EncryptedPackage" in ole_streams(data):
            fmt = _encrypted_office_format(file_name)
            raise IngestError(
                LoadStatus.PASSWORD_REQUIRED,
                "This Office file is password protected. Open it, remove the password (or save as PDF) and upload again.",
            )
        pages = _load_pages(fmt, data, password, ocr, warnings)
    except IngestError as exc:
        log.info("ingest %s: %s (%s)", fmt, exc.status, sha256[:12])
        warnings.clear()
        return result(exc.status, exc.message)
    except Exception as exc:  # corrupt files make parsers fail in many ways
        log.warning("ingest %s: unreadable, %s (%s)", fmt, type(exc).__name__, sha256[:12])
        warnings.clear()
        return result(LoadStatus.UNREADABLE, "This file is damaged or could not be read. Please upload it again.")

    if not any(page.text.strip() for page in pages):
        warnings.append("No text could be read from this file.")
    log.info("ingest %s: ok, %d page(s), %s (%s)", fmt, len(pages), _sources(pages), sha256[:12])
    return result(LoadStatus.OK, pages=pages)


def _sources(pages: list[Page]) -> str:
    counts = {s: sum(p.text_source is s for p in pages) for s in TextSource}
    return ", ".join(f"{s.value}={n}" for s, n in counts.items() if n)
