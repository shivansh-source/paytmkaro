"""Feature extraction: SmeProfile + validated DocumentEnvelopes -> one scalar per parameter, with evidence.

Each function takes a `Context` and returns either a `Feature` (value, plain display text, evidence) or
`Unavailable` (why not, and exactly what it waits for). They are pure: no clock (the date comes from
`Context.as_of`), no randomness, no narration text and no names, addresses or identifiers in anything
they return. Values are numbers or short category tokens only; see fieldlock.py.

Metrics that SmeProfile already computes (bounces, FOIR, average balance, GST turnover ...) are READ from
it, never redefined here (definitions: app/scoring/metrics.py). New metrics defined in this file:
- liquidity cushion = average monthly balance / average monthly credits
- revenue trend = mean credits of the last 3 months / mean credits of the earlier months (>= 6 months)
- credit stability = coefficient of variation (stdev / mean) of monthly credits
- low-balance days = share of days whose end-of-day balance is below one month of existing EMI
  (below 10% of average monthly credits when there is no EMI)
- cash credit share = value of credits tagged "cash" / value of all business credits
- GST filing timeliness = share of GSTR-3B months filed on or before the due date
- GST turnover trend = same shape as revenue trend, on GSTR-3B outward value (>= 4 months)
- low-confidence field share = extracted fields needing review / all extracted fields
- ITR income margin = ITR-V gross total income / GST turnover (12m)
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.recommendation.rules import inr
from app.schemas.common import UDYAM_RE, Check, CheckStatus, CrossCheck, DocumentType, EvidenceRef, Extracted
from app.schemas.documents import DocumentEnvelope
from app.schemas.profile import SmeProfile
from app.validation.cross import DocumentSet, bank_credits_by_month
from app.validation.months import month_key, month_range, months_between

Value = float | int | str | bool


@dataclass(frozen=True)
class Feature:
    value: Value
    display: str  # plain-language statement of the value, e.g. "3 bounced debits in the last 6 months"
    evidence: tuple[EvidenceRef, ...] = ()
    low_confidence: str | None = None  # set when the source itself is unverified (e.g. mock bureau score)
    terse: bool = False  # display already says everything; do not append the band label to the reason


@dataclass(frozen=True)
class Unavailable:
    reason: str
    waits_for: str


FeatureFn = Callable[["Context"], "Feature | Unavailable"]


@dataclass
class Context:
    profile: SmeProfile
    docs: DocumentSet
    as_of: date
    by_id: dict[str, DocumentEnvelope] = field(default_factory=dict)

    @classmethod
    def build(cls, profile: SmeProfile, documents: list[DocumentEnvelope], as_of: date) -> Context:
        return cls(profile, DocumentSet.from_envelopes(documents), as_of, {e.document_id: e for e in documents})

    def check(self, check_id: CrossCheck) -> Check | None:
        return next((c for c in self.profile.cross_checks if c.id == check_id), None)


# ---- helpers -------------------------------------------------------------------------------------


def _ref(env: DocumentEnvelope, path: str) -> EvidenceRef:
    return EvidenceRef(document_id=env.document_id, field=path)


def _dedupe(refs) -> tuple[EvidenceRef, ...]:
    """EvidenceRef is not hashable; keep the first of each (document, field)."""
    seen: dict[tuple[str, str], EvidenceRef] = {}
    for ref in refs:
        seen.setdefault((ref.document_id, ref.field), ref)
    return tuple(seen.values())


def _need(doc: str, path: str) -> Unavailable:
    return Unavailable(f"Waiting for the {doc.replace('_', ' ')} document.", f"document {doc}: {path}")


def _bank_refs(env: DocumentEnvelope) -> tuple[EvidenceRef, ...]:
    return tuple(_ref(env, f"data.{f}") for f in ("transactions", "period_from", "period_to", "opening_balance"))


def _with_bank_headers(ctx: Context, evidence: list[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    """Bank-derived metrics also rest on the statement's period and opening balance."""
    out = list(evidence)
    for ref in evidence:
        env = ctx.by_id.get(ref.document_id)
        if env is not None and env.document_type == DocumentType.BANK_STATEMENT and ref.field == "data.transactions":
            out += [r for r in _bank_refs(env) if r not in out]
    return tuple(out)


def _daily_balances(env: DocumentEnvelope) -> list[float]:
    """End-of-day balance for each day of the statement, carried forward over quiet days."""
    bank = env.data
    txns = sorted(bank.transactions, key=lambda t: t.date)
    start = bank.period_from.value or txns[0].date
    end = bank.period_to.value or txns[-1].date
    eod = {t.date: t.balance for t in txns}
    balance = bank.opening_balance.value if bank.opening_balance.value is not None else txns[0].balance
    out, day = [], start
    while day <= end:
        balance = eod.get(day, balance)
        out.append(balance)
        day += timedelta(days=1)
    return out


