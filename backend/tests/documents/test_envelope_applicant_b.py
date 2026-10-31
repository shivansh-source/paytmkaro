"""Applicant B end to end: documents carrying the facts of app.samples.applicant_b(), extracted and bridged
into envelopes, must give the same assessment as the sample envelopes themselves."""

import pytest
from textdocs import applicant_b_texts, loaded

from app.documents.extract.envelope import build_envelope
from app.documents.extract.pipeline import extract_detailed
from app.documents.models import DocumentType as DT
from app.documents.models import Page, TextSource
from app.samples import AS_OF, applicant_b
from app.schemas.documents import DocumentEnvelope
from app.scoring import assess

KINDS = {"pan": DT.PAN_CARD, "aadhaar": DT.AADHAAR, "gst": DT.GST_CERTIFICATE, "gstr3b": DT.GSTR_3B, "bank": DT.BANK_STATEMENT, "udyam": DT.UDYAM_CERTIFICATE}


@pytest.fixture(scope="module")
def bridged():
    envelopes, notes = [], []
    for kind, text in applicant_b_texts().items():
        # Ingest checked the full Aadhaar number before masking it; the sample says the check passed.
        flags = [True] if kind == "aadhaar" else []
        document = loaded(Page(index=0, text=text, text_source=TextSource.NATIVE, aadhaar_verhoeff_valid=flags))
        extraction = extract_detailed(document, KINDS[kind])
        built = build_envelope(extraction, document, sme_id="SAMPLE-B", document_id=f"b-{kind}", size_bytes=1000)
        envelopes.append(built.envelope)
        notes += built.notes
    return envelopes, notes


def _statuses(assessment):
    return {c.id: c.status.value for c in assessment.profile.cross_checks}


def test_every_envelope_round_trips(bridged):
    envelopes, _ = bridged
    assert len(envelopes) == 6
    for envelope in envelopes:
        assert DocumentEnvelope.model_validate(envelope.model_dump()) == envelope
        assert DocumentEnvelope.model_validate_json(envelope.model_dump_json()) == envelope


def test_cashflow_numbers_match_the_sample(bridged):
    ours, direct = assess("SAMPLE-B", bridged[0], as_of=AS_OF), assess("SAMPLE-B", applicant_b(), as_of=AS_OF)
    a, b = ours.profile.cashflow, direct.profile.cashflow

    assert a.bounces_6m.value == b.bounces_6m.value == 3
    assert a.foir.value == pytest.approx(b.foir.value, abs=0.001)
    assert a.gst_turnover_12m.value == pytest.approx(b.gst_turnover_12m.value, rel=1e-6)
    assert a.existing_emi_monthly.value == pytest.approx(b.existing_emi_monthly.value, rel=1e-6)
    assert a.avg_monthly_credits.value == pytest.approx(b.avg_monthly_credits.value, rel=1e-6)
    assert a.months_analyzed == b.months_analyzed


def test_planted_problems_are_caught_like_the_sample(bridged):
    ours, direct = assess("SAMPLE-B", bridged[0], as_of=AS_OF), assess("SAMPLE-B", applicant_b(), as_of=AS_OF)
    got, want = _statuses(ours), _statuses(direct)

    assert got["cross.name_match"] == want["cross.name_match"] == "warn"  # RAVI KUMAAR vs RAVI KUMAR
    assert got["cross.statement_gaps"] == want["cross.statement_gaps"] == "fail"  # GSTR-3B July 2026 missing
    assert got["cross.balance_math"] == want["cross.balance_math"] == "fail"  # 10 Feb 2026 credit 24k -> 54k
    for check in ("cross.pan_in_gstin", "cross.dob_match"):
        assert got[check] == want[check]
    # Readiness is capped at 49 when balance math fails, in both.
    assert ours.profile.readiness.score == direct.profile.readiness.score <= 49


def test_the_edited_row_is_the_one_flagged(bridged):
    assessment = assess("SAMPLE-B", bridged[0], as_of=AS_OF)
    math = next(c for c in assessment.profile.cross_checks if c.id == "cross.balance_math")
    assert "10 Feb 2026" in math.message


def test_bridge_loses_nothing_the_envelope_can_hold(bridged):
    _, notes = bridged
    assert notes == []


def test_whole_assessment_matches_the_sample(bridged):
    """Every per-document check, every readiness component and every cross-check agrees (not just the capped score)."""
    ours, direct = assess("SAMPLE-B", bridged[0], as_of=AS_OF), assess("SAMPLE-B", applicant_b(), as_of=AS_OF)

    def checks(a):
        return {(d.document_type.value, c.id, c.status.value) for d in a.documents for c in d.checks}

    assert checks(ours) == checks(direct)
    assert ours.profile.readiness.model_dump() == direct.profile.readiness.model_dump()
    assert {(c.id, c.status.value) for c in ours.profile.cross_checks} == {(c.id, c.status.value) for c in direct.profile.cross_checks}
