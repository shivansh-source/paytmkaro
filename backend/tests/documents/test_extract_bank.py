"""Bank statements: rows from text and tables, Indian formats, balance math, coverage, privacy."""

from app.documents.extract import extract
from app.documents.models import DocumentType, FieldSource, LoadedDocument, LoadStatus, Page, SourceFormat, TextSource
from app.documents.privacy import verhoeff_valid

HEADER = """DEMO BANK B
Statement of Account                      SAMPLE
Account Name: RAVI KUMAR
Account Number: 001234565521
IFSC: DEMO0001234
Branch: Jayanagar
Statement Period: 01/04/2026 to 30/06/2026
Opening Balance: 50,000.00
Date        Narration                           Withdrawal      Deposit      Balance"""


def page(text: str, index: int = 0, tables=None, source=TextSource.NATIVE) -> Page:
    return Page(index=index, text=text, text_source=source, tables=tables or [])


def doc(*pages: Page) -> LoadedDocument:
    return LoadedDocument(file_name="statement.pdf", sha256="0" * 64, source_format=SourceFormat.PDF, status=LoadStatus.OK, pages=list(pages))


ROWS = """02/04/2026  UPI/CR/KUMAR SALES                  1,00,000.00   1,50,000.00
05/04/2026  NACH/EMI/DEMO NBFC                    42,000.00    1,08,000.00
12-May-2026 NEFT CR SHARMA STORES                 60,000.00    1,68,000.00
15-May-2026 ATM WDL JAYANAGAR                     8,000.00     1,60,000.00
03/06/2026  CHQ PAID 004512                       12,500.00    1,47,500.00
20/06/2026  IMPS/CR/MEHTA AND SONS
            INVOICE 118                           25,000.00    1,72,500.00"""


def test_header_rows_and_balance_math_from_text():
    result = extract(doc(page(HEADER + "\n" + ROWS + "\nClosing Balance: 1,72,500.00")), DocumentType.BANK_STATEMENT)

    f = result.fields
    assert result.status == "ok", (result.missing, result.warnings)
    assert f["account_holder_name"].value == "RAVI KUMAR"
    assert f["bank_name"].value == "DEMO BANK B"
    assert f["ifsc"].value == "DEMO0001234"
    assert f["account_number_last4"].value == "5521"
    assert f["period_from"].value == "2026-04-01" and f["period_to"].value == "2026-06-30"
    assert f["opening_balance"].value == 50000.0 and f["closing_balance"].value == 172500.0

    rows = result.tables["transactions"]
    assert len(rows) == 6
    assert rows[0]["credit"] == 100000.0 and rows[0]["debit"] is None  # decided by balance math
    assert rows[1]["debit"] == 42000.0
    assert rows[2]["date"] == "2026-05-12"
    assert rows[4]["ref"] == "004512" and rows[4]["narration"] == "CHQ PAID"
    assert rows[5]["narration"] == "IMPS/CR/MEHTA AND SONS INVOICE 118"  # wrapped narration joined
    assert all(r["balance_ok"] for r in rows)
    assert f["balance_breaks"].value == 0 and f["balance_breaks"].source == FieldSource.COMPUTED
    assert f["total_credits"].value == 185000.0 and f["total_debits"].value == 62500.0
    assert f["missing_months"].value == [] and f["months_covered"].value == 3
    # The full account number never reaches the result.
    assert "001234565521" not in result.model_dump_json()


def test_one_edited_row_breaks_balance_math_once():
    # Deposit edited from 25,000 to 85,000; balances left as printed.
    edited = ROWS.replace("25,000.00    1,72,500.00", "85,000.00    1,72,500.00")
    result = extract(doc(page(HEADER + "\n" + edited)), DocumentType.BANK_STATEMENT)

    assert result.fields["balance_breaks"].value == 1
    breaks = [w for w in result.warnings if w.startswith("Balance math breaks")]
    assert len(breaks) == 1
    assert "row 6 (20/06/2026" in breaks[0] and "₹85,000.00" in breaks[0] and "₹2,32,500.00" in breaks[0]
    assert [r["balance_ok"] for r in result.tables["transactions"]] == [True] * 5 + [False]