def _monthly_series(docs: DocumentSet) -> list[float]:
    """Business credits per statement month (bounce reversals excluded), zero-filled."""
    credits = bank_credits_by_month(docs)
    if not credits:
        return []
    return [credits.get(m, 0.0) for m in month_range(min(credits), max(credits))]


def _trend_ratio(series: list[float], recent: int = 3) -> float | None:
    earlier = series[:-recent]
    if not earlier or statistics.fmean(earlier) <= 0:
        return None
    return statistics.fmean(series[-recent:]) / statistics.fmean(earlier)


def _bank_env(ctx: Context) -> DocumentEnvelope | None:
    env = ctx.docs.get(DocumentType.BANK_STATEMENT)
    return env if env is not None and env.data.transactions else None


# ---- factories for the common shapes -------------------------------------------------------------


def metric(attr: str, fmt: Callable[[float], str], waits: str) -> FeatureFn:
    """Read a CashflowMetrics value (already computed and source-linked by app.scoring)."""

    def feature(ctx: Context) -> Feature | Unavailable:
        sourced = getattr(ctx.profile.cashflow, attr)
        if sourced is None:
            return Unavailable(f"The cash-flow metric '{attr}' could not be computed from the documents so far.", f"SmeProfile.cashflow.{attr} (needs {waits})")
        return Feature(sourced.value, fmt(sourced.value), _with_bank_headers(ctx, list(sourced.evidence)))

    return feature


def identity_value(attr: str, fmt: Callable[[object], tuple[Value, str]], waits: str) -> FeatureFn:
    def feature(ctx: Context) -> Feature | Unavailable:
        sourced = getattr(ctx.profile.identity, attr)
        if sourced is None:
            return Unavailable(f"'{attr}' is not available yet.", f"SmeProfile.identity.{attr} (needs {waits})")
        value, display = fmt(sourced.value)
        return Feature(value, display, tuple(sourced.evidence))

    return feature


def cross_check_status(check_id: CrossCheck, display: dict[CheckStatus, str], quote: bool = False) -> FeatureFn:
    """Use only the status of a cross-document check. Its message is quoted only for checks whose text
    carries no personal data (`quote=True`: balance math and statement gaps)."""

    def feature(ctx: Context) -> Feature | Unavailable:
        check = ctx.check(check_id)
        if check is None:
            return Unavailable("The documents needed for this cross-check have not all been provided.", f"SmeProfile.cross_checks[{check_id.value}]")
        text = display[check.status]
        if quote and check.status != CheckStatus.PASS:
            text = f"{text}: {check.message}"
        evidence = []
        for i, doc_id in enumerate(check.document_ids):
            path = check.fields[i] if len(check.fields) == len(check.document_ids) else (check.fields[0] if len(check.fields) == 1 else "data")
            evidence.append(EvidenceRef(document_id=doc_id, field=path))
        return Feature(check.status.value, text, tuple(evidence), terse=True)

    return feature


# ---- company profile -----------------------------------------------------------------------------

vintage_months = identity_value("business_vintage_months", lambda v: (v, f"{v} months in business"), "Udyam or GST registration")
constitution = identity_value("constitution", lambda v: (v.value, f"Constitution is {v.value.replace('_', ' ')}"), "GST registration or PAN")
msme_category = identity_value("msme_category", lambda v: (v.value, f"Udyam category is {v.value}"), "Udyam registration")


def udyam_registration(ctx: Context) -> Feature | Unavailable:
    env = ctx.docs.get(DocumentType.UDYAM)
    if env is None or env.data.udyam_number.value is None:
        return _need("udyam", "data.udyam_number")
    ok = bool(UDYAM_RE.match(env.data.udyam_number.value.upper()))
    return Feature("registered" if ok else "invalid_format", "Udyam registration provided" if ok else "Udyam registration provided but malformed",
                   (_ref(env, "data.udyam_number"),))


def gst_registration_tenure(ctx: Context) -> Feature | Unavailable:
    env = ctx.docs.get(DocumentType.GST_REGISTRATION)
    if env is None or env.data.registration_date.value is None:
        return _need("gst_registration", "data.registration_date")
    months = max(0, months_between(env.data.registration_date.value, ctx.as_of))
    return Feature(months, f"GST-registered for {months} months", (_ref(env, "data.registration_date"),))


# ---- promoter profile ----------------------------------------------------------------------------


