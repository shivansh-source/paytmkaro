"""score_sme end to end on the sample applicants: determinism, null columns, coverage, reasons, confidence."""

from __future__ import annotations

from datetime import date

import pytest

from app.assessment import REGISTRY, score_sme
from app.samples import AS_OF, BUREAU_A, applicant_a
from app.samples.applicants import _envelope, _x
from app.schemas.common import DocumentType, Extracted, RowProvenance, Source
from app.schemas.documents import ItrV
from app.schemas.profile import BureauScore
from app.scoring import assess
from assessment_support import by_id, card, dump, pipeline


def _replace(docs, doc_type, **changes):
    """Copy of `docs` with the data of one document edited."""
    out = []
    for env in docs:
        if env.document_type == doc_type:
            env = env.model_copy(update={"data": env.data.model_copy(update=changes)})
        out.append(env)
    return out


def _without(docs, *doc_types):
    return [e for e in docs if e.document_type not in doc_types]


def _card_without(*doc_types):
    a = assess("SAMPLE-A", _without(applicant_a(), *doc_types), bureau=BUREAU_A, as_of=AS_OF)
    return score_sme(a.profile, a.documents, as_of=AS_OF)


# ---- determinism and completeness ----------------------------------------------------------------


def test_same_input_gives_identical_output():
    profile, docs = pipeline("B")
    assert dump(score_sme(profile, docs, as_of=AS_OF)) == dump(score_sme(profile, list(docs), as_of=AS_OF))
    assert dump(card("A")) == dump(card("A"))


def test_as_of_defaults_to_profile_timestamp_not_the_clock():
    profile, docs = pipeline("A")
    assert score_sme(profile, docs).as_of == profile.updated_at.date() == AS_OF


@pytest.mark.parametrize("which", ["A", "B"])
def test_every_registry_parameter_is_present_with_a_reason(which):
    c = card(which)
    assert [r.id for r in c.parameters] == [p.id for p in REGISTRY]
    assert list(c.features.features) == [p.id for p in REGISTRY]
    for r in c.parameters:
        assert r.status in ("computed", "pending", "not_applicable")
        assert r.reason
        if r.status == "computed":
            assert r.points is not None and r.band and r.value is not None
            assert r.effective_weight > 0
            assert c.features.features[r.id] == r.value
        else:
            assert r.points is None and r.value is None and r.effective_weight == 0
            assert c.features.features[r.id] is None


@pytest.mark.parametrize("which", ["A", "B"])
def test_pending_parameters_name_their_missing_field_or_document(which):
    c = card(which)
    pending = [r for r in c.parameters if r.status == "pending"]
    assert len(pending) == 26  # 24 pending by schema + the 2 ITR-V parameters (document not uploaded)
    for r in pending:
        assert r.waits_for and len(r.waits_for) > 8, r.id
        assert r.reason.startswith("Not scored:")
    waits = {r.id: r.waits_for for r in pending}
    assert "bureau_report.cmr_rank" in waits["rb.cmr"]
    assert "sanction_letter" in waits["bc.margin_facility"]
    assert "financial_statements" in waits["fn.dscr"]
    assert "settlement_report" in waits["bc.pg_settlements"]
    assert "itr_v" in waits["sp.itr_filed"]


def test_registry_level_counts():
    computable = [p for p in REGISTRY if p.computable]
    assert len(REGISTRY) == 51 and len(computable) == 27 and len(REGISTRY) - len(computable) == 24


# ---- coverage math ---------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["A", "B"])
def test_coverage_and_index_math_recomputed_from_rows(which):
    c = card(which)
    rows = [r for r in c.parameters if r.status == "computed"]
    total = sum(r.weight for r in c.parameters if r.in_total)
    assert c.coverage.total_weight == total == 85
    assert c.coverage.effective_weight == pytest.approx(sum(r.effective_weight for r in rows))
    assert c.coverage.coverage_pct == pytest.approx(100 * c.coverage.effective_weight / total, abs=0.05)
    expected = sum(r.effective_weight * r.points for r in rows) / sum(r.effective_weight for r in rows)
    assert c.index == pytest.approx(expected, abs=0.05)
    assert c.coverage.computed_count == len(rows) == 25
    # responsiveness is outside the weight base, so it is not in the pending count
    assert c.coverage.pending_count + c.coverage.computed_count + c.coverage.not_applicable_count == 50


def test_responsiveness_is_outside_the_weight_base_but_still_listed():
    r = by_id(card("A"))["rb.responsiveness"]
    assert r.in_total is False and r.status == "pending"


def test_coverage_is_partial_and_labelled_so():
    c = card("A")
    assert 45 <= c.coverage.coverage_pct < 50 and c.coverage.label == "partial"


