"""The twelve parameters that read the bureau report, financial statements, sanction letter and settlement report.

Applicant A (the clean sample) plus synthetic envelopes of the four newer document types. The samples themselves
carry none of them, so their scorecards are unchanged by these parameters (pinned in test_assessment_scoring.py).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest
from assessment_support import sensitive_strings

from app.assessment import REGISTRY, load_config, score_sme
from app.samples import AS_OF, BUREAU_A, applicant_a
from app.schemas.common import DocumentType, Extracted, Source
from app.schemas.documents import (
    BureauReport,
    DocumentEnvelope,
    FileInfo,
    FinancialStatements,
    SanctionLetter,
    SettlementMonth,
    SettlementReport,
)
from app.scoring import assess

NEW_IDS = [
    "rb.cmr", "rb.worst_dpd_24m", "rb.enquiries_90d", "rb.adverse_flags",
    "fn.revenue_growth_yoy", "fn.net_margin", "fn.leverage", "fn.dscr",
    "bc.od_utilisation", "bc.margin_facility", "bc.facility_trend", "bc.pg_settlements",
]


# ---- builders ------------------------------------------------------------------------------------------------


def ext(value, confidence=0.95):
    return Extracted(value=value, confidence=confidence, source=Source.PARSER)


def envelope(doc_type, data, doc_id, *, day=1, status="verified"):
    return DocumentEnvelope(
        document_id=doc_id, sme_id="SAMPLE-A", document_type=doc_type, status=status,
        uploaded_at=datetime(2026, 10, day, tzinfo=timezone.utc),
        file=FileInfo(file_name=f"{doc_id}.pdf", mime_type="application/pdf", size_bytes=1000, sha256="a" * 64),
        data=data,
    )


def bureau(**fields):
    fields.setdefault("report_date", date(2026, 9, 30))
    return envelope(DocumentType.BUREAU_REPORT, BureauReport(**{k: ext(v) for k, v in fields.items()}), "bureau-1")


GOOD_BUREAU = dict(cmr_rank=3, max_dpd_24m=0, enquiries_90d=1, written_off_or_settled=False, suit_filed_or_wilful_default=False)
BAD_BUREAU = dict(cmr_rank=8, max_dpd_24m=75, enquiries_90d=7, written_off_or_settled=True, suit_filed_or_wilful_default=False)

GOOD_FIN = dict(
    financial_year="2025-26", prior_financial_year="2024-25", audit_status="audited",
    revenue=24_000_000.0, prior_revenue=20_000_000.0, profit_after_tax=1_800_000.0, net_worth=6_000_000.0,
    long_term_borrowings=2_000_000.0, short_term_borrowings=1_000_000.0,
    depreciation=400_000.0, interest_expense=300_000.0, principal_repayments=500_000.0,
)
BAD_FIN = dict(GOOD_FIN, revenue=15_000_000.0, profit_after_tax=-200_000.0, net_worth=1_000_000.0,
               long_term_borrowings=3_000_000.0, short_term_borrowings=2_500_000.0,
               depreciation=100_000.0, interest_expense=600_000.0, principal_repayments=900_000.0)


def financials(doc_id="fin-1", day=1, **fields):
    fields = {**GOOD_FIN, **fields}
    return envelope(DocumentType.FINANCIAL_STATEMENTS, FinancialStatements(**{k: ext(v) for k, v in fields.items()}), doc_id, day=day)


def sanction(doc_id="sanction-1", day=1, **fields):
    fields = {"facility_type": "Overdraft", "sanctioned_amount": 1_000_000.0, "sanction_date": date(2026, 4, 1), "fd_lien_or_margin": False, **fields}
    return envelope(DocumentType.SANCTION_LETTER, SanctionLetter(**{k: ext(v) for k, v in fields.items()}), doc_id, day=day)


def settlement(months, doc_id="settle-1"):
    rows = [SettlementMonth(month=m, gross=g, fees=g * 0.02, net=g * 0.98, fee_pct=2.0, txn_count=100) for m, g in months.items()]
    return envelope(DocumentType.SETTLEMENT_REPORT, SettlementReport(months=rows), doc_id)


def credits_by_month(docs):
    bank = next(d for d in docs if d.document_type == DocumentType.BANK_STATEMENT).data
    totals: dict[str, float] = {}
    for t in bank.transactions:
        if t.credit:
            totals[f"{t.date:%Y-%m}"] = totals.get(f"{t.date:%Y-%m}", 0.0) + t.credit
    return totals


def overdrawn(docs, shift):
    """Applicant A's statement with every balance lowered by `shift` (opening and closing too, so the math still holds)."""
    out = []
    for d in docs:
        if d.document_type == DocumentType.BANK_STATEMENT:
            data = d.data
            data = data.model_copy(update={
                "opening_balance": data.opening_balance.model_copy(update={"value": data.opening_balance.value - shift}),
                "closing_balance": data.closing_balance.model_copy(update={"value": data.closing_balance.value - shift}),
                "transactions": [t.model_copy(update={"balance": t.balance - shift}) for t in data.transactions],
            })
            d = d.model_copy(update={"data": data})
        out.append(d)
    return out


