"""Per-type extraction from clean text and noisy OCR-like input. No network, no OCR engine.
All identifiers are synthetic (sample PAN ABCPK1234F, GSTIN with a computed check character)."""

import io

import pytest
from PIL import Image

from app.documents.extract import extract
from app.documents.extract.common import gstin_check_char, gstin_valid, months_between, parse_date, parse_inr, repair_gstin
from app.documents.models import DocumentType, FieldSource, LoadedDocument, LoadStatus, OcrLine, Page, SourceFormat, TextSource

PAN = "ABCPK1234F"
GSTIN = "29ABCPK1234F1Z" + gstin_check_char("29ABCPK1234F1Z")


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(out, format="PNG")
    return out.getvalue()


def text_page(text: str, index: int = 0, source: TextSource = TextSource.NATIVE, tables=None) -> Page:
    return Page(index=index, text=text, text_source=source, tables=tables or [])


def ocr_page(rows: list[list[tuple[str, float]]], index: int = 0, image: bool = True) -> Page:
    """Each row is a list of (text, confidence) boxes printed side by side on one line."""
    lines = []
    for r, boxes in enumerate(rows):
        x = 10.0
        for text, conf in boxes:
            lines.append(OcrLine(text=text, confidence=conf, bbox=(x, 40.0 * r, x + 12 * len(text), 40.0 * r + 20)))
            x += 12 * len(text) + 30
    text = "\n".join(" ".join(t for t, _ in boxes) for boxes in rows)
    return Page(index=index, text=text, text_source=TextSource.OCR, ocr_lines=lines, image_png=png() if image else None)


def doc(*pages: Page) -> LoadedDocument:
    return LoadedDocument(file_name="sample.pdf", sha256="0" * 64, source_format=SourceFormat.PDF, status=LoadStatus.OK, pages=list(pages))


# ---------- building blocks ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,50,000.00", 150000.0), ("₹ 2,500", 2500.0), ("12,34,567.5", 1234567.5), ("2,500.00 Dr", -2500.0), ("(1,000.00)", -1000.0), ("150000", 150000.0), ("abc", None), ("-", None)],
)
def test_indian_number_parsing(raw, expected):
    assert parse_inr(raw) == expected


@pytest.mark.parametrize(("raw", "iso"), [("15/08/1985", "1985-08-15"), ("05-Jul-2025", "2025-07-05"), ("1 April 2026", "2026-04-01"), ("2026-04-01", "2026-04-01"), ("31/02/2025", None)])
def test_date_parsing_is_day_first(raw, iso):
    parsed = parse_date(raw)
    assert (parsed.isoformat() if parsed else None) == iso


def test_gstin_check_character():
    assert gstin_valid("27AAPFU0939F1ZV")  # widely published sample GSTIN
    assert not gstin_valid("27AAPFU0939F1ZW")
    assert gstin_valid(GSTIN)
    assert not gstin_valid("00" + GSTIN[2:])  # no such state code
    # OCR read I for 1 inside the PAN part: positional repair only counts because the check char verifies.
    assert repair_gstin(GSTIN.replace("1234", "I234")) == GSTIN


def test_vintage_month_arithmetic():
    assert months_between(parse_date("01/08/2025"), parse_date("31/10/2026")) == 14
    assert months_between(parse_date("15/08/2025"), parse_date("14/10/2026")) == 13


# ---------- PAN ----------

PAN_TEXT = f"""INCOME TAX DEPARTMENT     GOVT. OF INDIA
स्थायी लेखा संख्या कार्ड
Permanent Account Number Card
{PAN}
नाम / Name
RAVI KUMAR
पिता का नाम / Father's Name
SURESH KUMAR
जन्म की तारीख / Date of Birth
15/08/1985
SAMPLE"""


def test_pan_card_from_text_layer():
    result = extract(doc(text_page(PAN_TEXT)), DocumentType.PAN_CARD)

    assert result.status == "ok" and result.missing == []
    f = result.fields
    assert f["pan"].value == PAN and f["pan"].validated and f["pan"].source == FieldSource.TEXT_LAYER
    assert f["holder_type"].value == "individual" and f["holder_type"].source == FieldSource.COMPUTED
    assert f["name"].value == "RAVI KUMAR" and not f["name"].validated  # free text: no code check alone
    assert f["father_name"].value == "SURESH KUMAR"
    assert f["dob"].value == "1985-08-15"


def test_pan_card_noisy_ocr_side_by_side_labels():
    page = ocr_page([
        [("INCOME TAX DEPARTMENT", 0.9)],
        [("Permanent Account Number", 0.88)],
        [("ABCPKI234F", 0.81)],  # I for 1
        [("Name", 0.95), ("RAVI KUMAR", 0.9)],
        [("Father's Name", 0.93), ("SURESH KUMAR", 0.86)],
        [("Date of Birth", 0.9), ("15/08/1985", 0.83)],
    ])
    result = extract(doc(page), DocumentType.PAN_CARD)

    assert result.fields["pan"].value == PAN
    assert result.fields["pan"].confidence <= 0.6 and "corrected" in result.fields["pan"].note
    assert result.fields["name"].value == "RAVI KUMAR" and result.fields["name"].source == FieldSource.OCR
    assert result.fields["name"].confidence == 0.9  # weakest box on that row
    assert result.fields["father_name"].value == "SURESH KUMAR"


