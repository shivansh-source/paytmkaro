"""Contract changes to the extraction envelope: what the schema now allows and how validation, scoring and the
assessment behave when a value was never printed."""

import pytest
from pydantic import ValidationError

from app.samples import AS_OF, BUREAU_A, applicant_a
from app.schemas import Aadhaar, DocumentType, Extracted, Source
from app.scoring import assess


def replace_data(docs, doc_type, **changes):
    return [
        d.model_copy(update={"data": d.data.model_copy(update=changes)}) if d.document_type == doc_type else d
        for d in docs
    ]


def run(docs):
    return assess("SAMPLE", docs, bureau=BUREAU_A, sector="retail", as_of=AS_OF)


def check(assessment, check_id):
    return next(c for c in assessment.profile.cross_checks if c.id == check_id)


# ---- Aadhaar: year of birth ------------------------------------------------------------------------


def aadhaar_fields(**overrides):
    return {
        "aadhaar_last4": {"value": "4821", "confidence": 0.98, "source": "vlm"},
        "name": {"value": "RAVI KUMAR", "confidence": 0.95, "source": "vlm"},
        "address": {"value": {"text": "SAMPLE, Bengaluru 560004"}, "confidence": 0.9, "source": "vlm"},
        **overrides,
    }


def test_aadhaar_needs_a_dob_or_a_year_of_birth():
    with pytest.raises(ValidationError, match="dob or a year_of_birth"):
        Aadhaar.model_validate(aadhaar_fields())
    year_only = Aadhaar.model_validate(aadhaar_fields(year_of_birth={"value": 1986, "confidence": 0.9, "source": "vlm"}))
    assert year_only.dob is None and year_only.year_of_birth.value == 1986
    # An unreadable date is still representable, so validation can report it.
    unreadable = Aadhaar.model_validate(aadhaar_fields(dob={"value": None, "confidence": 0, "source": "vlm"}))
    assert unreadable.dob.value is None


def year_only(docs, year):
    return replace_data(
        docs, DocumentType.AADHAAR, dob=None, year_of_birth=Extracted[int](value=year, confidence=0.9, source=Source.OCR)
    )


def pan_year(docs):
    return next(d for d in docs if d.document_type == DocumentType.PAN_CARD).data.dob.value.year


def test_matching_year_of_birth_passes_the_dob_check():
    docs = applicant_a()
    result = check(run(year_only(docs, pan_year(docs))), "cross.dob_match")
    assert result.status == "pass" and "only the year" in result.message
    assert result.expected == result.actual == str(pan_year(docs))


def test_different_year_of_birth_fails_the_dob_check():
    docs = applicant_a()
    result = check(run(year_only(docs, pan_year(docs) + 3)), "cross.dob_match")
    assert result.status == "fail" and "Year of birth differs" in result.message


def test_year_only_card_is_not_sent_to_the_user_for_a_missing_date():
    assessment = run(year_only(applicant_a(), pan_year(applicant_a())))
    aadhaar = next(d for d in assessment.documents if d.document_type == DocumentType.AADHAAR)
    assert not any("date of birth" in c.message.lower() for c in aadhaar.checks if c.id.endswith("needs_review"))


# ---- Opening balance ---------------------------------------------------------------------------------


def test_missing_opening_balance_does_not_crash_or_ask_the_user():
    from app.assessment import score_sme

    docs = replace_data(applicant_a(), DocumentType.BANK_STATEMENT, opening_balance=None)
    assessment = run(docs)

    assert assessment.profile.cashflow.avg_monthly_credits is not None
    bank = next(d for d in assessment.documents if d.document_type == DocumentType.BANK_STATEMENT)
    assert not any("opening" in c.message.lower() for c in bank.checks if c.id.endswith("needs_review"))
    assert score_sme(assessment.profile, assessment.documents, as_of=AS_OF).index is not None


def test_transaction_reference_is_its_own_field():
    docs = applicant_a()
    bank = next(d for d in docs if d.document_type == DocumentType.BANK_STATEMENT).data
    first = bank.transactions[0].model_copy(update={"ref": "CHQ000123"})
    assert first.ref == "CHQ000123" and type(first).model_validate(first.model_dump()).ref == "CHQ000123"


# ---- Uploaded bureau report -> self-declared score ---------------------------------------------------

from datetime import date as _date  # noqa: E402
from pathlib import Path  # noqa: E402