def itr_filed(ctx: Context) -> Feature | Unavailable:
    env = ctx.docs.get(DocumentType.ITR_V)
    if env is None or not env.data.assessment_year.value:
        return _need("itr_v", "data.assessment_year")
    try:
        ay_start = int(env.data.assessment_year.value[:4])
    except ValueError:
        return Unavailable("The assessment year on the ITR-V could not be read.", "document itr_v: data.assessment_year (confirm the value)")
    fy_start = ctx.as_of.year if ctx.as_of.month >= 4 else ctx.as_of.year - 1
    lag = max(0, fy_start - ay_start)  # 0: the return for the year just ended (AY fy_start-fy_start+1)
    return Feature(lag, f"Latest ITR-V is {lag} year(s) behind the latest return due", (_ref(env, "data.assessment_year"),))


def itr_income_margin(ctx: Context) -> Feature | Unavailable:
    env, turnover = ctx.docs.get(DocumentType.ITR_V), ctx.profile.cashflow.gst_turnover_12m
    if env is None or env.data.gross_total_income.value is None:
        return _need("itr_v", "data.gross_total_income")
    if turnover is None or turnover.value <= 0:
        return Unavailable("GST turnover is needed to compare with the income in the ITR-V.", "SmeProfile.cashflow.gst_turnover_12m (needs gstr3b)")
    ratio = round(env.data.gross_total_income.value / turnover.value, 4)
    return Feature(ratio, f"ITR-V income is {ratio:.1%} of annual GST turnover ({inr(env.data.gross_total_income.value)} against {inr(turnover.value)})",
                   (_ref(env, "data.gross_total_income"), *turnover.evidence))


# ---- banking conduct -----------------------------------------------------------------------------

bounces_6m = metric("bounces_6m", lambda v: f"{int(v)} bounced debit(s) in the last 6 statement months", "bank_statement")
foir = metric("foir", lambda v: f"Existing EMIs are {v:.0%} of average monthly credits (FOIR)", "bank_statement with transactions")
gst_bank_consistency = metric("gst_vs_bank_ratio", lambda v: f"GST turnover is {v:.0%} of bank credits over the same months", "bank_statement and gstr3b")
turnover_scale = metric("gst_turnover_12m", lambda v: f"Annualised GST turnover {inr(v)}", "gstr3b")


def statement_months(ctx: Context) -> Feature | Unavailable:
    env = _bank_env(ctx)
    months = ctx.profile.cashflow.months_analyzed
    if env is None or months == 0:
        return _need("bank_statement", "data.transactions")
    return Feature(months, f"{months} months of bank statements analysed", _bank_refs(env))


def liquidity_cushion(ctx: Context) -> Feature | Unavailable:
    amb, credits = ctx.profile.cashflow.avg_monthly_balance, ctx.profile.cashflow.avg_monthly_credits
    if amb is None or credits is None or credits.value <= 0:
        return _need("bank_statement", "data.transactions")
    ratio = round(amb.value / credits.value, 3)
    return Feature(ratio, f"Average balance is {ratio:.0%} of a month's credits", _with_bank_headers(ctx, list(amb.evidence)))


def revenue_trend(ctx: Context) -> Feature | Unavailable:
    env = _bank_env(ctx)
    series = _monthly_series(ctx.docs) if env else []
    if env is None or len(series) < 6:
        return Unavailable("At least 6 months of bank statements are needed to see a trend.", "document bank_statement: 6 or more months of data.transactions")
    ratio = _trend_ratio(series)
    if ratio is None:
        return Unavailable("Earlier months have no credits to compare with.", "document bank_statement: credits in earlier months")
    ratio = round(ratio, 3)
    return Feature(ratio, f"Last 3 months' bank inflow is {ratio:.0%} of the earlier monthly average", _bank_refs(env))


def credit_stability(ctx: Context) -> Feature | Unavailable:
    env = _bank_env(ctx)
    series = _monthly_series(ctx.docs) if env else []
    if env is None or len(series) < 3 or statistics.fmean(series) <= 0:
        return Unavailable("At least 3 months of credits are needed.", "document bank_statement: 3 or more months of data.transactions")
    cv = round(statistics.pstdev(series) / statistics.fmean(series), 3)
    return Feature(cv, f"Monthly bank inflow varies by {cv:.0%} around its average", _bank_refs(env))


def low_balance_days(ctx: Context) -> Feature | Unavailable:
    env, cash = _bank_env(ctx), ctx.profile.cashflow
    if env is None or cash.avg_monthly_credits is None:
        return _need("bank_statement", "data.transactions")
    emi = cash.existing_emi_monthly.value if cash.existing_emi_monthly else 0.0
    floor = emi if emi > 0 else 0.1 * cash.avg_monthly_credits.value
    days = _daily_balances(env)
    share = round(sum(1 for b in days if b < floor) / len(days), 3)
    what = "one month of existing EMI" if emi > 0 else "10% of a month's credits"
    return Feature(share, f"Balance was below {what} on {share:.0%} of days", _bank_refs(env))


