"""profile_features from Applicant-B-like synthetic documents, end to end through the match engine.

Applicant B (backend/data/sample_profiles/applicant_b.json): vintage 14 months, turnover ₹11,00,000,
3 bounces, FOIR 0.42, proprietorship, GST registered. Planted document errors: name mismatch on the
bank statement, one missing month (July), one edited row breaking balance math.
"""

import json
from datetime import date

from app.config import DATA_DIR
from app.documents.extract import extract, name_match, profile_features
from app.documents.extract.common import gstin_check_char, money
from app.documents.models import DocumentType, ExtractionResult, LoadedDocument, LoadStatus, Page, SourceFormat, TextSource
from app.recommendation import MatchInput, load_lender_products, recommend

AS_OF = date(2026, 10, 31)
PAN = "ABCPK1234F"
GSTIN = "29ABCPK1234F1Z" + gstin_check_char("29ABCPK1234F1Z")


def doc(text: str) -> LoadedDocument:
    page = Page(index=0, text=text, text_source=TextSource.NATIVE)
    return LoadedDocument(file_name="b.pdf", sha256="0" * 64, source_format=SourceFormat.PDF, status=LoadStatus.OK, pages=[page])


def amt(x: float) -> str:
    return money(x).lstrip("₹")


PAN_TEXT = f"Permanent Account Number Card\n{PAN}\nName\nRAVI KUMAR\nFather's Name\nSURESH KUMAR\nDate of Birth\n15/08/1985"
AADHAAR_TEXT = "Government of India\nRavi Kumar\nDOB: 15/08/1985\nMALE\nXXXX XXXX 4821\nAddress: 12 MG Road, Indiranagar, Bengaluru 560038"
GST_TEXT = f"""Form GST REG-06
Registration Number: {GSTIN}
1. Legal Name RAVI KUMAR
2. Trade Name, if any KUMAR TRADERS
4. Constitution of Business Proprietorship
5. Address of Principal Place of Business 14, Market Road, Jayanagar, Bengaluru, Karnataka, 560041
6. Date of Liability 01/08/2025
7. Date of Validity From 01/08/2025 To Not Applicable
8. Type of Registration Regular"""
ITR_TEXT = f"Assessment Year 2025-26\nPAN {PAN}\nName RAVI KUMAR\nForm Number ITR-4\nGross Total Income 2,40,000\nTotal Income 2,40,000\nGross Turnover 4,80,000"

# GSTR-3B Aug 2025 - Sep 2026 (14 months). Last 12 (Oct 2025 - Sep 2026): 10 x 90,000 + 2 x 1,00,000 = 11,00,000.
GSTR3B_VALUES = {"2025-08": 50000, "2025-09": 50000, **{m: 90000 for m in ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]}, "2026-08": 100000, "2026-09": 100000}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def gstr3b_text() -> str:
    blocks = []
    for period, value in GSTR3B_VALUES.items():
        y, m = map(int, period.split("-"))
        fy = f"{y}-{(y + 1) % 100:02d}" if m >= 4 else f"{y - 1}-{y % 100:02d}"
        tax = amt(value * 0.09)
        blocks.append(
            f"Form GSTR-3B\nYear {fy}  Period {MONTH_NAMES[m - 1]}\n1. GSTIN {GSTIN}\n2(a). Legal name of the registered person RAVI KUMAR\n"
            f"(a) Outward taxable supplies (other than zero rated, nil rated and exempted)  {amt(value)}  0.00  {tax}  {tax}  0.00"
        )
    return "\n\n".join(blocks)


def bank_text(holder: str = "RAJESH KUMAR") -> str:
    """Apr-Sep 2026 without July. Each month: sales 60,000 + 40,000, EMI 42,000. NACH bounces in Jun, Aug,
    Sep (returned EMI credited back + a charge). August's 40,000 deposit is printed but the balance only
    moved by 4,000: the edited row."""
    rows: list[tuple[str, str, float, float, float | None]] = []  # date, narration, debit, credit, printed amount override
    for m in (4, 5, 6, 8, 9):
        rows += [(f"03/{m:02d}/2026", "UPI/CR/KUMAR SALES", 0, 60000, None), (f"05/{m:02d}/2026", "NACH/EMI/DEMO NBFC LOAN", 42000, 0, None)]
        if m in (6, 8, 9):
            rows += [(f"07/{m:02d}/2026", "NACH RTN INSUFFICIENT FUNDS", 0, 42000, None), (f"08/{m:02d}/2026", "NACH RTN CHGS", 590, 0, None)]
        actual = 4000 if m == 8 else 40000
        rows.append((f"20/{m:02d}/2026", "NEFT CR SHARMA STORES", 0, actual, 40000 if m == 8 else None))
    lines, balance = [], 25000.0
    for d, narration, debit, credit, printed in rows:
        balance += credit - debit
        shown = printed if printed is not None else (debit or credit)
        lines.append(f"{d}  {narration:<32}  {amt(shown)}  {amt(balance)}")
    header = f"DEMO BANK B\nAccount Name: {holder}\nAccount Number: 001234565521\nIFSC: DEMO0001234\nStatement Period: 01/04/2026 to 30/09/2026\nOpening Balance: 25,000.00"
    return header + "\n" + "\n".join(lines)


