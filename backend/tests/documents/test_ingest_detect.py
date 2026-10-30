"""Format detection from content: wrong extensions, unsupported and broken files."""

from pathlib import Path

import pytest

from app.documents.ingest import detect_format, load_document
from app.documents.models import LoadStatus, SourceFormat

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"

EXPECTED = {
    "pan_card.jpg": SourceFormat.JPEG,
    "pan_card.heic": SourceFormat.HEIC,
    "aadhaar_front.png": SourceFormat.PNG,
    "aadhaar_front.webp": SourceFormat.WEBP,
    "aadhaar_front.bmp": SourceFormat.BMP,
    "kyc_scans_multipage.tiff": SourceFormat.TIFF,
    "gst_reg06.pdf": SourceFormat.PDF,
    "gst_reg06_scanned.pdf": SourceFormat.PDF,
    "e_aadhaar_encrypted.pdf": SourceFormat.PDF,
    "kyc_bundle.docx": SourceFormat.DOCX,
    "bank_statement.xlsx": SourceFormat.XLSX,
    "bank_statement.csv": SourceFormat.CSV,
    "legacy_word.doc": SourceFormat.DOC,
    "bureau_report.pdf": SourceFormat.PDF,
    "bureau_report_commercial.pdf": SourceFormat.PDF,
    "bureau_report_scanned.jpg": SourceFormat.JPEG,
    "udyam_certificate.pdf": SourceFormat.PDF,
    "udyam_certificate.jpg": SourceFormat.JPEG,
    "financial_statements.pdf": SourceFormat.PDF,
    "financial_statements.xlsx": SourceFormat.XLSX,
    "sanction_letter.pdf": SourceFormat.PDF,
    "sanction_letter.docx": SourceFormat.DOCX,
    "settlement_report.csv": SourceFormat.CSV,
    "settlement_report.xlsx": SourceFormat.XLSX,
}


@pytest.mark.parametrize("name,expected", EXPECTED.items())
def test_format_comes_from_bytes_not_extension(name, expected):
    data = (FIXTURES / name).read_bytes()
    assert detect_format(data) is expected
    # A misleading name changes nothing.
    doc = load_document(data, "renamed.txt")
    assert doc.source_format is expected
    assert len(doc.sha256) == 64


@pytest.mark.parametrize(
    "name", [n for n in EXPECTED if n not in ("e_aadhaar_encrypted.pdf", "legacy_word.doc")]
)
def test_every_supported_fixture_loads(name):
    doc = load_document((FIXTURES / name).read_bytes(), name)
    assert doc.status is LoadStatus.OK, doc.message
    assert doc.pages


def test_plain_text_and_csv():
    assert detect_format(b"Date,Narration,Amount\n01-04-2025,UPI,100\n02-04-2025,NEFT,200\n") is SourceFormat.CSV
    assert detect_format(b"Dear sir,\nPlease find my documents attached.\nThanks") is SourceFormat.TXT
    # Starts with "BM" but is text, not a bitmap.
    assert detect_format(b"BMW service invoice for R. Kumar, amount 1500") is SourceFormat.TXT
    assert detect_format("Café owner R. Kumar".encode("cp1252")) is SourceFormat.TXT


def test_zip_and_unknown_binary_are_unsupported_with_a_hint():
    doc = load_document((FIXTURES / "archive.zip").read_bytes(), "docs.pdf")
    assert doc.status is LoadStatus.UNSUPPORTED_FORMAT
    assert "ZIP" in doc.message
    doc = load_document(bytes(range(256)) * 4, "x.pdf")
    assert doc.status is LoadStatus.UNSUPPORTED_FORMAT
    assert "PDF" in doc.message


def test_legacy_doc_asks_for_pdf_or_docx():
    doc = load_document((FIXTURES / "legacy_word.doc").read_bytes(), "kyc.doc")
    assert doc.status is LoadStatus.UNSUPPORTED_FORMAT
    assert doc.message == "Please save this Word file as PDF or DOCX and upload again."


@pytest.mark.parametrize("data", [b"", b"   \n\t "])
def test_empty_file_is_unreadable(data):
    doc = load_document(data, "empty.pdf")
    assert doc.status is LoadStatus.UNREADABLE
    assert doc.pages == []


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7\n garbage that is not a pdf",
        b"\xff\xd8\xff\xe0 truncated jpeg",
        b"\x89PNG\r\n\x1a\n broken png",
        b"PK\x03\x04 not really a zip",
        b"PK\x03\x04" + b"\x00" * 100,
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600 + "Workbook".encode("utf-16-le"),
        b"II*\x00 bad tiff",
    ],
)
def test_corrupt_files_never_raise(data):
    doc = load_document(data, "file.bin")
    assert doc.status in (LoadStatus.UNREADABLE, LoadStatus.UNSUPPORTED_FORMAT)
    assert doc.message


def test_zip_with_unusual_compression_does_not_escape(monkeypatch):
    import zipfile

    def boom(*args, **kwargs):
        raise ValueError("odd compression")

    monkeypatch.setattr(zipfile.ZipFile, "read", boom)
    doc = load_document((FIXTURES / "kyc_bundle.docx").read_bytes(), "kyc.docx")
    assert doc.status in (LoadStatus.UNREADABLE, LoadStatus.UNSUPPORTED_FORMAT)


def test_byte_limit(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1000)
    doc = load_document((FIXTURES / "pan_card.jpg").read_bytes(), "pan.jpg")
    assert doc.status is LoadStatus.TOO_LARGE
    assert doc.pages == []