def test_pan_with_bad_shape_goes_to_missing_not_guessed():
    result = extract(doc(text_page(PAN_TEXT.replace(PAN, "ABCP1234F"))), DocumentType.PAN_CARD)
    assert "pan" in result.missing and "pan" not in result.fields
    assert result.status == "partial"


# ---------- Aadhaar ----------

AADHAAR_FRONT = """भारत सरकार
Government of India
रवि कुमार
Ravi Kumar
जन्म तिथि/DOB: 15/08/1985
पुरुष/ MALE
XXXX XXXX 4821
मेरा आधार, मेरी पहचान"""

AADHAAR_BACK = """Unique Identification Authority of India
Address: S/O Suresh Kumar, 12 MG Road,
Indiranagar, Bengaluru, Karnataka - 560038
XXXX XXXX 4821"""


def test_aadhaar_front_and_back():
    result = extract(doc(text_page(AADHAAR_FRONT), text_page(AADHAAR_BACK, 1)), DocumentType.AADHAAR)

    f = result.fields
    assert result.status == "ok"
    assert f["name"].value == "Ravi Kumar"
    assert f["dob"].value == "1985-08-15"
    assert f["gender"].value == "male"
    assert f["aadhaar_last4"].value == "4821"
    assert f["pincode"].value == "560038" and f["address"].page_index == 1
    assert "Indiranagar" in f["address"].value


def test_aadhaar_year_of_birth_only_and_unmasked_number_is_never_kept():
    full = "2345 6789 0124"
    text = AADHAAR_FRONT.replace("जन्म तिथि/DOB: 15/08/1985", "Year of Birth: 1985").replace("XXXX XXXX 4821", full)
    result = extract(doc(text_page(text)), DocumentType.AADHAAR)

    assert result.fields["year_of_birth"].value == 1985
    assert "dob" not in result.missing
    assert result.fields["aadhaar_last4"].value == "0124"
    assert "6789" not in result.model_dump_json()


# ---------- GST REG-06 ----------

GST_TEXT = f"""Government of India
Form GST REG-06
[See Rule 10(1)]
Registration Certificate
Registration Number: {GSTIN}
1. Legal Name RAVI KUMAR
2. Trade Name, if any KUMAR TRADERS
3. Additional trade names, if any
4. Constitution of Business Proprietorship
5. Address of Principal Place of Business 14, Market Road, Jayanagar,
Bengaluru Urban, Karnataka, 560041
6. Date of Liability 01/08/2025
7. Date of Validity From 01/08/2025 To Not Applicable
8. Type of Registration Regular
9. Particulars of Approving Authority
Date of issue of Certificate 05/08/2025
SAMPLE"""


def test_gst_certificate_fields_and_computed_parts():
    result = extract(doc(text_page(GST_TEXT)), DocumentType.GST_CERTIFICATE)

    f = result.fields
    assert result.status == "ok", result.warnings
    assert f["gstin"].value == GSTIN and f["gstin"].validated
    assert f["pan_from_gstin"].value == PAN and f["pan_from_gstin"].source == FieldSource.COMPUTED
    assert f["state_code"].value == "29" and f["state"].value == "Karnataka"
    assert f["legal_name"].value == "RAVI KUMAR"
    assert f["trade_name"].value == "KUMAR TRADERS"
    assert f["constitution_of_business"].value == "proprietorship"
    assert f["registration_date"].value == "2025-08-01" and "validity" in f["registration_date"].note
    assert f["date_of_liability"].value == "2025-08-01"
    assert f["pincode"].value == "560041"
    assert "Jayanagar" in f["address"].value and "Bengaluru Urban" in f["address"].value
    assert f["type_of_registration"].value == "Regular"


def test_gstin_with_wrong_check_character_is_missing_with_reason():
    bad = GSTIN[:-1] + ("A" if GSTIN[-1] != "A" else "B")
    result = extract(doc(text_page(GST_TEXT.replace(GSTIN, bad))), DocumentType.GST_CERTIFICATE)

    assert "gstin" in result.missing and "pan_from_gstin" not in result.fields
    assert any("check character" in w for w in result.warnings)


@pytest.mark.parametrize(
    ("printed", "code"),
    [("Partnership", "partnership"), ("Private Limited Company", "pvt_ltd"), ("Limited Liability Partnership", "llp"), ("Public Limited Company", "public_ltd"), ("Hindu Undivided Family", "huf")],
)
def test_constitution_is_normalised(printed, code):
    result = extract(doc(text_page(GST_TEXT.replace("Proprietorship", printed))), DocumentType.GST_CERTIFICATE)
    assert result.fields["constitution_of_business"].value == code


