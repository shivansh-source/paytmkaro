"""From extracted documents to SMEProfile features, plus cross-document checks.

Every number here is computed in code from validated fields and rows; each
feature says which document and field it came from and whether it is an estimate.
Missing documents give None (reported as missing by the engine), never 0 or False.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel

from app.documents.extract.common import month_key, month_label, month_range, months_between, normalize_name, parse_date
from app.documents.models import DocumentType, ExtractionResult
from app.recommendation.models import SMEProfile
from app.recommendation.rules import inr

I = re.IGNORECASE

BOUNCE = re.compile(r"\bRTN\b|\bRETURN(?:ED)?\b|\bBOUNCE[D]?\b|INSUFF(?:ICIENT)?|\bCHQ\s*RET|\bDISHONOU?R(?:ED)?\b|\bUNPAID\b", I)
CHARGE = re.compile(r"\bCHG|\bCHRG|CHARGE|\bFEE\b|\bGST\b|PENAL", I)
EMI = re.compile(r"\bEMI\b|\bNACH\b|\bECS\b|\bACH\s*-?\s*D|\bLOAN\b|\bSI\s*-?\s*LOAN", I)
# Credits that are not business receipts: own-account moves, reversals, refunds, loan money, interest.
NON_REVENUE = re.compile(
    r"\bSELF\b|OWN\s*A/?C|\bREV(?:ERSAL)?\b|REFUND|\bRTN\b|RETURN|LOAN\s*DISB|DISBURS|\bSWEEP\b|\bFD\b|INT(?:EREST)?\.?\s*(?:PD|PAID|CREDIT)|CASH\s*BACK",
    I,
)
TURNOVER_TOLERANCE = 0.25  # bank credits vs GSTR-3B (taxable + tax) for the same months
NAME_PASS = 0.92
NAME_CONFIRM = 0.75


class FeatureValue(BaseModel):
    value: Any
    # "<document_type>.<field or table>", e.g. "gst_certificate.registration_date".
    source: str
    method: str
    estimate: bool = False


CheckOutcome = Literal["pass", "warn", "fail"]


class DocumentCheck(BaseModel):
    """Cross-document check, explained like the recommendation engine's CheckResult."""

    rule: str
    outcome: CheckOutcome
    message: str
    documents: list[str] = []


class ProfileFeatures(BaseModel):
    as_of: date
    features: dict[str, FeatureValue] = {}
    checks: list[DocumentCheck] = []
    warnings: list[str] = []

    def profile_fields(self) -> dict[str, Any]:
        """Only the SMEProfile fields, ready for SMEProfile(sme_id=..., requested_amount=..., **this)."""
        return {k: v.value for k, v in self.features.items() if k in SMEProfile.model_fields}


# ---------- helpers ----------


def _docs(results: list[ExtractionResult], kind: DocumentType) -> list[ExtractionResult]:
    return [r for r in results if r.document_type == kind and r.status != "failed"]


def _field(results: list[ExtractionResult], kind: DocumentType, name: str) -> Any:
    for r in _docs(results, kind):
        if name in r.fields:
            return r.fields[name].value
    return None


def _transactions(results: list[ExtractionResult]) -> list[dict[str, Any]]:
    rows = []
    for r in _docs(results, DocumentType.BANK_STATEMENT):
        rows.extend({**t, "_date": parse_date(t["date"])} for t in r.tables.get("transactions", []))
    # Same row in two overlapping statements counts once.
    unique = {(t["date"], t["narration"], t.get("debit"), t.get("credit"), t.get("balance")): t for t in rows}
    return sorted(unique.values(), key=lambda t: t["_date"])


def _statement_span(results: list[ExtractionResult], rows: list[dict[str, Any]]) -> tuple[date, date] | None:
    starts, ends = [], []
    for r in _docs(results, DocumentType.BANK_STATEMENT):
        if "period_from" in r.fields:
            starts.append(parse_date(r.fields["period_from"].value))
        if "period_to" in r.fields:
            ends.append(parse_date(r.fields["period_to"].value))
    if not starts and rows:
        starts = [rows[0]["_date"]]
    if not ends and rows:
        ends = [rows[-1]["_date"]]
    return (min(starts), max(ends)) if starts and ends else None


