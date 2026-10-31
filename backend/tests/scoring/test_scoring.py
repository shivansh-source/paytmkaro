from app.samples import AS_OF, BUREAU_A, BUREAU_B, applicant_a, applicant_b
from app.schemas import DocumentType
from app.scoring import assess


def run(docs, bureau=None):
    return assess("SAMPLE", docs, bureau=bureau, sector="retail", as_of=AS_OF)


def test_clean_applicant_metrics():
    cash = run(applicant_a(), BUREAU_A).profile.cashflow
    assert cash.months_analyzed == 12
    assert cash.avg_monthly_credits.value == 200_000
    assert cash.existing_emi_monthly.value == 50_000
    assert cash.foir.value == 0.25
    assert cash.bounces_6m.value == 0
    assert cash.gst_turnover_12m.value == 196_000 * 12
    assert cash.gst_vs_bank_ratio.value == 0.98
    assert cash.foir.evidence[0].document_id == "sample-a-bank"


def test_clean_applicant_identity():
    identity = run(applicant_a(), BUREAU_A).profile.identity
    assert identity.business_vintage_months.value == 39  # 1 Jul 2023 -> 31 Oct 2026
    assert identity.constitution.value == "proprietorship"
    assert identity.gstin.value[2:12] == identity.pan.value
    assert identity.address.value.state == "Karnataka"


def test_clean_applicant_is_ready():
    profile = run(applicant_a(), BUREAU_A).profile
    assert profile.readiness.band == "ready"
    assert profile.readiness.score >= 90
    assert [f.id for f in profile.fix_it] == ["upload.itr_v"]


def test_messy_applicant_metrics():
    cash = run(applicant_b(), BUREAU_B).profile.cashflow
    assert cash.bounces_6m.value == 3
    assert 0.38 < cash.foir.value < 0.45
    assert cash.gst_turnover_12m.value == 92_000 * 12  # 5 months, annualised


def test_tampering_caps_readiness():
    profile = run(applicant_b(), BUREAU_B).profile
    assert profile.readiness.score <= 49
    assert profile.readiness.band == "not_ready"
    high = [f.title for f in profile.fix_it if f.priority == "high"]
    assert high == ["Upload the original bank statement downloaded from net banking", "Upload GSTR-3B for Jul 2026"]


def test_missing_bureau_and_documents_show_in_fix_it():
    docs = [d for d in applicant_a() if d.document_type != DocumentType.BANK_STATEMENT]
    profile = run(docs).profile
    ids = [f.id for f in profile.fix_it]
    assert ids[0] == "upload.bank_statement"
    assert "add.bureau" in ids
    assert profile.cashflow.foir is None  # not guessed without a statement
    assert profile.readiness.band != "ready"


def test_backwards_statement_period_fails_a_check_instead_of_crashing():
    docs = applicant_a()
    bank = next(d for d in docs if d.document_type == DocumentType.BANK_STATEMENT)
    flipped = bank.model_copy(update={"data": bank.data.model_copy(
        update={"period_from": bank.data.period_to, "period_to": bank.data.period_from})})
    docs = [flipped if d is bank else d for d in docs]

    result = run(docs, BUREAU_A)

    checked = next(d for d in result.documents if d.document_type == DocumentType.BANK_STATEMENT)
    period = next(c for c in checked.checks if c.id == "bank.period")
    assert period.status == "fail" and "backwards" in period.message
    # Metrics fall back to the transactions, so they match the correctly-dated statement.
    clean = run(applicant_a(), BUREAU_A).profile.cashflow
    cash = result.profile.cashflow
    assert cash.months_analyzed == clean.months_analyzed == 12
    assert cash.foir.value == clean.foir.value


def test_profile_builds_from_a_single_document():
    pan_only = [d for d in applicant_a() if d.document_type == DocumentType.PAN_CARD]
    profile = run(pan_only).profile
    assert profile.identity.pan.value == "ABCPK1234F"
    assert profile.identity.gstin is None
    assert len([f for f in profile.fix_it if f.action == "upload" and f.priority == "high"]) == 5