from app.documents.process import _self_provided_bureau, process_upload  # noqa: E402
from app.schemas.documents import BureauReport, DocumentEnvelope, FileInfo  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def bureau_result(**fields):
    extracted = {name: Extracted(value=value, confidence=0.9, source=Source.PARSER) for name, value in fields.items()
                 if name in BureauReport.model_fields}
    report = BureauReport(
        bureau_name=extracted.get("bureau_name"), report_date=extracted.get("report_date"), score=extracted.get("score"),
        cmr_rank=extracted.get("cmr_rank"), active_accounts=extracted.get("active_accounts"),
        total_outstanding=extracted.get("total_outstanding"), overdue_amount=extracted.get("overdue_amount"),
        max_dpd_24m=extracted.get("max_dpd_24m"), written_off_or_settled=extracted.get("written_off_or_settled"),
        suit_filed_or_wilful_default=extracted.get("suit_filed_or_wilful_default"), enquiries_90d=extracted.get("enquiries_90d"),
    )
    return DocumentEnvelope(
        document_id="bureau-test", sme_id="s", document_type=DocumentType.BUREAU_REPORT, status="needs_review",
        uploaded_at=datetime.now(timezone.utc),
        file=FileInfo(file_name="bureau.pdf", mime_type="application/pdf", size_bytes=10, sha256="a" * 64), data=report,
    )


def test_uploaded_bureau_report_becomes_an_unverified_self_declared_score():
    result = process_upload((FIXTURES / "bureau_report.pdf").read_bytes(), "bureau_report.pdf", sme_id="s")

    assert result.bureau is not None and result.bureau.source == "self_declared" and result.bureau.value == 705
    assert any("unverified" in w for w in result.warnings)
    # It plugs straight into scoring as the self-declared value.
    assert assess("s", [], bureau=result.bureau, as_of=AS_OF).profile.bureau.source == "self_declared"


def test_commercial_report_gives_no_score():
    result = process_upload((FIXTURES / "bureau_report_commercial.pdf").read_bytes(), "bureau_report_commercial.pdf", sme_id="s")
    assert result.bureau is None  # the CMR rank is 1-10, lower is better: never a 300-900 score


def test_no_history_unreadable_or_cmr_only_reports_give_no_score():
    assert _self_provided_bureau([bureau_result(no_credit_history=True)]) is None
    assert _self_provided_bureau([bureau_result(cmr_rank=4)]) is None
    assert _self_provided_bureau([bureau_result(score=None)]) is None
    assert _self_provided_bureau([]) is None


def test_the_newest_report_wins_and_an_undated_one_loses_to_a_dated_one():
    older = bureau_result(score=640, report_date="2025-01-10")
    newer = bureau_result(score=700, report_date="2026-09-30")
    undated = bureau_result(score=800)

    assert _self_provided_bureau([older, newer]).value == 700
    assert _self_provided_bureau([newer, older]).value == 700
    assert _self_provided_bureau([undated, older]).value == 640
    assert _self_provided_bureau([newer]).as_of == _date(2026, 9, 30)


# ---- Optional running balance ------------------------------------------------------------------------------


def with_transactions(docs, mutate):
    bank = next(d for d in docs if d.document_type == DocumentType.BANK_STATEMENT).data
    return replace_data(docs, DocumentType.BANK_STATEMENT, transactions=[mutate(i, t) for i, t in enumerate(bank.transactions)])


def blank(docs, every_nth=None, all_rows=False, first=0):
    """Remove the printed balance from every nth row (or from all rows)."""
    return with_transactions(
        docs, lambda i, t: t.model_copy(update={"balance": None}) if all_rows or (every_nth and i >= first and i % every_nth == 0) else t
    )


def balance_math(assessment):
    return check(assessment, "cross.balance_math")


def rows_of(docs):
    return len(next(d for d in docs if d.document_type == DocumentType.BANK_STATEMENT).data.transactions)


def test_an_edited_amount_beside_a_blank_balance_is_still_caught():
    docs = applicant_a()
    bank = next(d for d in docs if d.document_type == DocumentType.BANK_STATEMENT).data
    k = next(i for i, t in enumerate(bank.transactions[:-1]) if t.credit > 0)

    def tamper(i, t):
        # Row k: credit inflated by 30,000 AND its balance cell blanked, so row k alone shows nothing wrong.
        return t.model_copy(update={"credit": t.credit + 30_000, "balance": None}) if i == k else t

    untouched = [t.model_copy(update={"balance": None}) if i == k else t for i, t in enumerate(bank.transactions)]
    control = replace_data(docs, DocumentType.BANK_STATEMENT, transactions=untouched)

    assert balance_math(run(control)).status == "pass"  # blank cell alone is not an accusation
    caught = balance_math(run(with_transactions(docs, tamper)))
    assert caught.status == "fail"  # the next printed balance no longer matches the chained total