def score(extra=(), *, base=None, bureau_score=BUREAU_A):
    docs = [*(base if base is not None else applicant_a()), *extra]
    assessment = assess("SAMPLE-A", docs, bureau=bureau_score, sector="retail", as_of=AS_OF)
    return score_sme(assessment.profile, assessment.documents, as_of=AS_OF)


def row(card, pid):
    return next(p for p in card.parameters if p.id == pid)


def full_set():
    base = applicant_a()
    max_balance = max(t.balance for t in next(d for d in base if d.document_type == DocumentType.BANK_STATEMENT).data.transactions)
    docs = overdrawn(base, max_balance + 150_000)
    months = {m: v * 0.4 for m, v in credits_by_month(docs).items()}
    extra = [
        bureau(**GOOD_BUREAU), financials(),
        sanction("sanction-new", sanction_date=date(2026, 4, 1), sanctioned_amount=1_200_000.0),
        sanction("sanction-old", sanction_date=date(2025, 4, 1), sanctioned_amount=800_000.0),
        settlement(months),
    ]
    return docs, extra


# ---- coverage ----------------------------------------------------------------------------------------------


def test_the_samples_are_unchanged_but_every_new_parameter_is_still_listed():
    card = score()
    assert [p.id for p in card.parameters if p.id in NEW_IDS] and all(row(card, i).status == "pending" for i in NEW_IDS)
    assert all(row(card, i).reason for i in NEW_IDS)  # each says what document it waits for
    assert card.coverage.coverage_pct == pytest.approx(45.3, abs=0.1)


def test_all_twelve_compute_with_the_four_documents_and_coverage_rises():
    base = score()
    docs, extra = full_set()
    card = score(extra, base=docs)

    assert {i: row(card, i).status for i in NEW_IDS} == {i: "computed" for i in NEW_IDS}
    assert card.coverage.coverage_pct > base.coverage.coverage_pct + 20
    print(f"coverage with the four documents: {card.coverage.coverage_pct}% (samples: {base.coverage.coverage_pct}%)")
    assert card.coverage.coverage_pct < 100


# ---- worse input never scores better --------------------------------------------------------------------------


def _bureau(good):
    return [bureau(**(GOOD_BUREAU if good else BAD_BUREAU))]


CASES = {
    "rb.cmr": lambda good: _bureau(good),
    "rb.worst_dpd_24m": lambda good: _bureau(good),
    "rb.enquiries_90d": lambda good: _bureau(good),
    "rb.adverse_flags": lambda good: _bureau(good),
    "fn.revenue_growth_yoy": lambda good: [financials(**({} if good else BAD_FIN))],
    "fn.net_margin": lambda good: [financials(**({} if good else BAD_FIN))],
    "fn.leverage": lambda good: [financials(**({} if good else BAD_FIN))],
    "fn.dscr": lambda good: [financials(**({} if good else BAD_FIN))],
    "bc.margin_facility": lambda good: [sanction(fd_lien_or_margin=not good)],
    "bc.facility_trend": lambda good: [
        sanction("s-new", sanctioned_amount=1_200_000.0 if good else 500_000.0, sanction_date=date(2026, 4, 1)),
        sanction("s-old", sanctioned_amount=800_000.0, sanction_date=date(2025, 4, 1)),
    ],
}


@pytest.mark.parametrize("pid", list(CASES))
def test_a_worse_input_never_scores_better_and_never_raises_the_index(pid):
    better, worse = score(CASES[pid](True)), score(CASES[pid](False))
    assert row(better, pid).status == row(worse, pid).status == "computed", pid
    assert row(worse, pid).points < row(better, pid).points, pid
    assert worse.index <= better.index, pid


