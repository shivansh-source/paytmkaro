"""bureau report, Udyam, financial statements, sanction letter, settlement report: committed fixtures plus the
rules that matter (no-history scores, CMR, unit scaling, balance sheet, EMI recompute, settlement privacy)."""

import json
from pathlib import Path

import pytest
from textdocs import loaded, page, text_doc

from app.documents.extract import extract
from app.documents.extract.pipeline import extract_detailed
from app.documents.fakes import FakeVlm
from app.documents.ingest import load_document
from app.documents.models import DocumentType as DT
from app.documents.models import FieldSource, LoadStatus, Page, TextSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def from_fixture(name: str, kind: DT):
    document = load_document((FIXTURES / name).read_bytes(), name)
    assert document.status == LoadStatus.OK
    return extract(document, kind)


# ---------- committed fixtures ----------


def test_bureau_report_fixture_is_self_provided_and_masks_third_party_data():
    r = from_fixture("bureau_report.pdf", DT.BUREAU_REPORT)

    assert r.status == "ok" and r.fields["score"].value == 705 and r.fields["bureau_name"].value == "other"
    assert r.fields["pan_masked"].value == "XXXXXX234F"
    accounts = r.tables["accounts"]
    assert [a["account_last4"] for a in accounts] == ["7890", "8812", "5678"] and accounts[1]["dpd_max"] == 30
    assert any("self-provided and unverified" in w for w in r.warnings)
    dumped = r.model_dump_json()
    for leaked in ("50100234567890", "4387000012345678", "9876543210", "ABCDE1234F", "Market Road"):
        assert leaked not in dumped


def test_commercial_report_keeps_cmr_out_of_the_score():
    r = from_fixture("bureau_report_commercial.pdf", DT.BUREAU_REPORT)
    assert r.fields["cmr_rank"].value == 4 and "score" not in r.fields


def test_udyam_fixture():
    r = from_fixture("udyam_certificate.pdf", DT.UDYAM_CERTIFICATE)
    f = r.fields
    assert r.status == "ok" and f["udyam_number"].value == "UDYAM-MH-00-1234567"
    assert f["enterprise_type"].value == "small" and f["major_activity"].value == "trading"
    assert f["date_of_incorporation"].value == "2022-04-01" and f["pincode"].value == "411001"
    assert [n["code"] for n in f["nic_codes"].value] == ["46", "4690", "46900"]


def test_financial_statements_fixture_is_scaled_from_lakhs():
    r = from_fixture("financial_statements.pdf", DT.FINANCIAL_STATEMENTS)
    f = r.fields
    assert r.status == "ok" and f["unit"].value == "lakhs" and f["unit_scale"].value == 100000
    assert f["revenue"].value == 61240000.0 and "scaled x100,000 from lakhs" in f["revenue"].note
    assert f["audit_status"].value == "audited" and len(f["udin"].value) == 18
    assert f["financial_year"].value == "2024-25" and f["prior_revenue"].value == 54010000.0
    assert not [w for w in r.warnings if "does not balance" in w]


def test_sanction_letter_fixture_emi_matches_the_recomputed_one():
    r = from_fixture("sanction_letter.pdf", DT.SANCTION_LETTER)
    f = r.fields
    assert (f["facility_type"].value, f["sanctioned_amount"].value, f["tenure_months"].value) == ("term_loan", 1000000.0, 36)
    assert f["emi_amount"].value == pytest.approx(f["emi_recomputed"].value, abs=1) and not [w for w in r.warnings if "EMI" in w]
    assert f["cooling_off_days"].value == 3 and f["fd_lien_or_margin"].value is False


def test_settlement_fixture_drops_customer_data_and_aggregates_in_code():
    r = from_fixture("settlement_report.csv", DT.SETTLEMENT_REPORT)
    assert r.status == "ok" and len(r.tables["settlements"]) == 60 and len(r.tables["monthly"]) == 3
    assert r.fields["total_gross"].source == FieldSource.COMPUTED and r.fields["total_gross"].value == pytest.approx(231865.11)
    dumped = r.model_dump_json()
    assert "payer00@demoupi" not in dumped and "9151847156" not in dumped and "400000000005" not in dumped