def applicant_b_results() -> list[ExtractionResult]:
    return [
        extract(doc(PAN_TEXT), DocumentType.PAN_CARD),
        extract(doc(AADHAAR_TEXT), DocumentType.AADHAAR),
        extract(doc(GST_TEXT), DocumentType.GST_CERTIFICATE),
        extract(doc(gstr3b_text()), DocumentType.GSTR_3B),
        extract(doc(ITR_TEXT), DocumentType.ITR),
        extract(doc(bank_text()), DocumentType.BANK_STATEMENT),
    ]


def test_applicant_b_features_match_the_sample_profile():
    results = applicant_b_results()
    assert [r.status for r in results] == ["ok"] * 6, [(r.document_type, r.missing) for r in results]
    features = profile_features(results, as_of=AS_OF)
    f = features.features
    expected = json.loads((DATA_DIR / "sample_profiles" / "applicant_b.json").read_text(encoding="utf-8"))

    for key in ("business_vintage_months", "annual_turnover", "bounces_6m", "foir", "gst_registered", "constitution"):
        assert f[key].value == expected[key], key
    assert f["business_vintage_months"].source == "gst_certificate.registration_date"
    assert f["annual_turnover"].source == "gstr_3b.periods.taxable_outward_value" and not f["annual_turnover"].estimate
    assert "Oct 2025 to Sep 2026" in f["annual_turnover"].method
    assert not f["bounces_6m"].estimate and "2026-04-01 to 2026-09-30" in f["bounces_6m"].method
    assert f["foir"].estimate and f["bounces_6m"].source == "bank_statement.transactions.narration"
    assert "bureau_score" not in f and "sector" not in f
    assert set(features.profile_fields()) <= set(MatchInput.model_fields)


def test_applicant_b_planted_errors_are_flagged():
    checks = {(c.rule, tuple(c.documents)): c for c in profile_features(applicant_b_results(), as_of=AS_OF).checks}
    outcome = {key: c.outcome for key, c in checks.items()}

    assert outcome[("pan_in_gstin", ("gst_certificate", "pan_card"))] == "pass"
    assert outcome[("pan_in_gstin", ("gst_certificate", "itr"))] == "pass"
    assert outcome[("gstin_consistency", ("gst_certificate", "gstr_3b"))] == "pass"
    assert outcome[("dob_match", ("pan_card", "aadhaar"))] == "pass"
    assert outcome[("name_match", ("pan_card", "aadhaar"))] == "pass"
    bank_name = checks[("name_match", ("pan_card", "bank_statement"))]
    assert bank_name.outcome == "fail" and "RAJESH KUMAR" in bank_name.message
    assert outcome[("statement_balance_math", ("bank_statement",))] == "fail"
    coverage = checks[("statement_coverage", ("bank_statement",))]
    assert coverage.outcome == "warn" and "Jul 2026" in coverage.message
    assert outcome[("address_pincode", ("aadhaar", "gst_certificate"))] == "warn"
    turnover = checks[("turnover_vs_bank", ("gstr_3b", "bank_statement"))]
    assert turnover.outcome == "pass" and "5 months" in turnover.message


def test_applicant_b_features_drive_the_match_engine():
    features = profile_features(applicant_b_results(), as_of=AS_OF)
    # Bureau score and sector cannot come from documents: self-declared here, as in applicant_b.json.
    profile = MatchInput(sme_id="SAMPLE-B", requested_amount=500000, requested_tenure_months=24, bureau_score=705, sector="retail", **features.profile_fields())
    results = {r.lender: r for r in recommend(profile, load_lender_products())}

    assert results["Demo Bank A"].status == "not_yet"
    assert results["Demo NBFC B"].status == "matched" and results["Demo Finance C"].status == "matched"
    reasons = " ".join(results["Demo Bank A"].reasons)
    assert "14 months" in reasons and "₹11,00,000" in reasons


def test_initials_need_confirmation_not_failure():
    assert name_match("R. Kumar", "Ravi Kumar")[0] == "warn"
    assert name_match("RAVI KUMAAR", "Ravi Kumar")[0] == "pass"
    assert name_match("Sunil Verma", "Ravi Kumar")[0] == "fail"

    results = applicant_b_results()
    results[-1] = extract(doc(bank_text(holder="R. KUMAR")), DocumentType.BANK_STATEMENT)
    check = next(c for c in profile_features(results, as_of=AS_OF).checks if c.rule == "name_match" and "bank_statement" in c.documents)
    assert check.outcome == "warn" and "please confirm" in check.message