def test_overdraft_utilisation_and_settlements_get_worse_as_the_inputs_do():
    base = applicant_a()
    top = max(t.balance for t in next(d for d in base if d.document_type == DocumentType.BANK_STATEMENT).data.transactions)
    light, heavy = overdrawn(base, top + 20_000), overdrawn(base, top + 700_000)
    letter = [sanction()]
    low, high = row(score(letter, base=light), "bc.od_utilisation"), row(score(letter, base=heavy), "bc.od_utilisation")
    assert low.status == high.status == "computed" and high.points < low.points

    credits = credits_by_month(base)
    fits = row(score([settlement({m: v * 0.4 for m, v in credits.items()})]), "bc.pg_settlements")
    exceeds = row(score([settlement({m: v * 1.6 for m, v in credits.items()})]), "bc.pg_settlements")
    assert fits.status == exceeds.status == "computed" and exceeds.points < fits.points


def test_every_one_sided_numeric_band_list_is_best_first():
    """Config-level monotonicity: with first-match-wins, points must not rise as a value gets worse."""
    for pid, pc in load_config().parameters.items():
        one_sided = all((b.min is None) != (b.max is None) or (b.min is None and b.max is None) for b in pc.bands if b.value is None)
        if pc.bands and pc.bands[0].value is None and one_sided:
            points = [b.points for b in pc.bands]
            assert points == sorted(points, reverse=True), pid


# ---- bureau ------------------------------------------------------------------------------------------------


def test_a_commercial_only_report_still_scores_the_cmr_rank():
    """No consumer score, so nothing reaches SmeProfile.bureau: the engine must read the report itself."""
    card = score([bureau(cmr_rank=2)], bureau_score=None)
    cmr = row(card, "rb.cmr")
    assert cmr.status == "computed" and cmr.points == 100
    assert any("not pulled from a bureau" in f for f in cmr.flags)  # uploaded, so unverified
    assert row(card, "rb.consumer_score").status == "pending"


def test_cmr_lower_is_better_and_out_of_range_is_ignored():
    assert row(score([bureau(cmr_rank=1)]), "rb.cmr").points > row(score([bureau(cmr_rank=9)]), "rb.cmr").points
    assert row(score([bureau(cmr_rank=14)]), "rb.cmr").status == "pending"


def test_a_missing_adverse_flag_is_never_treated_as_clean():
    one_false_one_unknown = row(score([bureau(written_off_or_settled=False)]), "rb.adverse_flags")
    assert one_false_one_unknown.status == "pending"
    both_false = row(score([bureau(written_off_or_settled=False, suit_filed_or_wilful_default=False)]), "rb.adverse_flags")
    assert both_false.status == "computed" and both_false.points == 100
    one_true_one_unknown = row(score([bureau(suit_filed_or_wilful_default=True)]), "rb.adverse_flags")
    assert one_true_one_unknown.status == "computed" and one_true_one_unknown.points == 0


def test_an_old_report_is_flagged_not_discarded():
    card = score([bureau(cmr_rank=3, report_date=date(2026, 3, 1))])
    cmr = row(card, "rb.cmr")
    assert cmr.status == "computed" and any("days old" in f for f in cmr.flags)


def test_the_profile_bureau_wins_over_an_uploaded_report():
    from app.schemas.profile import BureauScore

    pulled = BureauScore(value=780, source="bureau", as_of=date(2026, 10, 1), cmr_rank=1, max_dpd_24m=0)
    card = score([bureau(cmr_rank=9, max_dpd_24m=120)], bureau_score=pulled)
    assert row(card, "rb.cmr").points == 100 and row(card, "rb.worst_dpd_24m").points == 100
    assert not any("not pulled from a bureau" in f for f in row(card, "rb.cmr").flags)


# ---- financial statements ----------------------------------------------------------------------------------------


def test_zero_or_negative_net_worth_is_the_worst_leverage_band_not_the_best():
    negative = row(score([financials(net_worth=-500_000.0)]), "fn.leverage")
    assert negative.status == "computed" and negative.points == 10
    assert "zero or negative" in negative.reason
    assert row(score([financials(net_worth=0.0)]), "fn.leverage").points == 10


def test_leverage_needs_both_borrowings_or_a_reported_ratio():
    assert row(score([financials(short_term_borrowings=None)]), "fn.leverage").status == "pending"
    reported = row(score([financials(short_term_borrowings=None, debt_to_equity=0.4)]), "fn.leverage")
    assert reported.status == "computed" and "as reported" in reported.reason