def _months_in(start: date, end: date) -> float:
    """Statement length in months, counting days so a 01/04-30/09 statement is 6.0."""
    return max(((end - start).days + 1) / (365.25 / 12), 1.0)


def _minus_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


def _is_bounce(t: dict[str, Any]) -> bool:
    return bool(BOUNCE.search(t["narration"])) and not CHARGE.search(t["narration"])


def _is_revenue_credit(t: dict[str, Any]) -> bool:
    return bool(t.get("credit")) and not NON_REVENUE.search(t["narration"])


def _gst_periods(results: list[ExtractionResult]) -> dict[str, dict[str, Any]]:
    periods: dict[str, dict[str, Any]] = {}
    for r in _docs(results, DocumentType.GSTR_3B):
        for row in r.tables.get("periods", []):
            periods.setdefault(row["period"], row)
    return dict(sorted(periods.items()))


# ---------- features ----------


def profile_features(results: list[ExtractionResult], *, as_of: date | None = None) -> ProfileFeatures:
    """SMEProfile-compatible features from a set of extracted documents, each with provenance.
    bureau_score and sector are never derived (they cannot come from these documents)."""
    as_of = as_of or date.today()
    out = ProfileFeatures(as_of=as_of)
    f = out.features
    rows = _transactions(results)
    span = _statement_span(results, rows)
    periods = _gst_periods(results)

    # Vintage: whole months from GST registration to as_of.
    if reg := _field(results, DocumentType.GST_CERTIFICATE, "registration_date"):
        months = months_between(parse_date(reg), as_of)
        f["business_vintage_months"] = FeatureValue(value=months, source="gst_certificate.registration_date", method=f"GST registration {reg} to {as_of.isoformat()}")
        f["gst_registration_vintage_months"] = f["business_vintage_months"].model_copy()

    # GST registration: only asserted when a valid GSTIN was read; absence is not proof of "no".
    for kind in (DocumentType.GST_CERTIFICATE, DocumentType.GSTR_3B):
        if gstin := _field(results, kind, "gstin"):
            f["gst_registered"] = FeatureValue(value=True, source=f"{kind.value}.gstin", method=f"valid GSTIN {gstin} (check character verified)")
            break

    _constitution(results, out)
    _turnover(results, out, rows, span, periods)
    if rows and span:
        _bounces(out, rows, span)
        _foir(out, rows, span)
        f["bank_statement_months"] = FeatureValue(value=round(_months_in(*span), 1), source="bank_statement.period", method=f"{span[0].isoformat()} to {span[1].isoformat()}")

    out.checks = cross_checks(results, rows=rows, periods=periods)
    return out


def _constitution(results: list[ExtractionResult], out: ProfileFeatures) -> None:
    if value := _field(results, DocumentType.GST_CERTIFICATE, "constitution_of_business"):
        out.features["constitution"] = FeatureValue(value=value, source="gst_certificate.constitution_of_business", method="as stated on GST REG-06")
        return
    holder = _field(results, DocumentType.GST_CERTIFICATE, "pan_from_gstin") or _field(results, DocumentType.PAN_CARD, "pan")
    if holder is None:
        return
    guess = {"P": "proprietorship", "F": "partnership", "H": "huf"}.get(holder[3])
    if guess:
        out.features["constitution"] = FeatureValue(
            value=guess, source="pan_card.pan", estimate=True,
            method=f"PAN 4th character '{holder[3]}'; please confirm (an 'F' PAN can also be an LLP)" if holder[3] == "F" else f"PAN 4th character '{holder[3]}'; please confirm",
        )
    else:
        out.warnings.append(f"Constitution unknown: PAN type '{holder[3]}' does not say which kind of entity; upload the GST certificate")


