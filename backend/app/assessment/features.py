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
- bureau details (CMR rank, worst DPD, enquiries, adverse flags): read from SmeProfile.bureau, else from the
  newest uploaded bureau report; unverified unless the score was pulled from a bureau
- revenue growth = revenue / prior-year revenue - 1; net margin = profit after tax / revenue; leverage =
  (long + short term borrowings) / net worth; DSCR = (PAT + depreciation + interest) / (principal + interest).
  Always recomputed from the components, in rupees; the latest financial year is used, never a mix of years
- overdraft utilisation = average overdrawn amount (negative end-of-day balance) / sanctioned limit, only when
  the statement does go negative (otherwise it cannot be tied to the overdraft account)
- settlement ratio = settlement net / bank business credits over the months both cover (>= 2); a consistency
  check, not a measure of how digital the business is
"""

from __future__ import annotations

import re
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
    """End-of-day balance for each day of the statement, carried forward over quiet days.

    Uses printed balances only; empty when fewer than half the rows print one (a rebuild would be a guess)."""
    bank = env.data
    txns = sorted(bank.transactions, key=lambda t: t.date)
    printed = [t for t in txns if t.balance is not None]
    if not printed or len(printed) * 2 < len(txns):
        return []
    start = bank.period_from.value or txns[0].date
    end = bank.period_to.value or txns[-1].date
    eod = {t.date: t.balance for t in printed}
    opening = bank.opening_balance.value if bank.opening_balance is not None else None
    balance = opening if opening is not None else printed[0].balance
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
    if not days:
        return Unavailable("Most rows of the statement don't print a running balance, so daily balances can't be rebuilt.",
                           "document bank_statement: a running balance on most rows")
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


# ---- documents added in schema 1.1 / 1.2: bureau report, financial statements, sanction letter, settlement ----

BUREAU_STALE_DAYS = 90  # placeholder: an older report is flagged on the card, not discarded


def _usable(ctx: Context, doc_type: DocumentType) -> list[DocumentEnvelope]:
    """Every usable envelope of one type, oldest upload first. DocumentSet keeps only the latest per type."""
    found = [e for e in ctx.by_id.values() if e.document_type == doc_type and e.data is not None and e.status != "failed"]
    return sorted(found, key=lambda e: e.uploaded_at)


def _field_value(env: DocumentEnvelope, name: str):
    item = getattr(env.data, name, None)
    return item.value if isinstance(item, Extracted) else None


def _bureau_detail(ctx: Context, name: str):
    """(value, evidence, source, report date) of one bureau field, or None.

    The profile's BureauScore wins (a score pulled from a bureau is the authority). Otherwise the newest
    uploaded report that states the field: a commercial-only report has no consumer score, so it never
    reaches SmeProfile.bureau and has to be read directly."""
    bureau = ctx.profile.bureau
    value = getattr(bureau, name, None) if bureau is not None else None
    if value is not None:
        return value, (), bureau.source, bureau.as_of
    reports = sorted(_usable(ctx, DocumentType.BUREAU_REPORT), key=lambda e: (_field_value(e, "report_date") or date.min, e.uploaded_at))
    for env in reversed(reports):
        value = _field_value(env, name)
        if value is not None:
            return value, (_ref(env, f"data.{name}"),), "self_declared", _field_value(env, "report_date")
    return None


def _bureau_note(ctx: Context, source: str, as_of: date | None) -> str | None:
    notes = []
    if source != "bureau":
        notes.append(f"bureau details are {source.replace('_', ' ')}, not pulled from a bureau")
    if as_of is not None and (ctx.as_of - as_of).days > BUREAU_STALE_DAYS:
        notes.append(f"the report is {(ctx.as_of - as_of).days} days old")
    return "; ".join(notes) or None


def _bureau_waits(name: str) -> str:
    return f"bureau_report.{name} (uploaded report) or SmeProfile.bureau.{name}"


def cmr_rank(ctx: Context) -> Feature | Unavailable:
    got = _bureau_detail(ctx, "cmr_rank")
    if got is None or not 1 <= got[0] <= 10:
        return Unavailable("No CIBIL MSME Rank (1 to 10) has been provided.", _bureau_waits("cmr_rank"))
    rank, evidence, source, as_of = got
    return Feature(rank, f"CIBIL MSME Rank {rank} (1 is best)", evidence, _bureau_note(ctx, source, as_of))


def worst_dpd_24m(ctx: Context) -> Feature | Unavailable:
    got = _bureau_detail(ctx, "max_dpd_24m")
    if got is None or got[0] < 0:
        return Unavailable("The report does not state the worst days past due.", _bureau_waits("max_dpd_24m"))
    days, evidence, source, as_of = got
    return Feature(days, f"Worst delay in the last 24 months was {days} days past due", evidence, _bureau_note(ctx, source, as_of))


def enquiries_90d(ctx: Context) -> Feature | Unavailable:
    got = _bureau_detail(ctx, "enquiries_90d")
    if got is None or got[0] < 0:
        return Unavailable("The report does not state the number of recent credit enquiries.", _bureau_waits("enquiries_90d"))
    count, evidence, source, as_of = got
    return Feature(count, f"{count} credit enquiries in the last 90 days", evidence, _bureau_note(ctx, source, as_of))


def adverse_flags(ctx: Context) -> Feature | Unavailable:
    """Either flag set is the worst band. 'Clean' needs both flags stated and false: a missing flag is not a clean one."""
    known = [d for d in (_bureau_detail(ctx, n) for n in ("written_off_or_settled", "suit_filed_or_wilful_default")) if d is not None]
    flagged = sum(1 for d in known if d[0] is True)
    if flagged == 0 and len(known) < 2:
        return Unavailable("The report does not state both the write-off / settlement and the suit-filed / wilful-default flags.",
                           "bureau_report.written_off_or_settled and suit_filed_or_wilful_default")
    evidence = _dedupe(ref for d in known for ref in d[1])
    text = "No write-off, settlement, suit or wilful-default flag on the report" if flagged == 0 else "A write-off, settlement, suit or wilful-default flag is reported"
    return Feature(flagged, text, evidence, _bureau_note(ctx, known[0][2], known[0][3]))


# ---- financial statements ----


def _statement(ctx: Context) -> DocumentEnvelope | None:
    """The latest financial year; years are never mixed."""
    return max(_usable(ctx, DocumentType.FINANCIAL_STATEMENTS), key=lambda e: (str(_field_value(e, "financial_year") or ""), e.uploaded_at), default=None)


def _statement_note(env: DocumentEnvelope) -> str | None:
    return None if _field_value(env, "audit_status") in ("audited", "ca_certified") else "the financial figures are provisional or their audit status is unknown"


def _statement_refs(env: DocumentEnvelope, *names: str) -> tuple[EvidenceRef, ...]:
    return tuple(_ref(env, f"data.{n}") for n in names)


def revenue_growth(ctx: Context) -> Feature | Unavailable:
    env = _statement(ctx)
    if env is None:
        return _need("financial_statements", "data.revenue, data.prior_revenue")
    revenue, prior = _field_value(env, "revenue"), _field_value(env, "prior_revenue")
    if revenue is None or prior is None:
        return Unavailable("Revenue for both years is needed.", "document financial_statements (revenue, prior_revenue)")
    if prior <= 0:
        return Unavailable("The previous year's revenue is zero or negative, so growth has no meaning.", "document financial_statements (prior_revenue > 0)")
    growth = round(revenue / prior - 1, 3)
    return Feature(growth, f"Revenue {'grew' if growth >= 0 else 'fell'} {abs(growth):.0%} against the previous year",
                   _statement_refs(env, "revenue", "prior_revenue"), _statement_note(env))


def net_margin(ctx: Context) -> Feature | Unavailable:
    env = _statement(ctx)
    if env is None:
        return _need("financial_statements", "data.profit_after_tax, data.revenue")
    profit, revenue = _field_value(env, "profit_after_tax"), _field_value(env, "revenue")
    if profit is None or revenue is None or revenue <= 0:
        return Unavailable("Profit after tax and a positive revenue are needed.", "document financial_statements (profit_after_tax, revenue > 0)")
    margin = round(profit / revenue, 3)
    return Feature(margin, f"Net profit margin of {margin:.1%}", _statement_refs(env, "profit_after_tax", "revenue"), _statement_note(env))


def leverage(ctx: Context) -> Feature | Unavailable:
    env = _statement(ctx)
    if env is None:
        return _need("financial_statements", "data.long_term_borrowings, short_term_borrowings, net_worth")
    long_term, short_term, worth = (_field_value(env, n) for n in ("long_term_borrowings", "short_term_borrowings", "net_worth"))
    if None not in (long_term, short_term, worth):
        refs = _statement_refs(env, "long_term_borrowings", "short_term_borrowings", "net_worth")
        if worth <= 0:
            # A negative denominator would otherwise land in the best band.
            return Feature(99.0, "Net worth is zero or negative, so borrowings cannot be set against it", refs, _statement_note(env))
        ratio = round((long_term + short_term) / worth, 2)
        return Feature(ratio, f"Borrowings are {ratio:.1f} times net worth", refs, _statement_note(env))
    reported = _field_value(env, "debt_to_equity")
    if reported is None or not 0 <= reported < 50:
        return Unavailable("Both kinds of borrowing and net worth (or a debt-to-equity ratio) are needed.", "document financial_statements (long_term_borrowings, short_term_borrowings, net_worth)")
    return Feature(round(reported, 2), f"Debt to equity of {reported:.1f}, as reported", _statement_refs(env, "debt_to_equity"), _statement_note(env))


def dscr(ctx: Context) -> Feature | Unavailable:
    env = _statement(ctx)
    if env is None:
        return _need("financial_statements", "data.profit_after_tax, depreciation, interest_expense, principal_repayments")
    profit, depreciation, interest, principal = (_field_value(env, n) for n in ("profit_after_tax", "depreciation", "interest_expense", "principal_repayments"))
    if None not in (profit, depreciation, interest, principal):
        service = principal + interest
        if service <= 0:
            return Unavailable("The year shows no debt service (no principal or interest), so coverage is not defined.", "document financial_statements (principal_repayments, interest_expense)")
        ratio = round((profit + depreciation + interest) / service, 2)
        return Feature(ratio, f"Cash profit covers debt service {ratio:.2f} times",
                       _statement_refs(env, "profit_after_tax", "depreciation", "interest_expense", "principal_repayments"), _statement_note(env))
    reported = _field_value(env, "dscr")
    if reported is None or not 0 <= reported < 50:
        return Unavailable("Profit, depreciation, interest and principal repayments (or a DSCR) are needed.", "document financial_statements (dscr or its components)")
    return Feature(round(reported, 2), f"Debt service coverage of {reported:.2f}, as reported", _statement_refs(env, "dscr"), _statement_note(env))


# ---- sanction letters ----


def _facility_kind(text: str | None) -> str:
    """Closed list only. The free text of a sanction letter can carry a business name, so it must never be echoed."""
    t = (text or "").lower()
    if "overdraft" in t or re.search(r"\bod\b", t):
        return "overdraft"
    if "cash credit" in t or "cash-credit" in t or re.search(r"\bcc\b", t):
        return "cash_credit"
    if "working capital" in t:
        return "working_capital"
    if "term" in t:
        return "term_loan"
    return "other"


def od_utilisation(ctx: Context) -> Feature | Unavailable:
    letters = [e for e in _usable(ctx, DocumentType.SANCTION_LETTER)
               if _facility_kind(_field_value(e, "facility_type")) in ("overdraft", "cash_credit") and (_field_value(e, "sanctioned_amount") or 0) > 0]
    if not letters:
        return Unavailable("No overdraft or cash-credit sanction letter with an amount has been provided.", "document sanction_letter (facility_type, sanctioned_amount)")
    letter = max(letters, key=lambda e: (_field_value(e, "sanction_date") or date.min, e.uploaded_at))
    env = _bank_env(ctx)
    if env is None:
        return _need("bank_statement", "data.transactions")
    if not any(t.balance is not None and t.balance < 0 for t in env.data.transactions):
        # Utilisation of 0% would read as a strength when the statement may simply be another account.
        return Unavailable("The statement never goes into overdraft, so it cannot be tied to the overdraft account.", "bank statement of the overdraft account (negative balances)")
    days = _daily_balances(env)
    if not days:
        return Unavailable("Most statement rows print no running balance, so daily balances can't be rebuilt.", "document bank_statement: a running balance on most rows")
    limit = _field_value(letter, "sanctioned_amount")
    ratio = round(statistics.fmean(max(0.0, -b) for b in days) / limit, 3)
    refs = (_ref(letter, "data.sanctioned_amount"), _ref(letter, "data.facility_type"), *_bank_refs(env))
    return Feature(ratio, f"The overdraft was used to {ratio:.0%} of its {inr(limit)} limit on average", refs)


def margin_facility(ctx: Context) -> Feature | Unavailable:
    known = [(e, _field_value(e, "fd_lien_or_margin")) for e in _usable(ctx, DocumentType.SANCTION_LETTER)]
    known = [(e, v) for e, v in known if v is not None]
    if not known:
        return Unavailable("No sanction letter states whether a facility is secured by a fixed-deposit lien or cash margin.", "document sanction_letter (fd_lien_or_margin)")
    margined = [e for e, v in known if v is True]
    if margined:
        return Feature("cash_margined", "A facility is secured by a fixed-deposit lien or full cash margin",
                       _dedupe(_ref(e, "data.fd_lien_or_margin") for e in margined))
    return Feature("not_margined", "No facility is fully cash-margined", _dedupe(_ref(e, "data.fd_lien_or_margin") for e, _ in known))


def facility_trend(ctx: Context) -> Feature | Unavailable:
    """Compare the two newest sanctions of the same facility type: all letters are read, not only the latest."""
    groups: dict[str, list[tuple[date, float, DocumentEnvelope]]] = {}
    for env in _usable(ctx, DocumentType.SANCTION_LETTER):
        when, amount = _field_value(env, "sanction_date"), _field_value(env, "sanctioned_amount")
        kind = _facility_kind(_field_value(env, "facility_type"))
        if kind != "other" and when is not None and amount is not None and amount > 0:  # unrecognised types can't be compared
            groups.setdefault(kind, []).append((when, amount, env))
    series = {kind: sorted(rows, key=lambda r: r[0]) for kind, rows in groups.items() if len(rows) >= 2}
    if not series:
        return Unavailable("Two sanction letters of the same facility type, with dates and amounts, are needed.", "documents sanction_letter for the last two renewals (sanctioned_amount, sanction_date)")
    kind = max(series, key=lambda k: series[k][-1][0])
    (_, before, old), (_, after, new) = series[kind][-2:]
    ratio = after / before
    token = "increased" if ratio > 1.02 else "decreased" if ratio < 0.98 else "same"
    verb = {"increased": "rose to", "decreased": "fell to", "same": "stayed at"}[token]
    refs = _dedupe([_ref(old, "data.sanctioned_amount"), _ref(new, "data.sanctioned_amount")])
    return Feature(token, f"The {kind.replace('_', ' ')} limit {verb} {inr(after)} from {inr(before)} at the last renewal", refs)


# ---- settlement report ----


def pg_settlements(ctx: Context) -> Feature | Unavailable:
    """Settlement net / bank business credits over the months both cover. A consistency check: a business that
    sells mostly in cash has a low ratio and that is fine; settlements ABOVE the bank inflow are what need explaining."""
    nets: dict[str, tuple[float, str]] = {}
    for env in _usable(ctx, DocumentType.SETTLEMENT_REPORT):
        for month in env.data.months:
            nets[month.month] = (month.net, env.document_id)  # later uploads win, as for GSTR-3B
    if not nets:
        return _need("settlement_report", "data.months")
    bank = _bank_env(ctx)
    if bank is None:
        return _need("bank_statement", "data.transactions")
    credits = bank_credits_by_month(ctx.docs)
    common = sorted(set(nets) & set(credits))
    total = sum(credits[m] for m in common)
    if len(common) < 2 or total <= 0:
        return Unavailable("At least 2 months must appear in both the settlement report and the bank statement.", "settlement_report and bank_statement covering the same 2 or more months")
    ratio = round(sum(nets[m][0] for m in common) / total, 3)
    refs = _dedupe([*(EvidenceRef(document_id=nets[m][1], field="data.months") for m in common), *_bank_refs(bank)])
    return Feature(ratio, f"Payment-aggregator settlements are {ratio:.0%} of bank inflow over {len(common)} months", refs)