def test_missing_documents_lower_coverage_not_the_scoring_of_what_remains():
    full = card("A")
    c = _card_without(DocumentType.GSTR3B)
    assert c.coverage.coverage_pct < full.coverage.coverage_pct
    ids = by_id(c)
    for pid in ("bc.gst_bank_consistency", "bc.gst_filing_timeliness", "bc.gst_turnover_trend", "bc.turnover_scale"):
        assert ids[pid].status == "pending" and ids[pid].points is None and ids[pid].waits_for
    assert "gstr3b" in ids["bc.gst_filing_timeliness"].waits_for
    # parameters that do not depend on the removed document score exactly as before
    assert ids["bc.foir"].points == by_id(full)["bc.foir"].points
    assert ids["bc.bounces_6m"].effective_weight == by_id(full)["bc.bounces_6m"].effective_weight


def test_without_bank_statement_and_gst_the_grade_is_insufficient_data():
    c = _card_without(DocumentType.BANK_STATEMENT, DocumentType.GSTR3B)
    assert c.coverage.coverage_pct < 25
    assert c.grade == "insufficient_data"


def test_empty_file_is_all_null_columns():
    a = assess("EMPTY", [], as_of=AS_OF)
    c = score_sme(a.profile, a.documents)
    assert c.index is None and c.grade == "insufficient_data"
    assert all(r.status == "pending" for r in c.parameters)
    assert set(c.features.features.values()) == {None}


def test_not_applicable_warehouse_for_a_service_business():
    profile, docs = pipeline("A")
    assert by_id(score_sme(profile, docs, as_of=AS_OF))["cp.warehouse_status"].status == "pending"  # trading firm
    services = _replace(docs, DocumentType.UDYAM, major_activity=_x("services", 0.98, Source.PARSER))
    c = score_sme(profile, services, as_of=AS_OF)
    r = by_id(c)["cp.warehouse_status"]
    assert r.status == "not_applicable" and "only needed for trading" in r.reason
    assert c.coverage.applicable_weight == c.coverage.total_weight - 2
    assert c.coverage.not_applicable_count == 1


# ---- A versus B -----------------------------------------------------------------------------------


def test_clean_applicant_scores_clearly_higher_than_messy_one():
    a, b = card("A"), card("B")
    assert a.index - b.index >= 20
    assert a.grade == "strong" and b.grade in ("cautious", "weak")
    assert a.grade_capped_by == [] and b.grade_capped_by
    assert by_id(a)["di.balance_math"].points == 100 and by_id(b)["di.balance_math"].points == 0


def test_messy_applicants_reasons_cite_the_planted_problems():
    b = card("B")
    text = " ".join(b.concerns).lower()
    assert "bounced" in text  # 3 bounces
    assert "foir" in text  # heavy EMI burden
    assert "balance" in text and "possible edit" in text  # balance-math tampering
    assert "missing gstr-3b for jul 2026" in text  # the GST gap
    assert "14 months in business" in text  # short vintage
    p = by_id(b)
    assert p["bc.bounces_6m"].value == 3 and p["bc.bounces_6m"].points <= 15
    assert p["di.statement_gaps"].points == 0
    assert p["di.name_match"].points == 50  # near-match name warning, status only
    # the bank-derived figures say they may include the edited row
    assert "edited row" in p["bc.foir"].reason
    assert any(ref.field == "data.transactions" for ref in p["bc.foir"].evidence)
    assert b.provisional and any("critical" in r.lower() for r in b.provisional_reasons)


def test_clean_applicant_has_no_integrity_concerns_and_has_evidence_links():
    a = card("A")
    p = by_id(a)
    assert p["bc.foir"].points == 80 and p["bc.bounces_6m"].points == 100
    assert not any("balance" in c.lower() for c in a.concerns)
    assert p["bc.foir"].evidence[0].document_id == "sample-a-bank"
    assert p["cp.vintage"].evidence[0].document_id == "sample-a-udyam"
    assert p["di.tax_registration_link"].evidence


def test_structural_parameters_are_scored_but_never_headlined():
    a = card("A")
    assert by_id(a)["cp.msme_category"].status == "computed"
    headlines = " ".join(a.concerns + a.strengths)
    assert "Udyam category" not in headlines and "Constitution" not in headlines


def test_both_cards_report_config_version_and_uncalibrated_weights():
    for which in "AB":
        c = card(which)
        assert c.config_version.startswith("2026.10")
        assert c.weights_calibrated is False
        assert "not a probability of default" in c.disclaimer


# ---- optional document: ITR-V ---------------------------------------------------------------------


def _itr(year="2025-26", income=200_000.0):
    data = ItrV(pan_number=_x("ABCPK1234F"), assessment_year=_x(year), itr_form=_x("ITR-3"),
                gross_total_income=_x(income), acknowledgement_number=_x("123456789012345"))
    return _envelope("SAMPLE-A", "sample-a-itr", DocumentType.ITR_V, data, "digital_pdf", Source.PARSER)