def _turnover(results, out: ProfileFeatures, rows, span, periods) -> None:
    f = out.features
    if periods:
        # The 12 calendar months ending at the latest return, not the last 12 returns filed.
        latest = parse_date(list(periods)[-1] + "-01")
        window = month_range(_minus_months(latest, 11), latest)
        present = [m for m in window if m in periods]
        total = sum(periods[m]["taxable_outward_value"] for m in present)
        span = f"{month_label(window[0])} to {month_label(window[-1])}"
        if len(present) == 12:
            f["annual_turnover"] = FeatureValue(value=round(total), source="gstr_3b.periods.taxable_outward_value", method=f"sum of 3.1(a) taxable outward supplies, {span}")
        else:
            gaps = ", ".join(month_label(m) for m in window if m not in periods)
            f["annual_turnover"] = FeatureValue(
                value=round(total * 12 / len(present)), source="gstr_3b.periods.taxable_outward_value", estimate=True,
                method=f"annualised from {len(present)} month(s) of GSTR-3B in {span} ({inr(total)} x 12 / {len(present)}); no return for {gaps}",
            )
        return
    itrs = sorted(_docs(results, DocumentType.ITR), key=lambda r: r.fields.get("assessment_year").value if r.fields.get("assessment_year") else "")
    for itr in reversed(itrs):
        if "business_turnover" in itr.fields:
            ay = itr.fields["assessment_year"].value if "assessment_year" in itr.fields else "unknown AY"
            f["annual_turnover"] = FeatureValue(value=round(itr.fields["business_turnover"].value), source="itr.business_turnover", method=f"gross turnover/receipts in the ITR for AY {ay}")
            return
    if rows and span:
        credits = sum(t["credit"] for t in rows if _is_revenue_credit(t))
        months = _months_in(*span)
        f["annual_turnover"] = FeatureValue(
            value=round(credits * 12 / months), source="bank_statement.transactions.credit", estimate=True,
            method=f"bank credits {inr(credits)} over {months:.1f} months, annualised; excludes self-transfers, reversals, refunds, loan disbursals and interest",
        )


def _bounces(out: ProfileFeatures, rows, span) -> None:
    end = span[1]
    start = _minus_months(end + timedelta(days=1), 6)  # 30/09 -> window 01/04..30/09
    hits = [t for t in rows if start <= t["_date"] <= end and _is_bounce(t)]
    method = f"return/bounce entries from {start.isoformat()} to {end.isoformat()} (6 months to statement end; charge rows not counted)"
    if span[0] > start:
        method += f"; statement only starts {span[0].isoformat()}, so fewer than 6 months were seen"
    out.features["bounces_6m"] = FeatureValue(value=len(hits), source="bank_statement.transactions.narration", method=method, estimate=span[0] > start)


def _foir(out: ProfileFeatures, rows, span) -> None:
    months = _months_in(*span)
    emis = sum(t["debit"] for t in rows if t.get("debit") and EMI.search(t["narration"]) and not BOUNCE.search(t["narration"]) and not CHARGE.search(t["narration"]))
    credits = sum(t["credit"] for t in rows if _is_revenue_credit(t))
    if credits <= 0:
        out.warnings.append("FOIR not estimated: no business credits in the bank statement")
        return
    out.features["foir"] = FeatureValue(
        value=round(emis / credits, 2), source="bank_statement.transactions", estimate=True,
        method=f"EMI/NACH/ECS debits {inr(emis / months)}/month over business credits {inr(credits / months)}/month ({months:.1f} months)",
    )


# ---------- cross-document checks ----------


def name_match(a: str, b: str) -> tuple[CheckOutcome, float]:
    """pass: same name (allowing small OCR slips); warn: initials or close ('R. Kumar' vs 'Ravi Kumar'); fail: different."""
    x, y = normalize_name(a), normalize_name(b)
    ratio = SequenceMatcher(None, x, y).ratio()
    if x == y or ratio >= NAME_PASS:
        return "pass", ratio
    tx, ty = x.split(), y.split()
    short, long_ = sorted((tx, ty), key=len)
    if short and len(short) <= len(long_) and all(
        any(s == l or (len(s) == 1 and l.startswith(s)) or (len(l) == 1 and s.startswith(l)) for l in long_) for s in short
    ):
        return "warn", ratio
    return ("warn" if ratio >= NAME_CONFIRM else "fail"), ratio


