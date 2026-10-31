"""Per-document and cross-document checks on the sample applicants (incl. B's 3 planted problems)."""
from app.samples import AS_OF, applicant_a, applicant_b
from app.schemas import CheckStatus, CrossCheck, DocumentType
from app.validation import validate_all


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


def test_confirming_a_near_match_name_resolves_the_warning():
    docs = applicant_b()
    bank = next(d for d in docs if d.document_type == DocumentType.BANK_STATEMENT)
    bank.data.account_holder_name.user_confirmed = True
    check = _cross(docs)[CrossCheck.NAME_MATCH]
    assert check.status == CheckStatus.PASS
    assert "confirmed by you" in check.message


def test_confirming_cannot_override_a_different_person():
    docs = applicant_a()
    bank = next(d for d in docs if d.document_type == DocumentType.BANK_STATEMENT)
    bank.data.account_holder_name.value = "SUNITA SHARMA"
    bank.data.account_holder_name.user_confirmed = True
    assert _cross(docs)[CrossCheck.NAME_MATCH].status == CheckStatus.FAIL
