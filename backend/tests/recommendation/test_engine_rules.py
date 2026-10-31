"""New lender rules, soft cutoffs, and the "what to change" suggestions."""

from app.recommendation import MatchInput, evaluate, load_lender_products, match_input, recommend
from app.samples import AS_OF, BUREAU_A, BUREAU_B, applicant_a, applicant_b
from app.schemas import LenderProduct, LoanRequest
from app.scoring import assess


def product(**overrides) -> LenderProduct:
    return LenderProduct.model_validate(
        {"id": "p", "lender": "Test Lender", "product": "Test loan", "pricing": {"apr_range": [18, 22], "processing_fee_pct": 2}, **overrides}
    )


def sme(**fields) -> MatchInput:
    return MatchInput(**{"sme_id": "x", "requested_amount": 500_000, **fields})


def test_soft_bureau_cutoff_warns_but_matches():
    hard = evaluate(sme(bureau_score=700), product(min_bureau_score=730))
    soft = evaluate(sme(bureau_score=700), product(min_bureau_score=730, bureau_score_is_hard_cutoff=False))
    assert hard.status == "not_yet"
    assert soft.status == "matched"
    assert soft.checks[0].outcome == "warn"
    assert "may still consider" in soft.reasons[0]


def test_vintage_by_constitution_overrides_general_minimum():
    p = product(
        min_business_vintage_months=12,
        min_business_vintage_by_constitution=[{"constitution": "proprietorship", "min_business_vintage_months": 36}],
    )
    assert evaluate(sme(business_vintage_months=24, constitution="proprietorship"), p).status == "not_yet"
    assert evaluate(sme(business_vintage_months=24, constitution="pvt_ltd"), p).status == "matched"


def test_itr_requirement():
    p = product(itr_required=True)
    result = evaluate(sme(has_itr=False), p)
    assert result.status == "not_yet"
    assert result.fixes[0].kind == "add_document"
    assert evaluate(sme(has_itr=True), p).status == "matched"


def test_collateral_above_free_limit_is_a_warning():
    result = evaluate(sme(), product(collateral_free_limit=200_000))
    assert result.status == "matched"
    assert result.checks[0].outcome == "warn"


def test_negative_geography_blocks():
    result = evaluate(sme(state="Karnataka"), product(negative_geographies=["Karnataka"]))
    assert result.status == "not_yet" and result.fixes[0].kind == "not_eligible"


def test_fixes_are_computed_from_the_gap():
    p = product(min_business_vintage_months=24, max_foir=0.4, min_bureau_score=730)
    fixes = {f.rule: f for f in evaluate(sme(business_vintage_months=14, foir=0.5, bureau_score=700), p).fixes}
    assert fixes["business_vintage"].months == 10
    assert "Eligible in 10 months" in fixes["business_vintage"].message
    assert "by 30 points" in fixes["bureau_score"].message
    assert "by about 20%" in fixes["foir"].message  # 0.5 -> 0.4


def test_amount_only_fix_is_a_quick_fix_and_ranks_first():
    big = product(id="big", ticket_size={"min": 100_000, "max": 1_000_000}, pricing={"apr_range": [24, 26], "processing_fee_pct": 2})
    strict = product(id="strict", min_business_vintage_months=60, pricing={"apr_range": [14, 16], "processing_fee_pct": 1})
    results = recommend(sme(requested_amount=1_400_000, business_vintage_months=14), [strict, big])
    assert [r.product_id for r in results] == ["big", "strict"]
    assert results[0].quick_fix and results[0].fixes[0].message == "Ask for ₹10,00,000 or less"


def _match(docs, bureau, amount):
    profile = assess("S", docs, bureau=bureau, sector="retail", as_of=AS_OF).profile
    return recommend(match_input(profile, LoanRequest(sme_id="S", amount=amount, tenure_months=24)), load_lender_products())


def test_full_pipeline_applicant_a_matches_every_lender():
    assert {r.status for r in _match(applicant_a(), BUREAU_A, 500_000)} == {"matched"}


def test_full_pipeline_applicant_b_gets_the_not_yet_path():
    results = {r.lender: r for r in _match(applicant_b(), BUREAU_B, 500_000)}
    bank_a = results["Demo Bank A"]
    assert bank_a.status == "not_yet"
    assert {f.rule for f in bank_a.fixes} == {"business_vintage", "annual_turnover", "bureau_score", "bounces_6m"}
    assert results["Demo NBFC B"].status == "matched"


def test_true_apr_includes_fees_and_fit_has_a_label():
    result = evaluate(sme(requested_tenure_months=24), product(pricing={"apr_range": [16, 20], "processing_fee_pct": 2}))
    assert result.true_apr_pct > 16
    assert result.fit_label == "strong"  # no thresholds to clear
    assert evaluate(sme(business_vintage_months=1), product(min_business_vintage_months=24)).fit_label is None
