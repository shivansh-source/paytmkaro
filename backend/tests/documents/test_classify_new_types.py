"""Round 2: bureau report, Udyam, financial statements, sanction letter, settlement report.

Synthetic corpus only. Settlement columns are generic names, not any vendor's layout.
"""

from __future__ import annotations

import pytest

from app.documents.classify import classify
from app.documents.classify.rules import score_page
from app.documents.classify.signals import extract_features
from app.documents.fakes import FakeVlm
from app.documents.models import DocumentType as T
from app.documents.models import LoadedDocument, LoadStatus, Page, SourceFormat, TextSource
from app.documents.ports import VlmError
from tests.documents.test_classify_rules import (
    AADHAAR_BACK_CLEAN,
    AADHAAR_FRONT_CLEAN,
    BANK_PAGE_1,
    BANK_ROWS_ONLY,
    GST_CERT_CLEAN,
    ITR_CLEAN,
    PAN_CLEAN,
    doc,
)

BUREAU_CONSUMER = """SAMPLE
CIBIL TransUnion Score                 Credit Information Report
Control Number: 000123456789        Date: 12/05/2024
CIBIL SCORE 742   (score range 300-900)
Name: RAVI KUMAR     PAN: ABCPK1234L
Account Information
Member  Account Type  Date Opened  Current Balance  Amount Overdue  DPD
DEMO BANK A  Business Loan  04/03/2022  2,45,000  0  000 000 000
Enquiry Information
DEMO NBFC B  Business Loan  02/05/2024  5,00,000"""

BUREAU_COMMERCIAL = """SAMPLE
Commercial Credit Report
CIBIL MSME Rank (CMR): CMR-4
Credit Facility  Sanctioned  Outstanding  Days Past Due  Suit-filed  Written-off
Cash Credit  10,00,000  6,20,000  0  No  No"""

BUREAU_NOISY = """crediti nformati0n rep0rt
c1b1l score 742 transunion
c0ntr0l number 000123456789
enquiryinformati0n
account inf0rmation dpd"""

UDYAM_CLEAN = """SAMPLE
UDYAM REGISTRATION CERTIFICATE
UDYAM-MH-26-0012345
Ministry of Micro, Small and Medium Enterprises
Name of Enterprise: KUMAR TRADERS
Type of Enterprise: MICRO
NIC 2 Digit: 46  NIC 4 Digit: 4690
Date of Incorporation 01/07/2017
Date of Commencement of Production/Business 01/07/2017"""

UDYAM_NOISY = """udyamregistrationcertificate
UDYAM MH 26 OO12345
ministryofmicro,smallandmediumenterprises
typeofenterprise micro
date0fcommencement0fproducti0n/business"""

UDYAM_HINDI = """उद्यम पंजीकरण प्रमाणपत्र
UDYAM-MH-26-0012345
सूक्ष्म, लघु और मध्यम उद्यम मंत्रालय"""

FINANCIALS_CLEAN = """SAMPLE
KUMAR TRADERS
Balance Sheet as at 31st March 2024          (Amount in ₹)
Share Capital / Proprietor's Capital   5,00,000
Reserves and Surplus                   2,10,000
Sundry Creditors                       1,45,000
Sundry Debtors                         3,10,000
Total Assets                           9,55,000
Profit and Loss Account for the year ended 31st March 2024
Notes to Accounts   Schedule 1
For Mehta & Associates, Chartered Accountants   UDIN: 24123456ABCDEF1234"""

FINANCIALS_NOISY = """balancesheet asatsist march 2024
sundry creditors 1,45,000 sundry debt0rs 3,10,000
reservesandsurp1us 2,10,000
chartered acc0untants udin"""

SANCTION_CLEAN = """SAMPLE
DEMO BANK A
Sanction Letter
Dear Sir, we are pleased to sanction the following facility:
Facility: Term Loan       Sanctioned Amount: Rs. 10,00,000
Rate of Interest: 14.5% p.a.   Annualised Percentage Rate (APR): 16.1%
Tenure: 36 months   EMI: Rs. 34,400   Processing Fee: 1% + GST
Security / Collateral: None
Cooling-off / Look-up period: 3 days
Terms and Conditions apply."""

KFS_CLEAN = """Key Fact Statement (KFS)
Loan amount sanctioned 5,00,000   Annualised Percentage Rate 17.2%
Tenure 24 months  Processing Fee 2,500  Cooling-off period 3 days"""

SANCTION_NOISY = """sancti0n 1etter
sanctionedamount rs 10,00,000
rate0finterest 14.5% pr0cessingfee 1%
c0oling-off 1ook-up peri0d"""