def test_itr_v_turns_two_pending_parameters_into_computed_and_raises_coverage():
    profile, docs = pipeline("A")
    base = score_sme(profile, docs, as_of=AS_OF)
    c = score_sme(profile, [*docs, _itr()], as_of=AS_OF)
    p = by_id(c)
    assert p["sp.itr_filed"].status == "computed" and p["sp.itr_filed"].points == 100
    assert p["sp.itr_income_margin"].status == "computed" and p["sp.itr_income_margin"].points == 100  # 8.5% of turnover
    assert c.coverage.coverage_pct > base.coverage.coverage_pct
    stale = by_id(score_sme(profile, [*docs, _itr(year="2022-23")], as_of=AS_OF))["sp.itr_filed"]
    assert stale.points == 20


# ---- low-confidence handling ----------------------------------------------------------------------


def test_field_needing_review_halves_weight_flags_and_lowers_coverage():
    profile, docs = pipeline("A")
    base = score_sme(profile, docs, as_of=AS_OF)
    shaky = _replace(docs, DocumentType.BANK_STATEMENT, opening_balance=Extracted(value=150_000.0, confidence=0.7, source=Source.OCR))
    c = score_sme(profile, shaky, as_of=AS_OF)
    r, r0 = by_id(c)["bc.foir"], by_id(base)["bc.foir"]
    assert r.status == "computed" and r.low_confidence
    assert r.effective_weight == r0.effective_weight * 0.5 and r.points == r0.points
    assert "50% weight" in r.reason
    assert c.coverage.coverage_pct < base.coverage.coverage_pct
    assert c.provisional and any("opening_balance" in x for x in c.provisional_reasons)


def test_user_confirmed_field_counts_as_confident():
    profile, docs = pipeline("A")
    confirmed = _replace(docs, DocumentType.BANK_STATEMENT,
                         opening_balance=Extracted(value=150_000.0, confidence=0.7, source=Source.OCR, user_confirmed=True))
    r = by_id(score_sme(profile, confirmed, as_of=AS_OF))["bc.foir"]
    assert not r.low_confidence and r.effective_weight == 3


def test_unreadable_input_excludes_the_parameter_instead_of_scoring_it():
    profile, docs = pipeline("A")
    base = score_sme(profile, docs, as_of=AS_OF)
    broken = _replace(docs, DocumentType.BANK_STATEMENT, opening_balance=Extracted(value=150_000.0, confidence=0.3, source=Source.OCR))
    c = score_sme(profile, broken, as_of=AS_OF)
    r = by_id(c)["bc.foir"]
    assert r.status == "pending" and r.points is None
    assert "confirmation or re-upload" in r.waits_for and "opening_balance" in r.waits_for
    assert c.coverage.coverage_pct < base.coverage.coverage_pct


def test_many_low_confidence_table_rows_flag_the_parameter():
    profile, docs = pipeline("A")
    bank = next(e for e in docs if e.document_type == DocumentType.BANK_STATEMENT)
    txns = list(bank.data.transactions)
    weak = RowProvenance(source=Source.OCR, confidence=0.6)
    for i in range(0, len(txns), 5):  # 20% of rows
        txns[i] = txns[i].model_copy(update={"provenance": weak})
    r = by_id(score_sme(profile, _replace(docs, DocumentType.BANK_STATEMENT, transactions=txns), as_of=AS_OF))["bc.bounces_6m"]
    assert r.low_confidence and r.status == "computed"


def test_failed_envelope_status_alone_does_not_exclude_parameters():
    # B's bank statement is needs_review as a document; its figures must still be scored (and flagged).
    r = by_id(card("B"))["bc.bounces_6m"]
    assert r.status == "computed" and not r.low_confidence


def test_mock_bureau_score_is_counted_at_half_weight_and_marks_card_provisional():
    c = card("A")
    r = by_id(c)["rb.consumer_score"]
    assert r.low_confidence and r.effective_weight == 1.5 and r.weight == 3
    assert c.provisional


def test_real_bureau_pull_counts_at_full_weight():
    profile, docs = pipeline("A")
    real = profile.model_copy(update={"bureau": BureauScore(value=760, source="bureau", as_of=date(2026, 10, 1))})
    r = by_id(score_sme(real, docs, as_of=AS_OF))["rb.consumer_score"]
    assert not r.low_confidence and r.effective_weight == 3


def test_missing_bureau_score_is_pending_not_zero():
    profile, docs = pipeline("A")
    r = by_id(score_sme(profile.model_copy(update={"bureau": None}), docs, as_of=AS_OF))["rb.consumer_score"]
    assert r.status == "pending" and r.points is None