def cash_credit_share(ctx: Context) -> Feature | Unavailable:
    env = _bank_env(ctx)
    if env is None:
        return _need("bank_statement", "data.transactions")
    credits = [t for t in env.data.transactions if t.credit and "bounce" not in t.tags]
    total = sum(t.credit for t in credits)
    if total <= 0:
        return Unavailable("The statement shows no business credits.", "document bank_statement: credit rows")
    share = round(sum(t.credit for t in credits if "cash" in t.tags) / total, 3)
    return Feature(share, f"{share:.0%} of bank inflow is cash deposits", _bank_refs(env))


def gst_filing_timeliness(ctx: Context) -> Feature | Unavailable:
    dated = [(m, env) for env in ctx.docs.gstr3b for m in env.data.months if m.filing_date and m.due_date]
    if len(dated) < 3:
        return Unavailable("Filing and due dates are needed for at least 3 GSTR-3B months.", "document gstr3b: months[].filing_date and months[].due_date")
    on_time = sum(1 for m, _ in dated if m.filing_date <= m.due_date)
    share = round(on_time / len(dated), 3)
    refs = _dedupe(_ref(env, "data.months") for _, env in dated)
    return Feature(share, f"{on_time} of {len(dated)} GSTR-3B returns filed on or before the due date", refs)


def gst_turnover_trend(ctx: Context) -> Feature | Unavailable:
    months = ctx.docs.gst_months()
    if len(months) < 4:
        return Unavailable("At least 4 months of GSTR-3B are needed to see a trend.", "document gstr3b: 4 or more months")
    periods = sorted(months)
    ratio = _trend_ratio([months[p][0] for p in periods])
    if ratio is None:
        return Unavailable("Earlier months have no turnover to compare with.", "document gstr3b: turnover in earlier months")
    ratio = round(ratio, 3)
    refs = _dedupe(EvidenceRef(document_id=months[p][1], field="data.months") for p in periods)
    return Feature(ratio, f"Last 3 months' GST turnover is {ratio:.0%} of the earlier monthly average", refs)


# ---- risk, bureau --------------------------------------------------------------------------------


def consumer_score(ctx: Context) -> Feature | Unavailable:
    bureau = ctx.profile.bureau
    if bureau is None:
        return Unavailable("No bureau score has been provided.", "SmeProfile.bureau (consumer bureau score, 300-900)")
    note = None if bureau.source == "bureau" else f"bureau score is {bureau.source.replace('_', ' ')}, not pulled from a bureau"
    return Feature(bureau.value, f"Bureau score {bureau.value} ({bureau.source.replace('_', ' ')})", (), note)


# ---- data integrity ------------------------------------------------------------------------------


def low_confidence_fields(ctx: Context) -> Feature | Unavailable:
    total = flagged = 0
    refs: list[EvidenceRef] = []
    for env in ctx.by_id.values():
        if env.data is None or env.status == "failed":
            continue
        refs.append(_ref(env, "data"))
        for name in type(env.data).model_fields:
            item = getattr(env.data, name)
            if isinstance(item, Extracted):
                total += 1
                flagged += int(item.needs_review)
    if total == 0:
        return Unavailable("No extracted fields to assess.", "any extracted document")
    share = round(flagged / total, 3)
    return Feature(share, f"{flagged} of {total} extracted fields need confirmation", tuple(refs))


def _statuses(ok: str, warn: str, fail: str) -> dict[CheckStatus, str]:
    return {CheckStatus.PASS: ok, CheckStatus.WARN: warn, CheckStatus.FAIL: fail}


balance_math = cross_check_status(
    CrossCheck.BALANCE_MATH, _statuses("Every bank statement row adds up", "Bank statement balance check needs review", "Bank statement balance check failed"), quote=True)
statement_gaps = cross_check_status(
    CrossCheck.STATEMENT_GAPS, _statuses("No missing months", "Supporting statements have a minor gap", "Supporting statements are missing a month"), quote=True)
tax_registration_link = cross_check_status(
    CrossCheck.PAN_IN_GSTIN, _statuses("PAN inside the GSTIN matches the PAN card", "PAN and GSTIN link needs review", "PAN inside the GSTIN does not match the PAN card"))
name_agreement = cross_check_status(
    CrossCheck.NAME_MATCH, _statuses("Name agrees across documents", "Name is a near-match across documents", "Name differs across documents"))
premises_agreement = cross_check_status(
    CrossCheck.ADDRESS_MATCH, _statuses("Address agrees across documents", "Address differs slightly across documents", "Address differs across documents"))
kyc_record_match = cross_check_status(
    CrossCheck.DOB_MATCH, _statuses("PAN and Aadhaar records agree", "PAN and Aadhaar could not be fully compared", "PAN and Aadhaar records disagree"))
