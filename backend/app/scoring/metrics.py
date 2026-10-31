"""Cash-flow metrics and identity, computed from validated documents. Every value links to its evidence.

Definitions (keep in sync with what lenders expect):
- average monthly balance: mean of daily end-of-day balances over the statement period
- average monthly credits: business credits per month (bounce reversals excluded)
- bounces_6m: bounce entries in the last 6 months of the statement
- existing EMI: average EMI debits over the last 3 statement months
- FOIR: existing EMI / average monthly credits
- GST turnover (12m): last 12 months of GSTR-3B outward taxable value, annualised if fewer
- GST vs bank: GST turnover / bank credits over the months both cover
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app.schemas.common import Address, Constitution, DocumentType, EvidenceRef, MsmeCategory, Sourced
from app.schemas.profile import CashflowMetrics, Identity
from app.validation.cross import DocumentSet, bank_credits_by_month
from app.validation.months import add_months, month_key, month_range, months_between


def _ev(env, field: str) -> list[EvidenceRef]:
    return [EvidenceRef(document_id=env.document_id, field=field)]


def _v(extracted):
    return extracted.value if extracted is not None else None


def compute_metrics(docs: DocumentSet) -> CashflowMetrics:
    bank_env = docs.get(DocumentType.BANK_STATEMENT)
    gst = docs.gst_months()
    metrics: dict = {"months_analyzed": 0}

    if bank_env and bank_env.data.transactions:
        bank = bank_env.data
        txns = sorted(bank.transactions, key=lambda t: t.date)
        start = _v(bank.period_from) or txns[0].date
        end = _v(bank.period_to) or txns[-1].date
        if end < start:  # misread header dates (validation fails the document); the rows are the better guide
            start, end = txns[0].date, txns[-1].date
        months = month_range(month_key(start), month_key(end))
        ev = _ev(bank_env, "data.transactions")

        # Daily end-of-day balance, carried forward on days without transactions. Only printed balances count:
        # with fewer than half the rows printing one, an average would be a guess, so it is left out.
        printed = [t for t in txns if t.balance is not None]
        eod: dict[date, float] = {t.date: t.balance for t in printed}
        opening = _v(bank.opening_balance)
        balance = opening if opening is not None else (printed[0].balance if printed else None)
        daily: list[float] = []
        day = start
        while day <= end and len(printed) * 2 >= len(txns):
            balance = eod.get(day, balance)
            if balance is not None:
                daily.append(balance)
            day += timedelta(days=1)

        credits = bank_credits_by_month(docs)
        avg_credits = sum(credits.values()) / len(months)

        window_start = add_months(end, -6)
        bounces = sum(1 for t in txns if "bounce" in t.tags and t.date > window_start)

        emi_months = months[-3:]
        emi_by_month: dict[str, float] = defaultdict(float)
        for t in txns:
            if "emi" in t.tags:
                emi_by_month[month_key(t.date)] += t.debit
        emi = sum(emi_by_month[m] for m in emi_months) / len(emi_months)

        if daily:
            metrics["avg_monthly_balance"] = Sourced[float](value=round(sum(daily) / len(daily), 2), evidence=ev)
        metrics.update(
            months_analyzed=len(months),
            avg_monthly_credits=Sourced[float](value=round(avg_credits, 2), evidence=ev),
            bounces_6m=Sourced[int](value=bounces, evidence=ev),
            existing_emi_monthly=Sourced[float](value=round(emi, 2), evidence=ev),
        )
        if avg_credits > 0:
            metrics["foir"] = Sourced[float](value=round(emi / avg_credits, 3), evidence=ev)

    if gst:
        periods = sorted(gst)[-12:]
        total = sum(gst[p][0] for p in periods)
        gst_ev = [EvidenceRef(document_id=doc_id, field="data.months") for doc_id in dict.fromkeys(gst[p][1] for p in periods)]
        metrics["gst_turnover_12m"] = Sourced[float](value=round(total * 12 / len(periods), 2), evidence=gst_ev)

        if bank_env:
            credits = bank_credits_by_month(docs)
            common = [p for p in periods if p in credits]
            bank_total = sum(credits[p] for p in common)
            if common and bank_total:
                ratio = sum(gst[p][0] for p in common) / bank_total
                metrics["gst_vs_bank_ratio"] = Sourced[float](
                    value=round(ratio, 3), evidence=gst_ev + _ev(bank_env, "data.transactions")
                )

    return CashflowMetrics(**metrics)


def build_identity(docs: DocumentSet, as_of: date, sector: str | None = None) -> Identity:
    pan_env = docs.get(DocumentType.PAN_CARD)
    gst_env = docs.get(DocumentType.GST_REGISTRATION)
    udyam_env = docs.get(DocumentType.UDYAM)
    fields: dict = {"sector": sector}

    if pan_env:
        pan = pan_env.data
        if _v(pan.pan_number):
            fields["pan"] = Sourced[str](value=_v(pan.pan_number).upper(), evidence=_ev(pan_env, "data.pan_number"))
        if _v(pan.dob):
            fields["promoter_dob"] = Sourced[date](value=_v(pan.dob), evidence=_ev(pan_env, "data.dob"))
        if _v(pan.name):
            fields["legal_name"] = Sourced[str](value=_v(pan.name), evidence=_ev(pan_env, "data.name"))
        if fields.get("pan") and fields["pan"].value[3:4] == "P":
            # An individual's PAN on a business file means a proprietorship, until GST says otherwise.
            fields["constitution"] = Sourced[Constitution](value=Constitution.PROPRIETORSHIP, evidence=_ev(pan_env, "data.pan_number"))

    if gst_env:
        g = gst_env.data
        for target, attr in (("legal_name", "legal_name"), ("trade_name", "trade_name"), ("gstin", "gstin")):
            if (value := _v(getattr(g, attr))) is not None:
                fields[target] = Sourced[str](value=value, evidence=_ev(gst_env, f"data.{attr}"))
        if _v(g.constitution) is not None:
            fields["constitution"] = Sourced[Constitution](value=_v(g.constitution), evidence=_ev(gst_env, "data.constitution"))
        if _v(g.principal_address) is not None:
            fields["address"] = Sourced[Address](value=_v(g.principal_address), evidence=_ev(gst_env, "data.principal_address"))

    started: tuple[date, list[EvidenceRef]] | None = None
    if udyam_env:
        u = udyam_env.data
        if _v(u.udyam_number):
            fields["udyam_number"] = Sourced[str](value=_v(u.udyam_number), evidence=_ev(udyam_env, "data.udyam_number"))
        if _v(u.enterprise_type):
            fields["msme_category"] = Sourced[MsmeCategory](value=_v(u.enterprise_type), evidence=_ev(udyam_env, "data.enterprise_type"))
        if _v(u.date_of_incorporation):
            started = (_v(u.date_of_incorporation), _ev(udyam_env, "data.date_of_incorporation"))
        if "address" not in fields and _v(u.address) is not None:
            fields["address"] = Sourced[Address](value=_v(u.address), evidence=_ev(udyam_env, "data.address"))
    if started is None and gst_env and _v(gst_env.data.registration_date):
        started = (_v(gst_env.data.registration_date), _ev(gst_env, "data.registration_date"))

    if started:
        fields["date_of_incorporation"] = Sourced[date](value=started[0], evidence=started[1])
        fields["business_vintage_months"] = Sourced[int](value=max(0, months_between(started[0], as_of)), evidence=started[1])

    return Identity(**fields)