def test_dscr_with_no_debt_service_and_growth_from_a_zero_base_are_not_scored():
    assert row(score([financials(principal_repayments=0.0, interest_expense=0.0)]), "fn.dscr").status == "pending"
    assert row(score([financials(prior_revenue=0.0)]), "fn.revenue_growth_yoy").status == "pending"


def test_ratios_are_recomputed_from_the_figures_not_taken_from_a_reported_value():
    card = score([financials(net_margin=9.9, dscr=9.9)])  # nonsense reported values must be ignored
    assert row(card, "fn.net_margin").points == 80  # 1.8M / 24M = 7.5%
    assert row(card, "fn.dscr").points == 100  # (1.8 + 0.4 + 0.3) / (0.5 + 0.3) = 3.1


def test_provisional_figures_count_at_reduced_weight_and_are_flagged():
    audited, provisional = score([financials()]), score([financials(audit_status="provisional")])
    assert row(provisional, "fn.dscr").points == row(audited, "fn.dscr").points
    assert any("provisional" in f for f in row(provisional, "fn.dscr").flags)
    assert provisional.coverage.effective_weight < audited.coverage.effective_weight


def test_only_the_latest_financial_year_is_used_never_a_mix():
    old_good = financials("fin-old", financial_year="2023-24", prior_financial_year="2022-23")
    new_bad = financials("fin-new", financial_year="2025-26", **{k: v for k, v in BAD_FIN.items() if k not in ("financial_year", "prior_financial_year")})
    card = score([old_good, new_bad])
    assert row(card, "fn.net_margin").points < 30  # the loss-making newer year, not the profitable older one
    assert score([new_bad, old_good]).index == card.index  # order of upload does not matter


# ---- sanction letters and bank ------------------------------------------------------------------------------------


def test_overdraft_utilisation_is_never_zero_by_default():
    never_negative = row(score([sanction()]), "bc.od_utilisation")  # Applicant A's balances are all positive
    assert never_negative.status == "pending" and "cannot be tied" in never_negative.reason


def test_a_term_loan_letter_is_not_an_overdraft():
    base = applicant_a()
    top = max(t.balance for t in next(d for d in base if d.document_type == DocumentType.BANK_STATEMENT).data.transactions)
    card = score([sanction(facility_type="Term loan")], base=overdrawn(base, top + 100_000))
    assert row(card, "bc.od_utilisation").status == "pending"


def test_overdraft_pends_when_most_balances_are_not_printed():
    from app.schemas.documents import Transaction  # noqa: F401  (documents the field being blanked)

    base = applicant_a()
    top = max(t.balance for t in next(d for d in base if d.document_type == DocumentType.BANK_STATEMENT).data.transactions)
    docs = overdrawn(base, top + 100_000)
    blanked = []
    for d in docs:
        if d.document_type == DocumentType.BANK_STATEMENT:
            rows = [t.model_copy(update={"balance": None}) if i % 4 else t for i, t in enumerate(d.data.transactions)]
            d = d.model_copy(update={"data": d.data.model_copy(update={"transactions": rows})})
        blanked.append(d)
    assert row(score([sanction()], base=blanked), "bc.od_utilisation").status == "pending"


def test_margin_facility_states_and_unknown():
    assert row(score([sanction(fd_lien_or_margin=True)]), "bc.margin_facility").points == 40
    assert row(score([sanction(fd_lien_or_margin=False)]), "bc.margin_facility").points == 100
    assert row(score([sanction(fd_lien_or_margin=None)]), "bc.margin_facility").status == "pending"


def test_facility_trend_needs_two_dated_letters_of_the_same_kind():
    only_one = row(score([sanction()]), "bc.facility_trend")
    assert only_one.status == "pending"
    different_kinds = [sanction("a", facility_type="Overdraft", sanction_date=date(2026, 4, 1)),
                       sanction("b", facility_type="Term loan", sanction_date=date(2025, 4, 1))]
    assert row(score(different_kinds), "bc.facility_trend").status == "pending"
    same = [sanction("a", sanctioned_amount=1_000_000.0, sanction_date=date(2026, 4, 1)),
            sanction("b", sanctioned_amount=1_000_000.0, sanction_date=date(2025, 4, 1))]
    assert row(score(same), "bc.facility_trend").points == 75


# ---- settlements ----------------------------------------------------------------------------------------------------


def test_settlements_need_two_common_months_and_a_low_share_is_fine():
    credits = credits_by_month(applicant_a())
    first_month = next(iter(credits))
    assert row(score([settlement({first_month: 100_000.0})]), "bc.pg_settlements").status == "pending"
    tiny = row(score([settlement({m: v * 0.02 for m, v in credits.items()})]), "bc.pg_settlements")
    assert tiny.status == "computed" and tiny.points == 100  # a mostly-cash business is not penalised
    far_above = row(score([settlement({m: v * 2.0 for m, v in credits.items()})]), "bc.pg_settlements")
    assert far_above.points == 10