SETTLEMENT_TABLE = [
    ["Transaction ID", "Payment Mode", "Amount", "MDR Fee", "Settlement Amount", "Settlement Date"],
    ["T0001", "UPI", "1,200.00", "0.00", "1,200.00", "05-04-2024"],
    ["T0002", "Card", "5,000.00", "100.00", "4,900.00", "05-04-2024"],
    ["T0003", "UPI", "850.00", "0.00", "850.00", "06-04-2024"],
    ["T0004", "Card", "2,300.00", "46.00", "2,254.00", "06-04-2024"],
]

SETTLEMENT_TEXT = """SAMPLE
Settlement Report
Merchant ID: M123456   Terminal ID: T98765
Settlement Date 05/04/2024   UTR 123456789012
Gross Amount 6,200.00   MDR 100.00   Net Settlement 6,100.00"""

SETTLEMENT_NOISY = """sett1ement rep0rt
merchant id m123456 termina1 id t98765
gr0ssamount 6,200.00 mdr 100.00 netsett1ement 6,100.00 utr"""

CLEAN = [
    (BUREAU_CONSUMER, T.BUREAU_REPORT),
    (BUREAU_COMMERCIAL, T.BUREAU_REPORT),
    (UDYAM_CLEAN, T.UDYAM_CERTIFICATE),
    (FINANCIALS_CLEAN, T.FINANCIAL_STATEMENTS),
    (SANCTION_CLEAN, T.SANCTION_LETTER),
    (KFS_CLEAN, T.SANCTION_LETTER),
    (SETTLEMENT_TEXT, T.SETTLEMENT_REPORT),
]
NOISY = [
    (BUREAU_NOISY, T.BUREAU_REPORT),
    (UDYAM_NOISY, T.UDYAM_CERTIFICATE),
    (UDYAM_HINDI, T.UDYAM_CERTIFICATE),
    (FINANCIALS_NOISY, T.FINANCIAL_STATEMENTS),
    (SANCTION_NOISY, T.SANCTION_LETTER),
    (SETTLEMENT_NOISY, T.SETTLEMENT_REPORT),
]


@pytest.mark.parametrize(("text", "expected"), CLEAN + NOISY, ids=[f"{e.value}{i}" for i, (_, e) in enumerate(CLEAN + NOISY)])
def test_new_types_from_text(text, expected):
    result = classify(doc(text))
    page = result.pages[0]
    assert page.document_type == expected, (page.signals, score_page(Page(index=0, text=text)).scores)
    assert page.signals and page.method == "rules"
    assert result.document_type == expected


def test_settlement_spreadsheet_headers_in_tables():
    page = Page(index=0, text="", text_source=TextSource.NATIVE, tables=[SETTLEMENT_TABLE])
    score = score_page(page)
    assert score.label == T.SETTLEMENT_REPORT, score.scores
    assert "table: settlement column headers" in score.signal_labels(T.SETTLEMENT_REPORT)
    assert score.scores.get(T.BANK_STATEMENT, 0) < 1  # row signals net out against the settlement header


# ---------- confusion pairs ----------


def test_bank_statement_is_not_a_settlement_report_and_vice_versa():
    assert classify(doc(BANK_PAGE_1)).pages[0].document_type == T.BANK_STATEMENT
    assert classify(doc(BANK_ROWS_ONLY)).pages[0].document_type == T.BANK_STATEMENT
    # A settlement page full of dated rows with amounts and UPI tokens still isn't a bank statement.
    rows = "\n".join(f"0{d}/04/2024 UPI T{d}000 {d}00.00 0.00 {d}00.00" for d in range(1, 9))
    page = classify(doc(SETTLEMENT_TEXT + "\n" + rows)).pages[0]
    assert page.document_type == T.SETTLEMENT_REPORT, page.signals


def test_itr_is_not_financial_statements_and_vice_versa():
    assert classify(doc(ITR_CLEAN)).pages[0].document_type == T.ITR
    assert classify(doc(FINANCIALS_CLEAN)).pages[0].document_type == T.FINANCIAL_STATEMENTS
    # An ITR-3/4 page that mentions a balance sheet schedule remains an ITR.
    itr_with_bs = ITR_CLEAN + "\nSchedule BP: Balance Sheet as on 31st March, Profit and Loss Account"
    assert classify(doc(itr_with_bs)).pages[0].document_type == T.ITR


