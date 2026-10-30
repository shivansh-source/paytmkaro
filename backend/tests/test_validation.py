from datetime import date

import pytest

from app.samples import AS_OF, applicant_a, applicant_b
from app.schemas import CheckStatus, CrossCheck, DocumentType
from app.schemas.documents import Transaction
from app.validation import validate_all
from app.validation.checksums import aadhaar_valid, gstin_check_digit, gstin_checksum_valid, verhoeff_check_digit, verhoeff_valid
from app.validation.tagging import tag_transaction
from app.validation.text import compare_addresses, compare_names


def test_verhoeff_textbook_example():
    assert verhoeff_check_digit("236") == "3"
    assert verhoeff_valid("2363")
    assert not verhoeff_valid("2364")


def test_aadhaar_rules():
    body = "23456789012"
    assert aadhaar_valid(body + verhoeff_check_digit(body))
    assert not aadhaar_valid("1" + body[1:] + "0")  # can't start with 0/1
    assert not aadhaar_valid("1234")


def test_gstin_checksum():
    assert gstin_checksum_valid("27AAPFU0939F1ZV")  # published example
    assert not gstin_checksum_valid("27AAPFU0939F1ZW")
    assert gstin_check_digit("27AAPFU0939F1Z") == "V"


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("RAVI KUMAR", "Ravi  Kumar", CheckStatus.PASS),
        ("RAVI KUMAR", "Mr. Ravi Kumar", CheckStatus.PASS),
        ("RAVI KUMAR", "KUMAR RAVI", CheckStatus.PASS),
        ("RAVI KUMAR", "R. KUMAR", CheckStatus.WARN),
        ("RAVI KUMAR", "RAVI KUMAAR", CheckStatus.WARN),
        ("RAVI KUMAR", "SUNITA SHARMA", CheckStatus.FAIL),
    ],
)
def test_name_matching(a, b, expected):
    assert compare_names(a, b) == expected


def test_address_matching():
    home = "12 Gandhi Bazaar Main Road, Basavanagudi, Bengaluru 560004"
    assert compare_addresses(home, "No 12, Gandhi Bazaar, Basavanagudi, Bengaluru - 560004") == CheckStatus.PASS
    assert compare_addresses(home, "44 MG Road, Pune 411001") == CheckStatus.FAIL


@pytest.mark.parametrize(
    ("narration", "debit", "credit", "tags"),
    [
        ("NACH RTN INSUFFICIENT FUNDS SAMPLE NBFC", 0, 40000, {"bounce", "nach"}),
        ("NACH RTN CHGS INCL GST", 590, 0, {"charges", "nach"}),
        ("NACH/DR/SAMPLE NBFC LOAN EMI", 40000, 0, {"emi", "nach"}),
        ("UPI/CR/SAMPLE RETAIL CUSTOMERS", 0, 24000, {"upi"}),
        ("CHQ RETURNED - DISHONOURED", 0, 15000, {"bounce"}),
    ],
)
def test_transaction_tagging(narration, debit, credit, tags):
    txn = Transaction(date=date(2026, 4, 5), narration=narration, debit=debit, credit=credit, balance=0)
    assert set(tag_transaction(txn).tags) == tags


def _cross(envelopes):
    _, _, cross = validate_all(envelopes, AS_OF)
    return {c.id: c for c in cross}


def test_clean_applicant_passes_everything():
    documents, _, cross = validate_all(applicant_a(), AS_OF)
    assert all(c.status == CheckStatus.PASS for c in cross), [c.message for c in cross if c.status != CheckStatus.PASS]
    assert {d.status for d in documents} == {"verified"}
    assert len(cross) == 7


def test_messy_applicant_three_planted_problems_are_caught():
    cross = _cross(applicant_b())
    assert cross[CrossCheck.NAME_MATCH].status == CheckStatus.WARN  # 1. "RAVI KUMAAR"
    assert "KUMAAR" in cross[CrossCheck.NAME_MATCH].message
    assert cross[CrossCheck.STATEMENT_GAPS].status == CheckStatus.FAIL  # 2. July GSTR-3B missing
    assert "Jul 2026" in cross[CrossCheck.STATEMENT_GAPS].message
    assert cross[CrossCheck.BALANCE_MATH].status == CheckStatus.FAIL  # 3. edited row
    assert "10 Feb 2026" in cross[CrossCheck.BALANCE_MATH].message
    # Nothing else is flagged.
    others = {k: v.status for k, v in cross.items() if k not in {CrossCheck.NAME_MATCH, CrossCheck.STATEMENT_GAPS, CrossCheck.BALANCE_MATH}}
    assert set(others.values()) == {CheckStatus.PASS}


def test_bad_pan_format_fails_but_is_kept():
    docs = applicant_a()
    pan = next(d for d in docs if d.document_type == DocumentType.PAN_CARD)
    pan.data.pan_number.value = "ABCPK12E4F"  # OCR read a 3 as E
    documents, _, cross = validate_all(docs, AS_OF)
    checked = next(d for d in documents if d.document_type == DocumentType.PAN_CARD)
    assert {c.id: c.status for c in checked.checks}["pan.format"] == CheckStatus.FAIL
    assert checked.status == "needs_review"
    assert {c.id: c for c in cross}[CrossCheck.PAN_IN_GSTIN].status == CheckStatus.FAIL


def test_low_confidence_fields_are_listed_for_review():
    docs = applicant_a()
    pan = next(d for d in docs if d.document_type == DocumentType.PAN_CARD)
    pan.data.dob.confidence = 0.6
    documents, _, _ = validate_all(docs, AS_OF)
    review = next(c for d in documents for c in d.checks if c.id == "pan.needs_review")
    assert review.status == CheckStatus.WARN and review.fields == ["data.dob"]