# ---------- rules ----------


@pytest.mark.parametrize("printed", ["NH", "-1", "000", "N/A"])
def test_no_history_scores_are_empty_never_zero(printed):
    r = extract(text_doc(f"CIBIL TransUnion\nReport date: 12/06/2025\nPAN: ABCDE1234F\nCIBIL Score: {printed}"), DT.BUREAU_REPORT)
    assert "score" not in r.fields and r.fields["no_credit_history"].value is True
    assert r.fields["pan_masked"].value == "XXXXXX234F"


def test_vlm_no_history_token_is_normalised_and_cmr_is_its_own_field():
    document = loaded(Page(index=0, text="", text_source=TextSource.NONE, image_png=b"\x89PNG\r\n\x1a\n" + b"0" * 10))
    vlm = FakeVlm([{"bureau_name": "Experian", "report_date": "12/06/2025", "score": "NH", "cmr_rank": 7}])
    # The image is not decodable by a real client, but FakeVlm only counts it.
    r = extract(document, DT.BUREAU_REPORT, vlm=vlm)
    assert "score" not in r.fields and r.fields["no_credit_history"].value is True and r.fields["cmr_rank"].value == 7

    out_of_range = extract(text_doc("CIBIL\nReport date: 12/06/2025\nCIBIL Score: 950"), DT.BUREAU_REPORT)
    assert "score" not in out_of_range.fields and any("score" in w and "failed validation" in w for w in out_of_range.warnings)


def test_cmr_rank_with_scale_note_in_brackets():
    r = extract(text_doc("Experian Commercial\nReport date: 12/06/2025\nCMR Rank (1-10, lower is better): 3"), DT.BUREAU_REPORT)
    assert r.fields["cmr_rank"].value == 3 and "score" not in r.fields


def fin_text(unit: str, assets_next: str = "900.00", header: str = "Particulars Note 2025-26 2024-25") -> str:
    return f"""Audited Financial Statements for the year ended 31 March 2026
({unit})
Independent Auditor's Report
{header}
Revenue from operations 1 1,200.50 1,000.00
Other income 2 10.00 8.00
Total expenses 3 1,100.00 930.00
Profit before tax 110.50 78.00
Profit for the year 80.00 60.00
Total assets {assets_next} 800.00
Total current assets 500.00 450.00
Total current liabilities 250.00 240.00
Total liabilities 400.00 380.00
Net worth 500.00 420.00
Long term borrowings 120.00 150.00
Finance costs 30.00 35.00
Depreciation and amortisation 20.00 18.00"""


@pytest.mark.parametrize(("unit", "scale"), [("Rs. in lakhs", 100_000), ("(₹ in Crores)", 10_000_000), ("Amount in Rs. thousands", 1_000), ("in Rupees", 1)])
def test_unit_is_detected_and_amounts_are_scaled_to_rupees(unit, scale):
    r = extract(text_doc(fin_text(unit)), DT.FINANCIAL_STATEMENTS)
    f = r.fields
    assert f["unit_scale"].value == scale and f["revenue"].value == round(1200.50 * scale, 2)
    assert f["prior_revenue"].value == round(1000.0 * scale, 2) and f["profit_after_tax"].value == round(80 * scale, 2)
    assert f["current_ratio"].value == 2.0 and f["current_ratio"].source == FieldSource.COMPUTED
    assert "dscr" not in f  # no principal repayments printed: not computed
    assert not [w for w in r.warnings if "does not balance" in w]


def test_missing_unit_assumes_rupees_and_warns():
    r = extract(text_doc(fin_text("(all figures as per books)")), DT.FINANCIAL_STATEMENTS)
    assert r.fields["unit_scale"].value == 1 and r.fields["unit"].note.startswith("assumed")
    assert any("assumed to be in rupees" in w for w in r.warnings)


def test_balance_sheet_that_does_not_balance_is_flagged():
    r = extract(text_doc(fin_text("Rs. in lakhs", assets_next="990.00")), DT.FINANCIAL_STATEMENTS)
    assert any("current year" in w and "does not balance" in w for w in r.warnings)