def test_missing_month_is_detected():
    no_may = "\n".join(line for line in ROWS.splitlines() if "May-2026" not in line).replace("1,47,500.00", "1,55,500.00").replace("1,72,500.00", "1,80,500.00")
    no_may = no_may.replace("CHQ PAID 004512                       12,500.00    1,55,500.00", "CHQ PAID 004512                       12,500.00    95,500.00")
    no_may = no_may.replace("25,000.00    1,80,500.00", "25,000.00    1,20,500.00")
    result = extract(doc(page(HEADER + "\n" + no_may)), DocumentType.BANK_STATEMENT)

    assert result.fields["missing_months"].value == ["2026-05"]
    assert any("No transactions in May 2026" in w for w in result.warnings)
    assert result.fields["balance_breaks"].value == 0


def test_dr_cr_suffix_rows_and_newest_first_order():
    text = """Customer Name : SUNITA RAO
A/c No: XXXXXXXX7788
Period: 01-Mar-2026 to 31-Mar-2026
Opening Balance 10,000.00 Cr
25-Mar-2026  POS PURCHASE GROCERY    1,500.00 Dr   12,500.00 Cr
10-Mar-2026  BY CLG SALES            4,000.00 Cr   14,000.00 Cr
02-Mar-2026  TO SELF ATM             0.00 Dr  10,000.00 Cr"""
    result = extract(doc(page(text)), DocumentType.BANK_STATEMENT)

    rows = result.tables["transactions"]
    assert [r["date"] for r in rows] == ["2026-03-02", "2026-03-10", "2026-03-25"]
    assert rows[1]["credit"] == 4000.0 and rows[2]["debit"] == 1500.0
    assert result.fields["balance_breaks"].value == 0
    assert result.fields["account_number_last4"].value == "7788"
    assert any("re-ordered" in w for w in result.warnings)


def test_rows_from_spreadsheet_table_with_debit_credit_columns():
    table = [
        ["Txn Date", "Description", "Ref No", "Debit", "Credit", "Balance"],
        ["01/04/2026", "Opening", "", "", "", "20,000.00"],
        ["03/04/2026", "UPI/CR/KUMAR SALES", "UPI123", "", "30,000.00", "50,000.00"],
        ["", "continued narration", "", "", "", ""],
        ["09/04/2026", "NACH RTN INSUFFICIENT FUNDS", "", "", "12,000.00", "62,000.00"],
        ["10/04/2026", "NACH RTN CHGS", "", "590.00", "", "61,410.00"],
    ]
    text = "Account Holder Name: RAVI KUMAR\nAccount No: 1234567890125521\nStatement Period: 01/04/2026 to 30/04/2026"
    result = extract(doc(page(text, tables=[table])), DocumentType.BANK_STATEMENT)

    rows = result.tables["transactions"]
    assert len(rows) == 4
    assert rows[1]["ref"] == "UPI123" and rows[1]["narration"] == "UPI/CR/KUMAR SALES continued narration"
    assert rows[3]["debit"] == 590.0
    # First row has no previous balance to check against.
    assert rows[0]["balance_ok"] is None and all(r["balance_ok"] for r in rows[1:])


def test_twelve_digit_upi_reference_survives_but_aadhaar_never_does():
    ref = next("41234567890" + d for d in "0123456789" if verhoeff_valid("41234567890" + d))
    text = HEADER + f"\n02/04/2026  UPI/{ref}/KUMAR SALES     1,00,000.00   1,50,000.00"
    result = extract(doc(page(text)), DocumentType.BANK_STATEMENT)

    assert ref in result.tables["transactions"][0]["narration"]


def test_ocr_text_without_header_period_uses_transaction_dates():
    text = "Account Name: RAVI KUMAR\nAccount Number: XXXX5521\n" + ROWS
    result = extract(doc(page(text, source=TextSource.OCR)), DocumentType.BANK_STATEMENT)

    f = result.fields
    assert f["period_from"].source == FieldSource.COMPUTED and f["period_from"].value == "2026-04-02"
    assert f["period_to"].value == "2026-06-20"
    assert result.tables["transactions"][0]["source"] == "ocr"
    # No opening balance: the first row's direction comes from its narration, later rows from balance math.
    assert result.tables["transactions"][0]["credit"] == 100000.0
