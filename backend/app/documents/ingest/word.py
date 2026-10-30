"""DOCX loader (python-docx): body text + tables as one page, embedded photos as extra OCR pages.

People paste phone photos of PAN/Aadhaar cards into Word files, so word/media
images are not decoration: each becomes its own page.
"""

from __future__ import annotations

import io
import zipfile

import docx
from docx.table import Table

from app.documents.models import LoadStatus, Page
from app.documents.ports import OcrEngine
from app.documents.ingest.common import IngestError, check_page_count, check_zip, native_page, ocr_page
from app.documents.ingest.images import image_frames

MIN_IMAGE_SIDE = 64  # smaller pictures are icons/logos, not documents


def _table_rows(table: Table) -> list[list[str]]:
    rows = []
    for row in table.rows:
        cells, previous = [], None
        for cell in row.cells:
            # Merged cells repeat the same cell object across the span; keep one.
            if previous is not None and cell._tc is previous:
                continue
            previous = cell._tc
            cells.append(cell.text.strip())
        rows.append(cells)
    return rows


def _body(document: docx.document.Document) -> tuple[str, list[list[list[str]]]]:
    lines: list[str] = []
    tables: list[list[list[str]]] = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            rows = _table_rows(block)
            tables.append(rows)
            lines.extend("\t".join(row) for row in rows)
        elif block.text.strip():
            lines.append(block.text)
    for section in document.sections:
        for part in (section.header, section.footer):
            lines.extend(p.text for p in part.paragraphs if p.text.strip())
    return "\n".join(lines), tables


def _media(data: bytes) -> list[bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = sorted(n for n in archive.namelist() if n.startswith("word/media/"))
        return [archive.read(name) for name in names]


def load_docx(data: bytes, ocr: OcrEngine | None, warnings: list[str]) -> list[Page]:
    check_zip(data)
    text, tables = _body(docx.Document(io.BytesIO(data)))
    pages = [native_page(0, text, tables)]

    images = []
    for blob in _media(data):
        try:
            frames = image_frames(blob)
        except IngestError as exc:
            # EMF/WMF drawings and broken images have nothing to read; an oversized photo
            # might be the PAN card, so say it was skipped.
            if exc.status is LoadStatus.TOO_LARGE:
                warnings.append("An embedded image was too large to process and was skipped.")
            continue
        images.extend(f for f in frames if min(f.size) >= MIN_IMAGE_SIDE)
    check_page_count(1 + len(images))
    if images and ocr is None:
        warnings.append(f"{len(images)} embedded image(s) were not OCR'd or checked for Aadhaar numbers.")
    pages.extend(ocr_page(i + 1, image, ocr, warnings) for i, image in enumerate(images))
    return pages
