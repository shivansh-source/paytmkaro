"""File format detection from content (magic bytes). The extension is never trusted."""

from __future__ import annotations

import csv
import io
import zipfile

from app.documents.models import SourceFormat

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"avif"}


def _ole_name(name: str) -> bytes:
    # OLE2 directory entries store stream names as UTF-16LE.
    return name.encode("utf-16-le")


def ole_streams(data: bytes) -> set[str]:
    """Names of well-known streams in an OLE2 container (cheap scan, no full parse)."""
    names = ("WordDocument", "Workbook", "Book", "EncryptedPackage", "EncryptionInfo", "PowerPoint Document")
    return {name for name in names if _ole_name(name) in data}


def _zip_format(data: bytes) -> SourceFormat:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            content_types = archive.read("[Content_Types].xml") if "[Content_Types].xml" in names else b""
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError):
        return SourceFormat.UNKNOWN
    if "word/document.xml" in names or b"wordprocessingml.document" in content_types:
        return SourceFormat.DOCX
    if "xl/workbook.xml" in names or b"spreadsheetml.sheet" in content_types:
        return SourceFormat.XLSX
    return SourceFormat.UNKNOWN


def decode_text(data: bytes) -> str | None:
    """Decode bytes that look like text; None for binary content."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in data[:8192]:
        return None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        sample = text[:8192]
        controls = sum(1 for ch in sample if ord(ch) < 32 and ch not in "\t\r\n\f")
        return text if controls <= len(sample) * 0.01 else None
    return None


def looks_like_csv(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()][:50]
    if len(lines) < 2:
        return False
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",;\t|")
    except csv.Error:
        return False
    widths = [len(row) for row in csv.reader(lines, dialect)]
    multi = [w for w in widths if w >= 2]
    # Most rows split into the same number of columns (> 1): a table, not prose.
    return len(multi) >= len(widths) * 0.8 and max(set(multi), key=multi.count) >= 2


def detect_format(data: bytes) -> SourceFormat:
    head = data[:16]
    if data[:1024].lstrip().startswith(b"%PDF") or b"%PDF-" in data[:1024]:
        return SourceFormat.PDF
    if head.startswith(b"\xff\xd8\xff"):
        return SourceFormat.JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return SourceFormat.PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return SourceFormat.WEBP
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return SourceFormat.TIFF
    # "BM" alone also starts plain text ("BMW ..."), so check the DIB header size too.
    if head[:2] == b"BM" and int.from_bytes(data[14:18], "little") in (12, 40, 52, 56, 64, 108, 124):
        return SourceFormat.BMP
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return SourceFormat.HEIC
    if head.startswith(b"PK\x03\x04"):
        return _zip_format(data)
    if head.startswith(_OLE2):
        streams = ole_streams(data)
        if "WordDocument" in streams:
            return SourceFormat.DOC
        if streams & {"Workbook", "Book"}:
            return SourceFormat.XLS
        return SourceFormat.UNKNOWN  # encrypted OOXML and others: the caller inspects further
    text = decode_text(data)
    if text is None or not text.strip():
        return SourceFormat.UNKNOWN
    return SourceFormat.CSV if looks_like_csv(text) else SourceFormat.TXT
