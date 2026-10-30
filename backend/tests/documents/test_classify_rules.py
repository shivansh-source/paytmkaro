"""Rule-based classifier on a small synthetic OCR-style corpus (no files, no network).

All samples are SAMPLE data: fictional names, PAN/GSTIN made up, Aadhaar already masked
the way ingest masks it ("XXXX XXXX 1234").
"""

from __future__ import annotations

import time

import pytest

from app.documents.classify import classify
from app.documents.classify.rules import MIN_CONFIDENCE, confidence_from_scores, score_page
from app.documents.classify.signals import extract_features
from app.documents.models import DocumentType as T
from app.documents.models import LoadedDocument, LoadStatus, OcrLine, Page, SourceFormat, TextSource

# ---------- corpus: clean text ----------

PAN_CLEAN = """SAMPLE
INCOME TAX DEPARTMENT        GOVT. OF INDIA
Permanent Account Number Card
ABCPK1234L
Name
RAVI KUMAR
Father's Name
SURESH KUMAR
Date of Birth
15/08/1985
Signature"""

AADHAAR_FRONT_CLEAN = """SAMPLE
Government of India
Ravi Kumar
DOB: 15/08/1985
Male
XXXX XXXX 4821
VID : XXXX XXXX 7710 0000
Aadhaar - Aam Admi ka Adhikar"""

AADHAAR_BACK_CLEAN = """SAMPLE
Unique Identification Authority of India
Address: S/O Suresh Kumar, 12 MG Road,
Indiranagar, Bengaluru, Karnataka - 560038
XXXX XXXX 4821
help@uidai.gov.in | www.uidai.gov.in
1800 300 1947"""

GST_CERT_CLEAN = """SAMPLE
Government of India
Form GST REG-06
[See Rule 10(1)]
Registration Certificate
Registration Number : 27ABCPK1234L1Z5
1. Legal Name : RAVI KUMAR
2. Trade Name, if any : KUMAR TRADERS
3. Constitution of Business : Proprietorship
4. Address of Principal Place of Business : 4 Market Yard, Pune, Maharashtra 411037
5. Date of Liability : 01/07/2017
6. Period of Validity From 01/07/2017 To Not Applicable
7. Type of Registration : Regular
8. Particulars of Approving Authority : Superintendent"""

GSTR3B_CLEAN = """SAMPLE
Form GSTR-3B
[See rule 61(5)]
Year 2024-25   Period: June
1. GSTIN 27ABCPK1234L1Z5
2(a). Legal name of the registered person  RAVI KUMAR
2(b). Trade name, if any  KUMAR TRADERS
3.1 Details of Outward Supplies and inward supplies liable to reverse charge
Nature of Supplies  Total Taxable value  Integrated Tax  Central Tax  State/UT Tax  Cess
(a) Outward taxable supplies (other than zero rated, nil rated and exempted)  8,45,000.00  0.00  76,050.00  76,050.00  0.00
4. Eligible ITC
(A) ITC Available  0.00  41,200.00  41,200.00
6.1 Payment of tax"""

ITR_CLEAN = """SAMPLE
INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT
[Where the data of the Return of Income in Form ITR-1 (SAHAJ), ITR-2, ITR-3, ITR-4 (SUGAM) filed]
Assessment Year 2024-25
PAN ABCPK1234L
Name RAVI KUMAR
Aadhaar Number XXXX XXXX 4821
Form Number ITR-4
e-Filing Acknowledgement Number 123456789012345
Date of filing 28-Jul-2024
Gross Total Income 9,80,000
Deductions under Chapter VI-A 1,50,000
Total Income 8,30,000
Total tax payable 45,760
Taxes Paid 45,760"""

BANK_PAGE_1 = """SAMPLE
DEMO BANK A
Statement of Account
Account Name: KUMAR TRADERS     Account No: XXXXXXX4532
IFSC: DEMO0001234     MICR: 411002005     Branch: Pune Camp
Statement Period: 01/04/2024 to 30/06/2024
Date        Narration                     Chq/Ref No     Withdrawal    Deposit      Balance
            Opening Balance                                                         1,25,400.00
01/04/2024  UPI/RAJESH/PAYMENT            410112345678                 12,500.00    1,37,900.00
02/04/2024  NEFT-ACME SUPPLIES            N09234          45,000.00                   92,900.00
03/04/2024  IMPS/P2A/SHARMA               409812345111                  8,200.00    1,01,100.00
05/04/2024  ATM WDL PUNE CAMP             000123          10,000.00                   91,100.00"""