# ---------- GSTR-3B ----------


def gstr3b_page(months: list[tuple[str, str, str]], index: int = 0) -> Page:
    """months: (financial year, month name, taxable value)."""
    blocks = []
    for fy, month, value in months:
        tax = f"{parse_inr(value) * 0.09:,.2f}"
        blocks.append(
            f"""Form GSTR-3B
[See rule 61(5)]
Year {fy}   Period {month}
1. GSTIN {GSTIN}
2(a). Legal name of the registered person RAVI KUMAR
3.1 Details of Outward Supplies and inward supplies liable to reverse charge
Nature of Supplies  Total Taxable value  Integrated Tax  Central Tax  State/UT Tax  Cess
(a) Outward taxable supplies (other than zero rated, nil rated and exempted)  {value}  0.00  {tax}  {tax}  0.00
(b) Outward taxable supplies (zero rated)  0.00  0.00  0.00  0.00  0.00"""
        )
    return text_page("\n\n".join(blocks), index)


def test_gstr3b_multiple_months_and_computed_total():
    page = gstr3b_page([("2025-26", "December", "90,000.00"), ("2025-26", "January", "1,00,000.00"), ("2025-26", "March", "95,500.50")])
    result = extract(doc(page), DocumentType.GSTR_3B)

    periods = result.tables["periods"]
    assert [p["period"] for p in periods] == ["2025-12", "2026-01", "2026-03"]
    assert periods[1]["taxable_outward_value"] == 100000.0 and periods[1]["cgst"] == 9000.0
    f = result.fields
    assert f["total_taxable_outward_value"].value == 285500.5 and f["total_taxable_outward_value"].source == FieldSource.COMPUTED
    assert f["period_from"].value == "2025-12" and f["period_to"].value == "2026-03" and f["months_filed"].value == 3
    assert any("February 2026" in w or "Feb 2026" in w for w in result.warnings)


def test_gstr3b_from_spreadsheet_table():
    table = [["GSTR-3B summary", ""], ["Tax period", "Taxable value", "IGST", "CGST", "SGST", "Cess"], ["Apr-2026", "1,00,000.00", "0", "9,000.00", "9,000.00", "0"], ["May-2026", "80,000.00", "0", "7,200.00", "7,200.00", "0"]]
    page = text_page(f"GSTIN {GSTIN}\nFinancial Year 2026-27", tables=[table])
    result = extract(doc(page), DocumentType.GSTR_3B)

    assert [p["period"] for p in result.tables["periods"]] == ["2026-04", "2026-05"]
    assert result.fields["total_taxable_outward_value"].value == 180000.0
    assert result.status == "ok"


# ---------- ITR ----------

ITR_TEXT = f"""INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT
[Where the data of the Return of Income in Form ITR-1 (SAHAJ), ITR-2, ITR-3, ITR-4 (SUGAM), ITR-5, ITR-6, ITR-7 filed and verified]
Assessment Year 2025-26
PAN {PAN}
Name RAVI KUMAR
Address 14, Market Road, Bengaluru 560041
Form Number ITR-4
e-Filing Acknowledgement Number 123456789012345
Date of filing 25-Jul-2025
1 Gross Total Income 4,80,000
2 Total Income 4,50,000
3 Net tax payable 0
Gross Turnover / Gross Receipts (44AD) 9,60,000
SAMPLE"""


def test_itr_acknowledgement():
    result = extract(doc(text_page(ITR_TEXT)), DocumentType.ITR)

    f = result.fields
    assert result.status == "ok", result.missing
    assert f["pan"].value == PAN
    assert f["name"].value == "RAVI KUMAR"
    assert f["assessment_year"].value == "2025-26"
    assert f["form_type"].value == "ITR-4"
    assert f["acknowledgement_number"].value == "123456789012345"
    assert f["filing_date"].value == "2025-07-25"
    assert f["gross_total_income"].value == 480000.0
    assert f["total_income"].value == 450000.0
    assert f["tax_payable"].value == 0.0
    assert f["business_turnover"].value == 960000.0


def test_unreadable_document_fails_cleanly():
    bad = LoadedDocument(file_name="x.pdf", sha256="0" * 64, source_format=SourceFormat.PDF, status=LoadStatus.PASSWORD_REQUIRED, message="Password needed")
    result = extract(bad, DocumentType.PAN_CARD)
    assert result.status == "failed" and result.warnings == ["Password needed"] and "pan" in result.missing


def test_page_indexes_select_one_segment_of_a_bundle():
    bundle = doc(text_page(PAN_TEXT, 0), text_page(AADHAAR_FRONT, 1))
    pan = extract(bundle, DocumentType.PAN_CARD, page_indexes=[0])
    aadhaar = extract(bundle, DocumentType.AADHAAR, page_indexes=[1])

    assert pan.fields["name"].value == "RAVI KUMAR" and pan.fields["pan"].page_index == 0
    assert aadhaar.fields["aadhaar_last4"].page_index == 1 and "pan" not in aadhaar.fields