def test_sanction_letter_vs_bank_statement_and_gst_certificate():
    assert classify(doc(SANCTION_CLEAN)).pages[0].document_type == T.SANCTION_LETTER
    assert classify(doc(BANK_PAGE_1)).pages[0].document_type == T.BANK_STATEMENT
    assert classify(doc(GST_CERT_CLEAN)).pages[0].document_type == T.GST_CERTIFICATE
    # A statement page mentioning EMI debits and an overdraft account is still a statement.
    stmt = BANK_PAGE_1 + "\n07/04/2024  EMI DEBIT OVERDRAFT A/C  000999  34,400.00   56,700.00"
    assert classify(doc(stmt)).pages[0].document_type == T.BANK_STATEMENT
    # EMI alone is weak.
    assert classify(doc("Your EMI is due tomorrow.")).pages[0].document_type == T.UNKNOWN


def test_udyam_is_separated_from_udyog_aadhaar():
    assert classify(doc(UDYAM_CLEAN)).pages[0].document_type == T.UDYAM_CERTIFICATE
    old = """UDYOG AADHAAR MEMORANDUM
Government of India Ministry of MSME
Udyog Aadhaar Number MH26A0012345
Name of Enterprise KUMAR TRADERS  Type of Enterprise MICRO"""
    assert classify(doc(old)).pages[0].document_type == T.UNKNOWN
    assert extract_features("UDYAM-MH-26-0012345", [])["udyam_number"] == 1
    assert extract_features("UDYAM-MH-26-001234", [])["udyam_number"] == 0
    assert classify(doc(AADHAAR_FRONT_CLEAN)).pages[0].document_type == T.AADHAAR


def test_consumer_bureau_report_is_not_an_itr_even_with_pan_and_score():
    page = classify(doc(BUREAU_CONSUMER)).pages[0]
    assert page.document_type == T.BUREAU_REPORT
    scores = score_page(Page(index=0, text=BUREAU_CONSUMER)).scores
    assert scores.get(T.ITR, 0) < 3
    # A bare 3-digit number is not bureau evidence.
    assert classify(doc("Invoice total 742\nRef 300 900")).pages[0].document_type == T.UNKNOWN
    assert extract_features("score 742", [])["score_range"] == 0


# ---------- bundle with the new types ----------


def test_bundle_with_new_types():
    pages = [
        PAN_CLEAN, AADHAAR_FRONT_CLEAN, AADHAAR_BACK_CLEAN,
        UDYAM_CLEAN, BUREAU_CONSUMER, FINANCIALS_CLEAN, SANCTION_CLEAN,
        BANK_PAGE_1, BANK_ROWS_ONLY, "",
        SETTLEMENT_TEXT, SETTLEMENT_TEXT,
    ]  # fmt: skip
    result = classify(doc(*pages))
    assert [(s.document_type, s.page_indexes) for s in result.segments] == [
        (T.PAN_CARD, [0]),
        (T.AADHAAR, [1, 2]),
        (T.UDYAM_CERTIFICATE, [3]),
        (T.BUREAU_REPORT, [4]),
        (T.FINANCIAL_STATEMENTS, [5]),
        (T.SANCTION_LETTER, [6]),
        (T.BANK_STATEMENT, [7, 8]),
        (T.UNKNOWN, [9]),
        (T.SETTLEMENT_REPORT, [10, 11]),
    ]


# ---------- page.method and result.warnings ----------


def _img_doc(*texts: str) -> LoadedDocument:
    return LoadedDocument(
        file_name="p.pdf", sha256="0" * 64, source_format=SourceFormat.PDF, status=LoadStatus.OK,
        pages=[Page(index=i, text=t, text_source=TextSource.OCR, image_png=b"png") for i, t in enumerate(texts)],
    )  # fmt: skip


def test_page_method_values():
    vlm = FakeVlm([{"pages": [{"image": 1, "document_type": "bank_statement", "reason": "rows"}]}])
    result = classify(_img_doc(BANK_PAGE_1, "", BANK_PAGE_1, "~~~", "Opening Balance 1,00.00"), vlm=vlm)
    methods = [p.method for p in result.pages]
    assert methods[0] == "rules" and methods[1] == "context" and methods[2] == "rules"
    assert methods[3] in {"vlm", "context"}
    assert result.warnings == []
    plain = classify(doc("", PAN_CLEAN))
    assert [p.method for p in plain.pages] == ["none", "rules"]


def test_warnings_for_vlm_failure_and_budget():
    failing = classify(_img_doc("~~~"), vlm=FakeVlm([VlmError("HTTP 500")]))
    assert any("failed" in w for w in failing.warnings)
    assert any("request failed" in s for s in failing.pages[0].signals)
    assert failing.pages[0].method == "none"
    ok = classify(_img_doc(PAN_CLEAN), vlm=FakeVlm())
    assert ok.warnings == []