def test_later_settlement_uploads_win_for_the_same_month():
    credits = credits_by_month(applicant_a())
    wrong = settlement({m: v * 3.0 for m, v in credits.items()}, "settle-old")
    right = settlement({m: v * 0.4 for m, v in credits.items()}, "settle-new")
    right = right.model_copy(update={"uploaded_at": datetime(2026, 10, 20, tzinfo=timezone.utc)})
    assert row(score([wrong, right]), "bc.pg_settlements").points == 100


# ---- cross-cutting -------------------------------------------------------------------------------------------------------


def test_failed_envelopes_are_ignored():
    failed = bureau(**GOOD_BUREAU).model_copy(update={"status": "failed", "data": None, "error": "unreadable"})
    assert row(score([failed], bureau_score=None), "rb.cmr").status == "pending"


def test_fairness_flags_travel_with_the_two_new_flagged_parameters_and_they_are_not_headlined():
    docs, extra = full_set()
    card = score(extra, base=docs)
    for pid in ("fn.net_margin", "bc.margin_facility"):
        assert any(f.startswith("Fairness review:") for f in row(card, pid).flags), pid
    headlines = " ".join(card.strengths + card.concerns)
    assert "profit margin" not in headlines and "cash-margined" not in headlines


def test_the_full_scorecard_carries_no_identifiers():
    docs, extra = full_set()
    text = json.dumps(score(extra, base=docs).model_dump(mode="json"), ensure_ascii=False)
    for secret in sensitive_strings():
        assert secret not in text, secret


def test_new_parameters_have_evidence_pointing_at_the_exact_field():
    docs, extra = full_set()
    card = score(extra, base=docs)
    expected = {"rb.cmr": "data.cmr_rank", "fn.dscr": "data.interest_expense", "bc.margin_facility": "data.fd_lien_or_margin",
                "bc.od_utilisation": "data.sanctioned_amount"}
    for pid, field in expected.items():
        assert any(e.field == field for e in row(card, pid).evidence), pid


def test_registry_and_config_still_agree_for_the_new_parameters():
    cfg = load_config()
    for pid in NEW_IDS:
        parameter = next(p for p in REGISTRY if p.id == pid)
        assert parameter.computable and cfg.parameters[pid].bands, pid


# ---- free text never reaches the card ------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "kind"), [
    ("Overdraft", "overdraft"), ("OD facility", "overdraft"), ("Cash Credit limit", "cash_credit"), ("CC", "cash_credit"),
    ("Working Capital Demand Loan", "working_capital"), ("Term loan", "term_loan"),
    ("Facility for Kumar Traders", "other"), ("", "other"), (None, "other"),
])
def test_facility_kind_is_a_closed_list(text, kind):
    from app.assessment.features import _facility_kind

    assert _facility_kind(text) == kind


def test_a_business_name_in_the_facility_type_never_reaches_the_scorecard():
    named = [
        sanction("a", facility_type="Cash credit to M/s Kumar Traders", sanctioned_amount=1_000_000.0, sanction_date=date(2026, 4, 1)),
        sanction("b", facility_type="Cash credit to M/s Kumar Traders", sanctioned_amount=800_000.0, sanction_date=date(2025, 4, 1)),
    ]
    card = score(named)
    assert row(card, "bc.facility_trend").status == "computed" and row(card, "bc.facility_trend").points == 100
    assert "kumar" not in json.dumps(card.model_dump(mode="json"), ensure_ascii=False).lower()

    unrecognised = [
        sanction("c", facility_type="Facility for Kumar Traders", sanctioned_amount=1_000_000.0, sanction_date=date(2026, 4, 1)),
        sanction("d", facility_type="Facility for Kumar Traders", sanctioned_amount=800_000.0, sanction_date=date(2025, 4, 1)),
    ]
    card = score(unrecognised)
    assert row(card, "bc.facility_trend").status == "pending"  # an unrecognised type can't be compared
    assert "kumar" not in json.dumps(card.model_dump(mode="json"), ensure_ascii=False).lower()


def test_the_config_version_changed_when_the_bands_did():
    assert load_config().config_version == "2026.10-placeholder.2"
    assert score().config_version == "2026.10-placeholder.2"