def _pan_in_gstin(results, checks: list[DocumentCheck]) -> None:
    gstin = _field(results, DocumentType.GST_CERTIFICATE, "gstin") or _field(results, DocumentType.GSTR_3B, "gstin")
    if not gstin:
        return
    inner = gstin[2:12]
    for kind in (DocumentType.PAN_CARD, DocumentType.ITR):
        pan = _field(results, kind, "pan")
        if not pan:
            continue
        docs = ["gst_certificate" if _field(results, DocumentType.GST_CERTIFICATE, "gstin") else "gstr_3b", kind.value]
        if pan == inner:
            checks.append(DocumentCheck(rule="pan_in_gstin", outcome="pass", documents=docs, message=f"PAN in GSTIN: {gstin} carries PAN {inner}, same as the {kind.value.replace('_', ' ')}"))
        elif inner[3] != "P" and pan[3] == "P":
            checks.append(DocumentCheck(
                rule="pan_in_gstin", outcome="warn", documents=docs,
                message=f"PAN in GSTIN: the GSTIN belongs to a {inner[3]}-type PAN ({inner}), the uploaded PAN {pan} is a person's; upload the business PAN",
            ))
        else:
            checks.append(DocumentCheck(rule="pan_in_gstin", outcome="fail", documents=docs, message=f"PAN in GSTIN: {gstin} carries PAN {inner}, but the {kind.value.replace('_', ' ')} shows {pan}"))
    other = _field(results, DocumentType.GSTR_3B, "gstin")
    cert = _field(results, DocumentType.GST_CERTIFICATE, "gstin")
    if cert and other:
        ok = cert == other
        checks.append(DocumentCheck(
            rule="gstin_consistency", outcome="pass" if ok else "fail", documents=["gst_certificate", "gstr_3b"],
            message=f"GSTIN: certificate and GSTR-3B both show {cert}" if ok else f"GSTIN: certificate shows {cert}, GSTR-3B shows {other}",
        ))


def _names(results, checks: list[DocumentCheck]) -> None:
    person = [(k, _field(results, k, "name")) for k in (DocumentType.PAN_CARD, DocumentType.AADHAAR, DocumentType.ITR)]
    person = [(k, n) for k, n in person if n]
    gst_pan = _field(results, DocumentType.GST_CERTIFICATE, "pan_from_gstin")
    legal = _field(results, DocumentType.GST_CERTIFICATE, "legal_name")
    trade = _field(results, DocumentType.GST_CERTIFICATE, "trade_name")
    # A proprietor's GST legal name is the person's name; a company's or firm's is not.
    if legal and (gst_pan is None or gst_pan[3] == "P"):
        person.append((DocumentType.GST_CERTIFICATE, legal))
    if person:
        ref_kind, ref = person[0]
        for kind, name in person[1:]:
            _name_check(checks, ref_kind.value, ref, kind.value, name)
    holder = _field(results, DocumentType.BANK_STATEMENT, "account_holder_name")
    if holder:
        options = [(k.value, n) for k, n in person[:1]] + [("gst_certificate", n) for n in (legal, trade) if n]
        if options:
            best = max(options, key=lambda o: (["fail", "warn", "pass"].index(name_match(holder, o[1])[0]), name_match(holder, o[1])[1]))
            _name_check(checks, best[0], best[1], "bank_statement", holder)


def _name_check(checks, kind_a: str, a: str, kind_b: str, b: str) -> None:
    outcome, ratio = name_match(a, b)
    label = f"{kind_b.replace('_', ' ')} vs {kind_a.replace('_', ' ')}"
    message = {
        "pass": f"Name ({label}): '{b}' matches '{a}'",
        "warn": f"Name ({label}): '{b}' looks like '{a}' ({ratio:.0%} similar); please confirm they are the same person",
        "fail": f"Name ({label}): '{b}' does not match '{a}' ({ratio:.0%} similar)",
    }[outcome]
    checks.append(DocumentCheck(rule="name_match", outcome=outcome, documents=[kind_a, kind_b], message=message))