def test_bank_name_matching_trade_name_passes():
    results = applicant_b_results()
    results[-1] = extract(doc(bank_text(holder="KUMAR TRADERS")), DocumentType.BANK_STATEMENT)
    check = next(c for c in profile_features(results, as_of=AS_OF).checks if c.rule == "name_match" and "bank_statement" in c.documents)
    assert check.outcome == "pass" and check.documents == ["gst_certificate", "bank_statement"]


def test_turnover_falls_back_to_itr_then_bank_credits():
    results = applicant_b_results()
    no_gst = [r for r in results if r.document_type != DocumentType.GSTR_3B]
    f = profile_features(no_gst, as_of=AS_OF).features
    assert f["annual_turnover"].value == 480000 and f["annual_turnover"].source == "itr.business_turnover"

    bank_only = [r for r in no_gst if r.document_type not in (DocumentType.ITR,)]
    f = profile_features(bank_only, as_of=AS_OF).features
    # Revenue credits 5,00,000 over ~6 months (returned NACH credits excluded), annualised.
    assert f["annual_turnover"].estimate and f["annual_turnover"].source == "bank_statement.transactions.credit"
    assert 990000 <= f["annual_turnover"].value <= 1000000


def test_missing_documents_give_none_not_zero():
    pan_only = [extract(doc(PAN_TEXT), DocumentType.PAN_CARD)]
    features = profile_features(pan_only, as_of=AS_OF)
    fields = features.profile_fields()

    for key in ("business_vintage_months", "annual_turnover", "bounces_6m", "foir", "gst_registered"):
        assert key not in fields
    # Individual PAN without a GST certificate: constitution is only an estimate.
    assert features.features["constitution"].value == "proprietorship" and features.features["constitution"].estimate


def test_company_gstin_against_personal_pan_is_a_warning():
    company = "29AACCD1234E1Z" + gstin_check_char("29AACCD1234E1Z")
    results = [extract(doc(PAN_TEXT), DocumentType.PAN_CARD), extract(doc(GST_TEXT.replace(GSTIN, company).replace("Proprietorship", "Private Limited Company")), DocumentType.GST_CERTIFICATE)]
    features = profile_features(results, as_of=AS_OF)

    check = next(c for c in features.checks if c.rule == "pan_in_gstin")
    assert check.outcome == "warn" and "business PAN" in check.message
    assert features.features["constitution"].value == "pvt_ltd"
    # A company's legal name is not compared with the director's PAN name.
    assert not any(c.rule == "name_match" and "gst_certificate" in c.documents for c in features.checks)


def test_short_statement_bounce_window_is_flagged_as_estimate():
    text = "Account Name: RAVI KUMAR\nAccount Number: XXXX5521\nStatement Period: 01/09/2026 to 30/09/2026\nOpening Balance: 1,000.00\n05/09/2026  ECS RTN  500.00  1,500.00"
    f = profile_features([extract(doc(text), DocumentType.BANK_STATEMENT)], as_of=AS_OF).features
    assert f["bounces_6m"].value == 1 and f["bounces_6m"].estimate and "fewer than 6 months" in f["bounces_6m"].method


def test_gstr3b_gap_annualises_over_calendar_window():
    values = {k: v for k, v in GSTR3B_VALUES.items() if k not in ("2025-10", "2025-11")}
    text = gstr3b_text().split("\n\n")
    kept = [b for b, k in zip(text, GSTR3B_VALUES) if k in values]
    results = [extract(doc("\n\n".join(kept)), DocumentType.GSTR_3B)]
    f = profile_features(results, as_of=AS_OF).features["annual_turnover"]

    # Oct 2025 - Sep 2026 window has 10 returns: 8 x 90,000 + 2 x 1,00,000 = 9,20,000, x 12 / 10.
    assert f.estimate and f.value == 1104000
    assert "Oct 2025, Nov 2025" in f.method


def test_extracted_output_conforms_to_schema_files():
    from app.config import DOCUMENT_SCHEMAS_DIR
    from app.documents.extract.schemas import SCHEMA_FILES, TABLE_MODELS

    for result in applicant_b_results():
        schema = json.loads((DOCUMENT_SCHEMAS_DIR / SCHEMA_FILES[result.document_type]).read_text(encoding="utf-8"))
        assert set(result.fields) <= set(schema["properties"]), result.document_type
        if result.document_type in TABLE_MODELS:
            key = TABLE_MODELS[result.document_type][0]
            row_keys = set(schema["properties"][key]["items"]["properties"])
            assert result.tables[key] and all(set(row) <= row_keys for row in result.tables[key])