BANK_ROWS_ONLY = """08/04/2024  UPI/RAMESH/GOODS              410845612345                  6,400.00      97,500.00
09/04/2024  NEFT-STEEL HOUSE              N09877          22,000.00                   75,500.00
10/04/2024  UPI/SURESH/PAYMENT            410998812345                 15,750.00      91,250.00
12/04/2024  IMPS/P2A/VERMA                410211223344                  9,900.00    1,01,150.00
15/04/2024  CHQ DEP 004512                004512                       30,000.00    1,31,150.00
18/04/2024  RTGS-MEHTA METALS             RTGS0098        60,000.00                   71,150.00
20/04/2024  UPI/ANIL/RENT                 411012121212    12,000.00                   59,150.00
22/04/2024  NEFT-ACME SUPPLIES            N09901                       48,500.00    1,07,650.00
25/04/2024  POS DEMO MART                 POS7788          3,450.00                 1,04,200.00"""

BANK_ROWS_CLOSING = BANK_ROWS_ONLY.replace("2024", "2O24").lower() + "\nclosing balance 1,04,200.00"

# ---------- corpus: noisy OCR (dropped spaces, O/0 and I/1 swaps, lowercase) ----------

PAN_NOISY = """lNCOME TAX DEPARTMENT G0VT.0F lNDlA
Permanent Acc0unt Numbcr Card
ABCPK I234L
Narne RAVl KUMAR
Fathers Narne SURESH KUMAR"""

AADHAAR_NOISY = """g0vernment0f india
uniqueidentificati0nauth0rityofindia
D0B:15/08/1985 MALE
xxxx xxxx 4821
he1p@uidai.gov.in"""

GST_CERT_NOISY = """f0rm gst reg-06
registrati0n certiflcate
reg no 27 ABCPK1234L 1Z5
constitutionofbusiness propriet0rship
dateofliability 01/07/2017
typeofregistrati0n regular"""

GSTR3B_NOISY = """f0rm gstr-3b
gstin 27ABCPK1234L1Z5
outwardtaxab1esupplies 8,45,000.00
e1igib1e itc 41,200.00
integrated tax central tax"""

ITR_NOISY = """lNDlAN lNC0ME TAX RETURN ACKN0WLEDGEMENT
assessmentyear 2024-25
itr-v
grosstota1income 9,80,000
PAN ABCPK1234L"""

BANK_NOISY = """statementofacc0unt
ifsc DEMO0001234
0pening ba1ance 1,25,400.00
01/04/2024 upi/rajesh 12,500.00 1,37,900.00
02/04/2024 neft-acme 45,000.00 92,900.00
03/04/2024 imps/sharma 8,200.00 1,01,100.00"""

# ---------- corpus: Hindi-only ----------

AADHAAR_HINDI = """भारत सरकार
भारतीय विशिष्ट पहचान प्राधिकरण
रवि कुमार
जन्म तिथि: 15/08/1985
पुरुष
XXXX XXXX 4821
मेरा आधार, मेरी पहचान"""

PAN_HINDI = """आयकर विभाग        भारत सरकार
स्थायी लेखा संख्या कार्ड
ABCPK1234L
नाम रवि कुमार
पिता का नाम सुरेश कुमार
हस्ताक्षर"""


def doc(*texts: str, status: LoadStatus = LoadStatus.OK, tables: dict[int, list] | None = None) -> LoadedDocument:
    tables = tables or {}
    return LoadedDocument(
        file_name="sample.pdf",
        sha256="0" * 64,
        source_format=SourceFormat.PDF,
        status=status,
        pages=[
            Page(index=i, text=t, text_source=TextSource.OCR if t else TextSource.NONE, tables=tables.get(i, []))
            for i, t in enumerate(texts)
        ],
    )


def page_type(text: str) -> T:
    result = classify(doc(text))
    return result.pages[0].document_type