def _dob(results, checks: list[DocumentCheck]) -> None:
    pan_dob = _field(results, DocumentType.PAN_CARD, "dob")
    aadhaar_dob = _field(results, DocumentType.AADHAAR, "dob")
    aadhaar_year = _field(results, DocumentType.AADHAAR, "year_of_birth")
    if not pan_dob or not (aadhaar_dob or aadhaar_year):
        return
    docs = ["pan_card", "aadhaar"]
    if aadhaar_dob:
        ok = pan_dob == aadhaar_dob
        msg = f"Date of birth: PAN and Aadhaar both show {pan_dob}" if ok else f"Date of birth: PAN shows {pan_dob}, Aadhaar shows {aadhaar_dob}"
    else:
        ok = int(pan_dob[:4]) == aadhaar_year
        msg = f"Date of birth: PAN year {pan_dob[:4]} matches Aadhaar year of birth" if ok else f"Date of birth: PAN shows {pan_dob}, Aadhaar year of birth is {aadhaar_year}"
    checks.append(DocumentCheck(rule="dob_match", outcome="pass" if ok else "fail", documents=docs, message=msg))


def _turnover_vs_bank(rows, periods, checks: list[DocumentCheck]) -> None:
    if not rows or not periods:
        return
    bank_months = {month_key(t["_date"]) for t in rows}
    common = [m for m in periods if m in bank_months]
    if not common:
        return
    gst = sum(periods[m]["taxable_outward_value"] + sum((periods[m].get(k) or 0) for k in ("igst", "cgst", "sgst", "cess")) for m in common)
    credits = sum(t["credit"] for t in rows if month_key(t["_date"]) in common and _is_revenue_credit(t))
    if gst <= 0:
        return
    gap = (credits - gst) / gst
    span = f"{month_label(common[0])} to {month_label(common[-1])} ({len(common)} months)"
    ok = abs(gap) <= TURNOVER_TOLERANCE
    checks.append(DocumentCheck(
        rule="turnover_vs_bank", outcome="pass" if ok else "warn", documents=["gstr_3b", "bank_statement"],
        message=(
            f"Turnover: bank credits {inr(credits)} vs GSTR-3B sales incl. tax {inr(gst)} for {span}, "
            + (f"within {TURNOVER_TOLERANCE:.0%}" if ok else f"{abs(gap):.0%} {'higher' if gap > 0 else 'lower'}; explain the difference (other bank accounts, cash sales, non-sales credits)")
        ),
    ))


def _statements(results, checks: list[DocumentCheck]) -> None:
    for r in _docs(results, DocumentType.BANK_STATEMENT):
        if (b := r.fields.get("balance_breaks")) is not None:
            n = b.value
            checks.append(DocumentCheck(
                rule="statement_balance_math", outcome="pass" if n == 0 else "fail", documents=["bank_statement"],
                message="Bank statement: every row's balance follows from the previous one" if n == 0
                else f"Bank statement: balance math breaks on {n} row(s); the statement may have been edited, upload the bank's original PDF",
            ))
        if (gaps := r.fields.get("missing_months")) is not None:
            months = ", ".join(month_label(m) for m in gaps.value)
            checks.append(DocumentCheck(
                rule="statement_coverage", outcome="pass" if not gaps.value else "warn", documents=["bank_statement"],
                message="Bank statement: every month in the period has transactions" if not gaps.value
                else f"Bank statement: no transactions in {months}; upload the missing pages or month",
            ))


def _pincode(results, checks: list[DocumentCheck]) -> None:
    a = _field(results, DocumentType.AADHAAR, "pincode")
    g = _field(results, DocumentType.GST_CERTIFICATE, "pincode")
    if a and g:
        ok = a == g
        checks.append(DocumentCheck(
            rule="address_pincode", outcome="pass" if ok else "warn", documents=["aadhaar", "gst_certificate"],
            message=f"Address: Aadhaar and GST address share PIN {a}" if ok else f"Address: Aadhaar PIN {a}, business PIN {g}; fine if the shop is elsewhere, please confirm",
        ))


def cross_checks(results: list[ExtractionResult], *, rows=None, periods=None) -> list[DocumentCheck]:
    rows = _transactions(results) if rows is None else rows
    periods = _gst_periods(results) if periods is None else periods
    checks: list[DocumentCheck] = []
    _pan_in_gstin(results, checks)
    _names(results, checks)
    _dob(results, checks)
    _pincode(results, checks)
    _turnover_vs_bank(rows, periods, checks)
    _statements(results, checks)
    return checks


__all__ = ["DocumentCheck", "FeatureValue", "ProfileFeatures", "cross_checks", "name_match", "profile_features"]
