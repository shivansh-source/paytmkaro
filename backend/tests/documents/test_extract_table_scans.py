"""Table-style scans: two-column "Label | Value" tables with top-aligned values and centred labels, mild skew.

No OCR engine runs here. Geometry tests use hand-placed OCR boxes; the *_real_boxes tests use boxes that
PaddleOCR produced from the committed image-only PDFs (tests/fixtures/documents/table_scan_ocr_boxes.json,
regenerate with the fixture script + a RUN_OCR_TESTS run). All data is synthetic.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from app.documents.extract import extract
from app.documents.extract.bank import repair_ifsc
from app.documents.extract.common import _ocr_rows, amount_tokens, gstin_check_char, page_view, parse_inr
from app.documents.ingest import load_document
from app.documents.models import DocumentType, LoadedDocument, LoadStatus, OcrLine, Page, SourceFormat, TextSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
GSTIN = "27ABCDE1234F1Z" + gstin_check_char("27ABCDE1234F1Z")


def page_of(boxes: list[tuple[str, float, float, float, float]], conf: float = 0.95) -> Page:
    lines = [OcrLine(text=t, confidence=conf, bbox=(x0, y0, x1, y1)) for t, x0, y0, x1, y1 in boxes]
    return Page(index=0, text="\n".join(l.text for l in lines), text_source=TextSource.OCR, ocr_lines=lines)


def doc_of(*pages: Page) -> LoadedDocument:
    return LoadedDocument(file_name="scan.pdf", sha256="0" * 64, source_format=SourceFormat.PDF, status=LoadStatus.OK, pages=list(pages))


def table(rows: list[tuple[str, list[str]]], *, top: float = 100.0, pitch: float = 80.0, offset: float = 17.0) -> Page:
    """Label | Value rows as OCR boxes: labels centred in the row, values top-aligned so their centres are
    `offset` px higher. Small filler boxes keep the median box height at 20 px, like a page of table text."""
    boxes = []
    for n, (label, values) in enumerate(rows):
        y = top + n * pitch
        height = 36 + 30 * (len(values) - 1)
        centre = y + height / 2
        boxes.append((label, 60, centre - 18, 60 + 12 * len(label), centre + 18))
        for k, value in enumerate(values):
            boxes.append((value, 420, y - offset + 30 * k, 420 + 12 * len(value), y - offset + 30 * k + 36))
    for k in range(6):
        boxes.append((f"note {k}", 60 + 80 * k, 20, 120 + 80 * k, 40))
    return page_of(boxes)


def lines_of(page: Page) -> list[str]:
    return [l.text for l in _ocr_rows(page)]


# ---------- A. row joining ----------


def test_label_and_top_aligned_value_17px_apart_share_a_row():
    page = table([("Legal Name", ["R. KUMAR"]), ("Trade Name", ["KUMAR TRADERS"])])
    rows = lines_of(page)
    assert "Legal Name  R. KUMAR" in rows
    assert "Trade Name  KUMAR TRADERS" in rows


def test_label_does_not_pick_up_the_next_rows_value():
    rows = [("1. Legal Name", ["R. KUMAR"]), ("2. Trade Name, if any", ["KUMAR TRADERS"]), ("3. Constitution", ["Proprietorship"])]
    result = extract(doc_of(table(rows)), DocumentType.GST_CERTIFICATE)
    assert result.fields["legal_name"].value == "R. KUMAR"
    assert result.fields["trade_name"].value == "KUMAR TRADERS"


def test_text_lines_that_barely_touch_are_not_joined():
    # Two stacked text lines, 6 px overlap on 40 px boxes (15%): different rows.
    page = page_of([("First line of text", 60, 100, 400, 140), ("Second line of text", 60, 134, 400, 174)])
    assert lines_of(page) == ["First line of text", "Second line of text"]


def test_second_line_of_a_wrapped_value_is_its_own_row():
    page = table([("Address", ["12, Market Road,", "Pune, Maharashtra 411001"])])
    rows = lines_of(page)
    assert any(r.startswith("Address") and "12, Market Road," in r and "Pune, Maharashtra 411001" in r for r in rows)


# ---------- B. crop edges ----------


def test_crop_is_widened_by_a_third_of_the_box_height_on_both_sides():
    from app.documents.ocr import EDGE_PAD, _crop, _widen

    poly = np.array([[100, 50], [300, 50], [300, 80], [100, 80]], dtype=np.float32)  # 200 x 30
    widened = _widen(poly)
    pad = EDGE_PAD * 30
    assert widened[0][0] == pytest.approx(100 - pad) and widened[1][0] == pytest.approx(300 + pad)
    assert widened[0][1] == 50 and widened[3][1] == 80  # height untouched
    assert poly[0][0] == 100  # the detector polygon (what OcrLine.bbox is built from) is not modified

    image = np.zeros((200, 500, 3), dtype=np.uint8)
    assert _crop(image, poly).shape[:2] == (30, int(200 + 2 * pad))


def test_margin_never_reaches_into_a_neighbouring_box_on_the_same_line():
    from app.documents.ocr import _room, _widen

    def quad(x0, y0, x1, y1):
        return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)

    box = quad(100, 50, 300, 80)  # height 30: the full margin would be 9 px
    near = quad(306, 50, 400, 80)  # 6 px to the right on the same line
    overlapping = quad(290, 52, 380, 82)  # already overlaps it (an Aadhaar group boundary)
    other_line = quad(302, 120, 400, 150)

    assert _room(box, [box, near]) == (float("inf"), 6.0)
    assert _room(box, [box, other_line]) == (float("inf"), float("inf"))
    widened = _widen(box, room=_room(box, [box, near]))
    assert widened[1][0] == pytest.approx(303) and widened[0][0] == pytest.approx(91)  # half the 6 px gap; free side full
    assert _widen(box, room=_room(box, [box, overlapping]))[1][0] == 300  # no margin into an overlapping neighbour


def test_vertical_strips_are_not_widened():
    from app.documents.ocr import _widen

    poly = np.array([[100, 50], [130, 50], [130, 250], [100, 250]], dtype=np.float32)
    assert (_widen(poly) == poly).all()


# ---------- 1. GST numbered labels ----------


def test_gst_constitution_and_address_under_numbered_labels():
    page = table(
        [
            ("Registration Number", [GSTIN]),
            ("1. Legal Name", ["R. KUMAR"]),
            ("3. Constitution", ["Proprietorship"]),
            ("4. Principal Place of Business", ["12, Market Road,", "Pune, Maharashtra, 411001"]),
            ("5. Date of Liability", ["01/04/2022"]),
        ]
    )
    f = extract(doc_of(page), DocumentType.GST_CERTIFICATE).fields
    assert f["constitution_of_business"].value == "proprietorship"
    assert f["address"].value == "12, Market Road, Pune, Maharashtra, 411001"
    assert f["pincode"].value == "411001"
    assert f["date_of_liability"].value == "2022-04-01"  # the address stops at the next numbered label


def test_gst_certificate_labels_with_and_without_the_words_of_business_still_work():
    text = f"Registration Number: {GSTIN}\n1. Legal Name: R. KUMAR\n3. Constitution of Business: Partnership\n4. Address of Principal Place of Business: 5, MG Road, Pune 411001\n5. Date of Liability: 01/04/2022"
    f = extract(doc_of(Page(index=0, text=text, text_source=TextSource.NATIVE)), DocumentType.GST_CERTIFICATE).fields
    assert f["constitution_of_business"].value == "partnership" and f["pincode"].value == "411001"


# ---------- 2. Aadhaar address ----------


def aadhaar_page(address_rows: list[list[str]]) -> Page:
    rows = [("Name", ["R. Kumar"]), ("DOB", ["15/08/1990"]), ("Gender", ["Male"]), ("Address", address_rows[0]), ("Aadhaar Number", ["XXXX XXXX 0124"])]
    return table(rows)


def test_aadhaar_two_line_address_in_a_table_scan():
    f = extract(doc_of(aadhaar_page([["S/O Suresh Kumar, 12, Market Road,", "Shivaji Nagar, Pune, Maharashtra - 411001"]])), DocumentType.AADHAAR).fields
    assert f["address"].value == "S/O Suresh Kumar, 12, Market Road, Shivaji Nagar, Pune, Maharashtra - 411001"
    assert f["pincode"].value == "411001"
    assert f["aadhaar_last4"].value == "0124"


def lines_page(lines: list[str]) -> Page:
    return Page(index=0, text="\n".join(lines), text_source=TextSource.NATIVE)


def test_aadhaar_address_runs_to_the_pincode_line_whatever_the_wording():
    # 'Vidya' contains 'vid', 'India' is a header word: neither ends the address.
    page = lines_page(["Name: R. Kumar", "DOB: 15/08/1990", "Address: S/O Suresh Kumar, 12, Market Road,", "Vidya Nagar, Pune,", "Maharashtra, India", "PIN Code: 411001", "Mobile: 98XXXXXX10", "XXXX XXXX 0124"])
    f = extract(doc_of(page), DocumentType.AADHAAR).fields
    assert "Vidya Nagar" in f["address"].value and "Maharashtra, India" in f["address"].value and f["address"].value.endswith("411001")
    assert f["pincode"].value == "411001" and "Mobile" not in f["address"].value


def test_aadhaar_hindi_label_and_bilingual_label():
    page = lines_page(["पता: Address: C/O Ravi, 5 Gandhi Road,", "Bengaluru, Karnataka - 560038", "VID: 9123 4567 8901 2345"])
    f = extract(doc_of(page), DocumentType.AADHAAR).fields
    assert f["address"].value == "C/O Ravi, 5 Gandhi Road, Bengaluru, Karnataka - 560038" and f["pincode"].value == "560038"


def test_encrypted_e_aadhaar_that_prints_an_address_is_read():
    data = (FIXTURES / "e_aadhaar_with_address.pdf").read_bytes()
    result = extract(load_document(data, "e.pdf", password="KUMA1990"), DocumentType.AADHAAR)
    f = result.fields
    assert f["address"].value.startswith("S/O Suresh Kumar") and "Vidya Nagar" in f["address"].value
    assert f["pincode"].value == "411001" and f["aadhaar_last4"].value == "0124"
    assert "2345" not in json.dumps({k: v.value for k, v in f.items()})  # only the last 4 digits exist


def test_the_original_e_aadhaar_fixture_prints_no_address_so_none_is_read():
    data = (FIXTURES / "e_aadhaar_encrypted.pdf").read_bytes()
    result = extract(load_document(data, "e.pdf", password="KUMA1990"), DocumentType.AADHAAR)
    assert "address" not in result.fields and "pincode" not in result.fields  # missing, never guessed


# ---------- 3. GSTR-3B month row ----------


def gstr3b_page(row_label: str = "(a) Outward taxable supplies") -> Page:
    cols = [60, 400, 520, 620, 730, 830]
    boxes = []
    for n, text in enumerate([f"GSTIN: {GSTIN}", "Financial Year: 2026-27", "Tax Period: April 2026"]):
        boxes.append((text, 60, 100 + 40 * n, 460, 130 + 40 * n))
    boxes.append(("3.1 Details of outward supplies", 60, 240, 500, 270))
    for text, x in zip(["Nature of Supplies", "Taxable value", "IGST", "CGST", "SGST", "Cess"], cols):
        boxes.append((text, x, 300, x + 10 * len(text), 330))
    for text, x in zip([row_label, "6,58,000.00", "0.00", "59,220.00", "59,220.00", "0.00"], cols):
        boxes.append((text, x, 340, x + 10 * len(text), 370))
    boxes.append(("(other than zero rated, nil rated and exempted)", 60, 372, 520, 400))
    return page_of(boxes)


@pytest.mark.parametrize("label", ["(a) Outward taxable supplies", "3.1(a) Outward taxable supplies", "3.1 (a) Outward taxable supplies"])
def test_gstr3b_month_row_goes_into_periods(label):
    result = extract(doc_of(gstr3b_page(label)), DocumentType.GSTR_3B)
    [period] = result.tables["periods"]
    assert period["period"] == "2026-04" and period["taxable_outward_value"] == 658000.0
    assert (period["igst"], period["cgst"], period["sgst"], period["cess"]) == (0.0, 59220.0, 59220.0, 0.0)
    assert result.fields["period_from"].value == "2026-04" and result.status == "ok"


def test_gstr3b_period_label_with_the_month_on_the_next_line():
    page = lines_page(["Financial Year: 2026-27", "Tax Period", "April 2026", "(a) Outward taxable supplies (other than zero rated)  6,58,000.00  0.00  59,220.00  59,220.00  0.00"])
    [period] = extract(doc_of(page), DocumentType.GSTR_3B).tables["periods"]
    assert period["period"] == "2026-04" and period["taxable_outward_value"] == 658000.0


# ---------- 4. bank rows from OCR boxes in columns ----------


def statement_page(debit_text: str = "Rs658,000.00") -> Page:
    cols = [40, 140, 400, 530, 690]
    rows = [
        ("01/04/2026", "Opening balance", "", "", "1,50,000.00"),
        ("03/04/2026", "UPI/412345678901/Sale proceeds", "", debit_text, "8,08,000.00"),
        ("07/04/2026", "NEFT/DEMO0002/Rent April", "18,000.00", "", "7,90,000.00"),
    ]
    boxes = [("DEMO BANK A - Statement of Account", 40, 40, 600, 70), ("Account No: XXXXXXXX4321 IFSC: DEM00001234", 40, 100, 600, 130), ("Period: 01-04-2026 to 30-04-2026", 40, 140, 600, 170)]
    for text, x in zip(["Date", "Narration", "Debit", "Credit", "Balance"], cols):
        boxes.append((text, x, 210, x + 10 * len(text), 240))
    for n, cells in enumerate(rows):
        for text, x in zip(cells, cols):
            if text:
                boxes.append((text, x, 260 + 40 * n, x + 10 * len(text), 290 + 40 * n))
    return page_of(boxes)


def test_scanned_statement_rows_from_column_boxes():
    result = extract(doc_of(statement_page()), DocumentType.BANK_STATEMENT)
    rows = result.tables["transactions"]
    assert [(r["date"], r["debit"], r["credit"], r["balance"]) for r in rows] == [
        ("2026-04-03", None, 658000.0, 808000.0),
        ("2026-04-07", 18000.0, None, 790000.0),
    ]
    assert all(r["balance_ok"] for r in rows) and result.fields["total_credits"].value == 658000.0


def test_scanned_statement_ifsc_with_letter_o_read_as_zero_is_repaired_and_flagged():
    result = extract(doc_of(statement_page()), DocumentType.BANK_STATEMENT)
    ifsc = result.fields["ifsc"]
    assert ifsc.value == "DEMO0001234" and ifsc.confidence <= 0.6
    assert "DEM00001234" in (ifsc.note or "")  # the as-read string is kept in the note
    from app.documents.extract import extract_detailed

    assert extract_detailed(doc_of(statement_page()), DocumentType.BANK_STATEMENT).raw["ifsc"] == "DEM00001234"


# ---------- 5. IFSC repair ----------


@pytest.mark.parametrize(
    ("raw", "fixed"),
    [("DEM00001234", "DEMO0001234"), ("DEMO0001234", "DEMO0001234"), ("HDFCO001234", "HDFC0001234"), ("5BIN0001234", "SBIN0001234"), ("SBIN0O01234", "SBIN0O01234"), ("DEMO000123", "DEMO000123")],
)
def test_ifsc_repair_by_position(raw, fixed):
    assert repair_ifsc(raw) == fixed  # only the first five positions are repaired; the last six are free


def test_ifsc_is_only_repaired_next_to_its_label():
    lines = ["Reference DEM00001234 for the NEFT", "Opening Balance: 1,000.00"]
    assert "ifsc" not in extract(doc_of(lines_page(lines)), DocumentType.BANK_STATEMENT).fields


# ---------- 6. currency prefixes ----------


@pytest.mark.parametrize(
    "raw", ["Rs658,000.00", "Rs.658,000.00", "INR658,000.00", "₹658,000.00", "Rs 6,58,000", "Rs. 6,58,000.00", "INR 6,58,000", "Rs.6,58,000/-", "rs658000", "₹ 6,58,000.00"]
)
def test_currency_prefixes_parse(raw):
    assert parse_inr(raw) == 658000.0


@pytest.mark.parametrize("raw", ["Rs", "Rs.", "INR", "Rsabc", "6,58,0O0", "Rs 12 34 56x", "", None])
def test_unparseable_amounts_are_none_never_zero(raw):
    assert parse_inr(raw) is None


def test_glued_currency_prefix_is_one_amount_token_not_a_zero_tail():
    assert [t.group(0) for t in amount_tokens("UPI sale Rs658,000.00 8,08,000.00")] == ["Rs658,000.00", "8,08,000.00"]
    assert [t.group(0) for t in amount_tokens("INR6,58,000.00 Cr")] == ["INR6,58,000.00 Cr"]
    assert [t.group(0) for t in amount_tokens("1,50,000.00 2500.50")] == ["1,50,000.00", "2500.50"]


def test_unreadable_statement_amount_is_reported_and_left_empty():
    lines = [
        "Opening Balance: 1,50,000.00",
        "03/04/2026 UPI/SALE 1,000.00 1,51,000.00",
        "04/04/2026 NEFT/RENT 5,000.00 1,46,000.00",
    ]
    page = lines_page(lines)
    page.tables = [[["Date", "Narration", "Debit", "Credit", "Balance"], ["03/04/2026", "UPI/SALE", "", "Rs 1O,000", "1,60,000.00"]]]
    result = extract(doc_of(page), DocumentType.BANK_STATEMENT)
    [row] = result.tables["transactions"]
    assert row["credit"] is None and row["debit"] is None and row["balance_ok"] is None
    assert any("could not be read as an amount" in w for w in result.warnings)


# ---------- 7. bureau score printed large in a box ----------


def bureau(*rows: str) -> LoadedDocument:
    return doc_of(lines_page(["DEMO CREDIT BUREAU - Consumer Credit Report", *rows, "Name  R. KUMAR", "Report date  12/06/2026"]))


def test_boxed_score_below_its_caption():
    f = extract(bureau("DEMO CREDIT SCORE", "742"), DocumentType.BUREAU_REPORT).fields
    assert f["score"].value == 742 and "caption" in f["score"].note


def test_boxed_score_above_its_caption():
    assert extract(bureau("742", "Your Credit Score"), DocumentType.BUREAU_REPORT).fields["score"].value == 742


def test_scale_ends_are_not_the_score():
    assert "score" not in extract(bureau("CIBIL Score", "300", "900"), DocumentType.BUREAU_REPORT).fields
    assert "score" not in extract(bureau("Credit Score", "900"), DocumentType.BUREAU_REPORT).fields


def test_cmr_rank_is_never_the_score():
    assert "score" not in extract(bureau("CMR Rank", "4"), DocumentType.BUREAU_REPORT).fields
    result = extract(bureau("CMR Rank 4", "Commercial Credit Score"), DocumentType.BUREAU_REPORT)
    assert "score" not in result.fields and result.fields["cmr_rank"].value == 4


def test_a_three_digit_number_from_an_unrelated_context_is_not_the_score():
    result = extract(bureau("Enquiries in last 90 days", "512", "Credit Score range", "300 - 900"), DocumentType.BUREAU_REPORT)
    assert "score" not in result.fields
    assert "score" not in extract(bureau("Total accounts 6", "Branch code", "742"), DocumentType.BUREAU_REPORT).fields


def test_two_different_candidates_are_ambiguous_so_nothing_is_read():
    assert "score" not in extract(bureau("742", "CIBIL Score", "688"), DocumentType.BUREAU_REPORT).fields


def test_score_printed_on_the_caption_line_still_works():
    assert extract(bureau("CIBIL Score: 705"), DocumentType.BUREAU_REPORT).fields["score"].value == 705


# ---------- real PaddleOCR boxes from the committed image-only PDFs ----------


def real_doc(name: str) -> LoadedDocument:
    packed = json.loads((FIXTURES / "table_scan_ocr_boxes.json").read_text(encoding="utf-8"))
    pages = []
    for i, boxes in enumerate(packed[name]):
        lines = [OcrLine(text=t, confidence=c, bbox=tuple(b)) for t, c, b in boxes]
        pages.append(Page(index=i, text="\n".join(l.text for l in lines), text_source=TextSource.OCR, ocr_lines=lines))
    return doc_of(*pages)


def test_gst_table_scan_real_boxes():
    f = extract(real_doc("gst_reg06_table_scan"), DocumentType.GST_CERTIFICATE).fields
    assert f["gstin"].value == GSTIN and f["legal_name"].value.replace(" ", "") == "R.KUMAR"
    assert f["trade_name"].value == "KUMAR TRADERS" and f["constitution_of_business"].value == "proprietorship"
    assert f["address"].value == "12, Market Road, Pune, Maharashtra, 411001" and f["pincode"].value == "411001"
    assert f["legal_name"].value != f["trade_name"].value


def test_udyam_table_scan_real_boxes():
    f = extract(real_doc("udyam_table_scan"), DocumentType.UDYAM_CERTIFICATE).fields
    assert f["enterprise_name"].value == "KUMAR TRADERS" and f["enterprise_type"].value == "small"
    assert f["address"].value == "12, Market Road, Pune, Maharashtra 411001" and f["udyam_number"].value == "UDYAM-MH-00-1234567"


def test_gstr3b_table_scan_real_boxes():
    [period] = extract(real_doc("gstr3b_table_scan"), DocumentType.GSTR_3B).tables["periods"]
    assert period["period"] == "2026-04" and period["taxable_outward_value"] == 658000.0 and period["cgst"] == 59220.0


def test_bank_statement_scan_real_boxes():
    result = extract(real_doc("bank_statement_table_scan"), DocumentType.BANK_STATEMENT)
    rows = result.tables["transactions"]
    assert [r["credit"] for r in rows if r["credit"]] == [658000.0] and len(rows) == 3
    assert all(r["balance_ok"] for r in rows) and result.fields["ifsc"].value == "DEMO0001234"


def test_bureau_scan_real_boxes_reads_the_boxed_score_not_the_cmr_rank():
    f = extract(real_doc("bureau_report_boxed_score"), DocumentType.BUREAU_REPORT).fields
    assert f["score"].value == 742 and f["cmr_rank"].value == 4