CLEAN = [
    (PAN_CLEAN, T.PAN_CARD),
    (AADHAAR_FRONT_CLEAN, T.AADHAAR),
    (AADHAAR_BACK_CLEAN, T.AADHAAR),
    (GST_CERT_CLEAN, T.GST_CERTIFICATE),
    (GSTR3B_CLEAN, T.GSTR_3B),
    (ITR_CLEAN, T.ITR),
    (BANK_PAGE_1, T.BANK_STATEMENT),
    (BANK_ROWS_ONLY, T.BANK_STATEMENT),
]
NOISY = [
    (PAN_NOISY, T.PAN_CARD),
    (AADHAAR_NOISY, T.AADHAAR),
    (GST_CERT_NOISY, T.GST_CERTIFICATE),
    (GSTR3B_NOISY, T.GSTR_3B),
    (ITR_NOISY, T.ITR),
    (BANK_NOISY, T.BANK_STATEMENT),
]


@pytest.mark.parametrize(("text", "expected"), CLEAN, ids=[e.value + str(i) for i, (_, e) in enumerate(CLEAN)])
def test_clean_english_samples(text, expected):
    result = classify(doc(text))
    page = result.pages[0]
    assert page.document_type == expected, page.signals
    assert page.confidence >= MIN_CONFIDENCE
    assert page.signals  # explainable
    assert result.document_type == expected
    assert result.method == "rules"


@pytest.mark.parametrize(("text", "expected"), NOISY, ids=[e.value for _, e in NOISY])
def test_noisy_ocr_samples(text, expected):
    page = classify(doc(text)).pages[0]
    assert page.document_type == expected, page.signals


@pytest.mark.parametrize(("text", "expected"), [(AADHAAR_HINDI, T.AADHAAR), (PAN_HINDI, T.PAN_CARD)])
def test_hindi_only_samples(text, expected):
    page = classify(doc(text)).pages[0]
    assert page.document_type == expected, page.signals
    # Signals name the Hindi phrase that matched, not its English twin.
    assert any(any("ऀ" <= ch <= "ॿ" for ch in s) for s in page.signals)


def test_pan_inside_gstin_does_not_count_for_pan_card():
    assert extract_features("ABCPK1234L", [])["pan"] == 1  # control: a bare PAN counts
    assert extract_features(GST_CERT_CLEAN, [])["pan"] == 0
    assert extract_features("Registration Number 27 ABCPK1234L 1Z5", [])["pan"] == 0  # OCR-spaced GSTIN
    assert extract_features("GSTIN 27ABCPK1234L1Z5  Proprietor PAN ABCPK1234L", [])["pan"] == 1
    score = score_page(Page(index=0, text=GST_CERT_CLEAN))
    assert score.scores.get(T.PAN_CARD, 0) <= 1  # only "Government of India"
    page = classify(doc(GST_CERT_CLEAN)).pages[0]
    assert page.document_type == T.GST_CERTIFICATE
    assert "pattern: GSTIN" in page.signals


def test_itr_with_pan_and_masked_aadhaar_stays_itr():
    page = classify(doc(ITR_CLEAN)).pages[0]
    assert page.document_type == T.ITR
    assert page.confidence > 0.8


def test_amounts_do_not_fake_aadhaar_or_gstr3b_signals():
    text = (
        BANK_PAGE_1
        + "\n26/04/2024  UPI/HARI/PAYMENT  411100001947  1,947.00  1,03,153.00"
        + "\n27/04/2024  CHQ  18,003.00 1,947.00  3.10"
        + "\nAccount No: XXXXXXXX4532"  # bank-style mask, not ingest's Aadhaar mask
    )
    score = score_page(Page(index=0, text=text))
    assert score.label == T.BANK_STATEMENT
    assert T.AADHAAR not in score.scores
    assert T.GSTR_3B not in score.scores
    assert extract_features("1800 300 1947", [])["uidai_helpline"] == 1


def test_spreadsheet_page_with_bank_headers_in_tables():
    table = [
        ["Txn Date", "Description", "Ref No", "Debit", "Credit", "Balance"],
        ["01-04-2024", "UPI/RAJESH/PAYMENT", "410112345678", "", "12,500.00", "1,37,900.00"],
        ["02-04-2024", "NEFT-ACME SUPPLIES", "N09234", "45,000.00", "", "92,900.00"],
        ["03-04-2024", "IMPS/P2A/SHARMA", "409812345111", "", "8,200.00", "1,01,100.00"],
    ]
    result = classify(doc("", tables={0: [table]}))
    page = result.pages[0]
    assert page.document_type == T.BANK_STATEMENT, page.signals
    assert "table: bank statement column headers" in page.signals