def test_a_statement_with_no_balance_column_cannot_pass_the_balance_check():
    from app.assessment import score_sme

    assessment = run(blank(applicant_a(), all_rows=True))
    result = balance_math(assessment)
    assert result.status == "warn" and "edits can't be ruled out" in result.message
    card = score_sme(assessment.profile, assessment.documents, as_of=AS_OF)
    parameter = next(p for p in card.parameters if p.id == "di.balance_math")
    assert parameter.status != "computed" or parameter.points < 100  # never full marks for an unverified statement


def test_partial_balance_columns_pass_only_when_most_rows_can_be_checked():
    docs = applicant_a()
    assert balance_math(run(blank(docs, every_nth=4))).status == "pass"  # a quarter blank: the rest still verifies
    mostly_blank = with_transactions(docs, lambda i, t: t.model_copy(update={"balance": None}) if i % 4 != 0 else t)
    assert balance_math(run(mostly_blank)).status == "warn"


def test_closing_balance_check_uses_the_chained_estimate_when_the_last_row_is_blank():
    docs = applicant_a()
    last = rows_of(docs) - 1
    blanked_last = with_transactions(docs, lambda i, t: t.model_copy(update={"balance": None}) if i == last else t)
    bank = next(d for d in run(blanked_last).documents if d.document_type == DocumentType.BANK_STATEMENT)
    assert next(c for c in bank.checks if c.id == "bank.closing_balance").status == "pass"

    wrong_close = replace_data(blanked_last, DocumentType.BANK_STATEMENT, closing_balance=Extracted[float](value=1.0, confidence=0.9, source=Source.OCR))
    bank = next(d for d in run(wrong_close).documents if d.document_type == DocumentType.BANK_STATEMENT)
    closing = next(c for c in bank.checks if c.id == "bank.closing_balance")
    assert closing.status == "fail" and "worked out from the rows" in closing.message


def test_blank_balances_do_not_remove_credits_or_invent_an_average_balance():
    clean = run(applicant_a()).profile.cashflow
    sparse = run(blank(applicant_a(), every_nth=4)).profile.cashflow
    stripped = run(blank(applicant_a(), all_rows=True)).profile.cashflow

    for cash in (sparse, stripped):  # money in and out is unaffected by a missing running balance
        assert cash.avg_monthly_credits.value == clean.avg_monthly_credits.value
        assert cash.foir.value == clean.foir.value and cash.bounces_6m.value == clean.bounces_6m.value
    assert sparse.avg_monthly_balance is not None
    assert stripped.avg_monthly_balance is None  # not 0 and not a guess


def test_assessment_goes_pending_on_balance_parameters_when_few_balances_are_printed():
    from app.assessment import score_sme

    def parameter(docs, pid):
        a = run(docs)
        return next(p for p in score_sme(a.profile, a.documents, as_of=AS_OF).parameters if p.id == pid)

    assert parameter(applicant_a(), "bc.low_balance_days").status == "computed"
    stripped = blank(applicant_a(), all_rows=True)
    low = parameter(stripped, "bc.low_balance_days")
    assert low.status == "pending" and "running balance" in low.reason
    assert parameter(stripped, "bc.liquidity_cushion").status == "pending"


# ---- Schema version ----------------------------------------------------------------------------------------


def test_schema_version_is_1_2_but_saved_1_0_and_1_1_payloads_still_validate():
    from app.schemas import SmeProfile
    from app.schemas.common import SCHEMA_VERSION
    from app.schemas.documents import DocumentEnvelope
    from app.schemas.examples import example_pan_envelope, example_sme_profile

    assert SCHEMA_VERSION == "1.2"
    assert example_pan_envelope().schema_version == "1.2" and example_sme_profile().schema_version == "1.2"
    # The dashboard saves the profile in the browser and posts it back later: an older one must not be rejected.
    for model, build in ((DocumentEnvelope, example_pan_envelope), (SmeProfile, example_sme_profile)):
        for old_version in ("1.0", "1.1"):
            old = build().model_dump(mode="json") | {"schema_version": old_version}
            assert model.model_validate(old).schema_version == old_version
    with pytest.raises(ValidationError):
        SmeProfile.model_validate(example_sme_profile().model_dump(mode="json") | {"schema_version": "2.0"})
