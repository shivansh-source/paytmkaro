"""Tabular and plain-text loaders: XLSX (openpyxl), XLS (xlrd), CSV, TXT.

One page per sheet; Page.tables holds the sheet's rows as strings and Page.text
the same rows tab-joined, so the classifier can read a spreadsheet like a page.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections.abc import Iterable
from decimal import Decimal

from app.documents.models import LoadStatus, Page
from app.documents.ingest.common import IngestError, check_page_count, check_zip, native_page
from app.documents.ingest.detect import decode_text

MAX_ROWS_PER_SHEET = 20_000


def format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time(0) else value.isoformat(sep=" ")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        # Round away float noise (0.30000000000000004) without switching to exponent notation.
        return format(Decimal(repr(round(value, 6))), "f").rstrip("0").rstrip(".")
    return str(value).strip()


def _clean_rows(rows: Iterable[Iterable[object]]) -> list[list[str]]:
    out = []
    for row in rows:
        cells = [format_cell(v) for v in row]
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            out.append(cells)
        if len(out) >= MAX_ROWS_PER_SHEET:
            break
    return out


def _sheet_pages(sheets: list[list[list[str]]], warnings: list[str]) -> list[Page]:
    filled = [rows for rows in sheets if rows]
    if any(len(rows) >= MAX_ROWS_PER_SHEET for rows in filled):
        warnings.append(f"Only the first {MAX_ROWS_PER_SHEET} rows of each sheet were read.")
    filled = filled or [[]]
    return [native_page(i, "\n".join("\t".join(r) for r in rows), [rows] if rows else []) for i, rows in enumerate(filled)]


def load_xlsx(data: bytes, warnings: list[str]) -> list[Page]:
    import openpyxl

    check_zip(data)
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise IngestError(LoadStatus.UNREADABLE, "This Excel file is damaged and could not be opened.")
    try:
        check_page_count(len(workbook.worksheets))
        sheets = [_clean_rows(ws.iter_rows(values_only=True)) for ws in workbook.worksheets]
    finally:
        workbook.close()
    return _sheet_pages(sheets, warnings)


def load_xls(data: bytes, warnings: list[str]) -> list[Page]:
    import xlrd

    try:
        book = xlrd.open_workbook(file_contents=data, on_demand=True)
    except xlrd.XLRDError as exc:
        if "encrypt" in str(exc).lower():
            raise IngestError(
                LoadStatus.PASSWORD_REQUIRED,
                "This Excel file is password protected. Open it, remove the password (or save as PDF) and upload again.",
            )
        raise IngestError(LoadStatus.UNREADABLE, "This Excel file is damaged and could not be opened.")
    try:
        check_page_count(book.nsheets)
        sheets = []
        for index in range(book.nsheets):
            sheet = book.sheet_by_index(index)
            rows = []
            for r in range(min(sheet.nrows, MAX_ROWS_PER_SHEET)):
                row = []
                for cell in sheet.row(r):
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                        except (ValueError, OverflowError, xlrd.xldate.XLDateError):
                            row.append(cell.value)
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        row.append(bool(cell.value))
                    elif cell.ctype in (xlrd.XL_CELL_ERROR, xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        row.append(None)
                    else:
                        row.append(cell.value)
                rows.append(row)
            sheets.append(_clean_rows(rows))
    finally:
        book.release_resources()
    return _sheet_pages(sheets, warnings)


def load_csv(data: bytes, warnings: list[str]) -> list[Page]:
    text = decode_text(data) or ""
    sample = "\n".join(text.splitlines()[:20])
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = _clean_rows(csv.reader(io.StringIO(text), dialect))
    return _sheet_pages([rows], warnings)


def load_txt(data: bytes) -> list[Page]:
    text = (decode_text(data) or "").replace("\r\n", "\n")
    return [native_page(0, text)]