def test_id_patterns_in_table_cells_count():
    table = [["Account Name", "KUMAR TRADERS"], ["IFSC", "DEMO0001234"], ["GSTIN", "27ABCPK1234L1Z5"]]
    counts = extract_features("", [" | ".join(row) for row in table])
    assert counts["ifsc"] == 1 and counts["gstin"] == 1 and counts["pan"] == 0


def test_scanned_statement_with_one_ocr_box_per_cell():
    """Ingest joins OCR boxes with newlines, so a row's date and amounts are on separate
    lines of Page.text; rows are rebuilt from box positions."""
    cells = [
        ["Date", "Narration", "Chq/Ref No", "Withdrawal", "Deposit", "Balance"],
        ["01/04/2024", "SALARY CREDIT", "000111", "", "12,500.00", "1,37,900.00"],
        ["02/04/2024", "CASH WDL", "000112", "45,000.00", "", "92,900.00"],
        ["03/04/2024", "CHQ DEP", "000113", "", "8,200.00", "1,01,100.00"],
        ["05/04/2024", "CASH WDL", "000114", "10,000.00", "", "91,100.00"],
    ]
    lines = [
        OcrLine(text=cell, confidence=0.9, bbox=(x * 120, y * 30 + (x % 2) * 3, x * 120 + 100, y * 30 + 20))
        for y, row in enumerate(cells)
        for x, cell in enumerate(row)
        if cell
    ]
    text = "\n".join(line.text for line in lines)
    assert extract_features(text, [])["txn_rows"] == 0  # per-box text alone has no rows
    page = Page(index=0, text=text, text_source=TextSource.OCR, ocr_lines=lines)
    score = score_page(page)
    assert score.label == T.BANK_STATEMENT
    assert "table: bank statement column headers" in score.signal_labels(T.BANK_STATEMENT)
    assert "rows: 4 dated rows with amounts" in score.signal_labels(T.BANK_STATEMENT)


@pytest.mark.parametrize("text", ["", "   \n  ", "SAMPLE\nThank you for visiting.\nPage 3 of 3"])
def test_blank_or_irrelevant_page_is_unknown(text):
    result = classify(doc(text))
    assert result.pages[0].document_type == T.UNKNOWN
    assert result.pages[0].confidence == 0
    assert result.document_type == T.UNKNOWN
    assert result.confidence == 0
    assert result.segments[0].document_type == T.UNKNOWN


@pytest.mark.parametrize("status", [s for s in LoadStatus if s is not LoadStatus.OK])
def test_non_ok_status_passes_through(status):
    loaded = LoadedDocument(
        file_name="locked.pdf",
        sha256="0" * 64,
        source_format=SourceFormat.PDF,
        status=status,
        message="Enter the PDF password",
    )
    result = classify(loaded)
    assert result.status == status
    assert result.message == "Enter the PDF password"
    assert (result.document_type, result.confidence, result.method) == (T.UNKNOWN, 0, "none")
    assert result.pages == [] and result.segments == []


# ---------- segments ----------


def test_bundled_pdf_is_split_into_segments():
    result = classify(
        doc(PAN_CLEAN, AADHAAR_FRONT_CLEAN, AADHAAR_BACK_CLEAN, BANK_PAGE_1, BANK_ROWS_ONLY, BANK_ROWS_CLOSING)
    )
    assert [(s.document_type, s.page_indexes) for s in result.segments] == [
        (T.PAN_CARD, [0]),
        (T.AADHAAR, [1, 2]),
        (T.BANK_STATEMENT, [3, 4, 5]),
    ]
    assert result.document_type == T.BANK_STATEMENT  # most pages
    assert result.method == "rules"


def test_weak_page_between_same_type_pages_joins_them():
    result = classify(doc(BANK_PAGE_1, "", BANK_ROWS_ONLY))
    assert [(s.document_type, s.page_indexes) for s in result.segments] == [(T.BANK_STATEMENT, [0, 1, 2])]
    middle = result.pages[1]
    assert middle.signals[0].startswith("context:")
    assert 0 < middle.confidence < result.pages[0].confidence