def test_oldest_year_first_columns_are_read_by_header_not_position():
    r = extract(text_doc(fin_text("Rs. in lakhs", header="Particulars Note 2024-25 2025-26")), DT.FINANCIAL_STATEMENTS)
    assert r.fields["financial_year"].value == "2025-26" and r.fields["revenue"].value == 100_000_000.0
    assert r.fields["prior_revenue"].value == 120_050_000.0 and any("oldest-year first" in w for w in r.warnings)


SANCTION = """DEMO BANK A
SANCTION LETTER - SAMPLE
Date: 20/05/2025
Facility: Term Loan
Sanctioned loan amount Rs. 10,00,000
Loan term 36 months
Rate of interest 12.50% per annum, fixed
EMI Rs. {emi}"""


def test_printed_emi_that_does_not_follow_from_the_terms_is_flagged():
    ok = extract(text_doc(SANCTION.format(emi="33,453.63")), DT.SANCTION_LETTER)
    bad = extract(text_doc(SANCTION.format(emi="28,000.00")), DT.SANCTION_LETTER)

    assert ok.fields["emi_recomputed"].value == 33453.63 and not [w for w in ok.warnings if "EMI" in w]
    assert any("does not match" in w and "₹33,453.63" in w for w in bad.warnings)


def test_fd_backed_overdraft_is_marked():
    text = "DEMO BANK A\nDate: 20/05/2025\nFacility: Overdraft\nSanctioned limit Rs. 5,00,000\nSecurity: Lien on Fixed Deposit No. 123456789012 with 100% margin"
    r = extract(text_doc(text), DT.SANCTION_LETTER)
    assert r.fields["facility_type"].value == "overdraft" and r.fields["fd_lien_or_margin"].value is True
    assert "123456789012" not in r.model_dump_json()  # long numbers in free text keep only the last 4 digits


def test_settlement_pii_columns_are_never_read():
    table = [
        ["Settlement Date", "Gross Amount", "MDR", "GST on MDR", "Net Settled", "Payer VPA", "Customer Mobile", "Card Last4", "Customer Name", "Transactions", "Mode"],
        ["01/04/2026", "10,000.00", "100.00", "18.00", "9,882.00", "ravi.k@okbank", "9876501234", "4242", "ASHA VERMA", "25", "UPI"],
        ["15/05/2026", "20,000.00", "200.00", "36.00", "19,764.00", "meena@oksbi", "9123456780", "1111", "MEENA ROY", "40", "CARD"],
    ]
    text = "Payment provider: DEMO PAY\nMerchant ID: M0012345\nReport period: 01/04/2026 to 31/05/2026"
    r = extract(text_doc(text, tables=[table]), DT.SETTLEMENT_REPORT)

    rows = r.tables["settlements"]
    assert [row["fees"] for row in rows] == [118.0, 236.0] and rows[0]["net_ok"] is True and rows[1]["txn_count"] == 40
    assert r.fields["merchant_id_last4"].value == "2345" and r.fields["total_gross"].value == 30000.0
    assert r.fields["fee_pct"].value == pytest.approx(1.18)
    dumped = r.model_dump_json()
    for pii in ("ravi.k@okbank", "meena@oksbi", "9876501234", "9123456780", "4242", "ASHA VERMA", "MEENA ROY", "M0012345"):
        assert pii not in dumped
    assert not any(k in json.loads(dumped)["tables"]["settlements"][0] for k in ("payer", "vpa", "mobile", "card", "customer"))


def test_settlement_net_that_does_not_follow_is_flagged_and_gaps_reported():
    table = [["Date", "Gross", "Fees", "Net"], ["01/04/2026", "10,000.00", "100.00", "9,900.00"], ["10/06/2026", "5,000.00", "50.00", "4,000.00"]]
    r = extract(text_doc("", tables=[table]), DT.SETTLEMENT_REPORT)
    assert r.tables["settlements"][1]["net_ok"] is False
    assert r.fields["missing_months"].value == ["2026-05"] and any("No settlements in May 2026" in w for w in r.warnings)
    assert extract_detailed  # raw trace available for the bridge