def test_page_pointing_elsewhere_is_not_absorbed_between_same_type_pages():
    weak_aadhaar = "पता: बेंगलुरु\nDOB"  # weak Aadhaar evidence, below the threshold
    result = classify(doc(BANK_PAGE_1, weak_aadhaar, BANK_ROWS_ONLY))
    assert result.pages[1].document_type == T.UNKNOWN
    assert "best guess: aadhaar" in result.pages[1].signals[1]


def test_weak_page_between_different_types_stays_unknown():
    result = classify(doc(PAN_CLEAN, "", BANK_PAGE_1))
    assert [s.document_type for s in result.segments] == [T.PAN_CARD, T.UNKNOWN, T.BANK_STATEMENT]


def test_weak_aadhaar_back_joins_front():
    weak_back = "Address: S/O Suresh Kumar, 12 MG Road, Bengaluru 560038\nपता: बेंगलुरु"
    result = classify(doc(AADHAAR_FRONT_CLEAN, weak_back))
    assert [(s.document_type, s.page_indexes) for s in result.segments] == [(T.AADHAAR, [0, 1])]


def test_segments_cover_every_page_once():
    texts = [PAN_CLEAN, "", AADHAAR_FRONT_CLEAN, "nothing here", GSTR3B_CLEAN, "", "", "", ITR_CLEAN]
    result = classify(doc(*texts))
    covered = [i for s in result.segments for i in s.page_indexes]
    assert covered == list(range(len(texts)))


def test_dominant_type_tie_breaks_on_confidence():
    result = classify(doc(PAN_NOISY, ITR_CLEAN))
    assert result.document_type == max(result.pages, key=lambda p: p.confidence).document_type


# ---------- confidence formula ----------


def test_confidence_rewards_evidence_and_margin():
    assert confidence_from_scores(0, 0) == 0
    assert confidence_from_scores(10, 0) > confidence_from_scores(4, 0)  # more evidence
    assert confidence_from_scores(10, 0) > confidence_from_scores(10, 6)  # clearer winner
    assert confidence_from_scores(7, 0) == pytest.approx(0.826, abs=0.001)
    assert 0 <= confidence_from_scores(100, 100) <= 0.5


def test_forty_page_statement_is_fast():
    pages = [BANK_PAGE_1] + [BANK_ROWS_ONLY * 4] * 39
    start = time.perf_counter()
    result = classify(doc(*pages))
    elapsed = time.perf_counter() - start
    assert result.segments[0].page_indexes == list(range(40))
    assert elapsed < 5, f"{elapsed:.2f}s"


# ---------- look-alike documents we don't support ----------

LOOKALIKES = {
    "tax_invoice": """TAX INVOICE
Kumar Traders  GSTIN: 27ABCPK1234L1Z5
Invoice No: 112  Date: 12/04/2024
Bill To: Acme Supplies GSTIN 29AAACA1234B1Z2
Steel rods  10  450.00  4,500.00
CGST 9% 405.00  SGST 9% 405.00  Total 5,310.00
Bank: Demo Bank A  A/c No 123456  IFSC DEMO0001234""",
    "udyog_aadhaar": """UDYOG AADHAAR MEMORANDUM
Government of India Ministry of MSME
Udyog Aadhaar Number MH26A0012345
Name of Enterprise KUMAR TRADERS  Type of Enterprise MICRO""",
    "form_16": """FORM NO. 16 Certificate under section 203 of the Income-tax Act, 1961
PAN of the Employee ABCPK1234L  Assessment Year 2024-25
Gross Salary 9,80,000  Total Income 8,30,000  Tax payable 45,760""",
    "hindi_letter": "प्रिय महोदय, आपके आवेदन के आधार पर हम सूचित करते हैं कि भारत सरकार की योजना ...",
    "salary_slip": """Salary Slip for April 2024
Employee Name Ravi Kumar  PAN ABCPK1234L
Basic 25,000.00 HRA 10,000.00 Gross 35,000.00""",
}


@pytest.mark.parametrize("name", LOOKALIKES)
def test_unsupported_lookalikes_stay_unknown(name):
    page = classify(doc(LOOKALIKES[name])).pages[0]
    assert page.document_type == T.UNKNOWN, page.signals
