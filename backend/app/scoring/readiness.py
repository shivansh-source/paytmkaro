"""Credit-readiness score, 0-100. Deterministic; an LLM may explain it but never sets it.

| Component           | Max | Earned by                                                          |
|---------------------|-----|--------------------------------------------------------------------|
| Documents complete  | 25  | each required document uploaded and readable                       |
| Identity verified   | 25  | PAN-in-GSTIN, name, DOB, address cross-checks (warn = half)        |
| Data integrity      | 15  | balance math, no missing months, GST consistent with bank          |
| Cash flow           | 25  | bounces (10), FOIR (10), statement length (5)                      |
| Credit history      | 10  | bureau score band                                                  |

A failed balance-math check (possible tampering) caps the score at 49, "not ready", whatever else holds.
"""

from __future__ import annotations

from app.schemas.common import REQUIRED_DOCUMENTS, Check, CheckStatus, CrossCheck
from app.schemas.profile import BureauScore, CashflowMetrics, Readiness, ReadinessComponent
from app.validation.cross import DocumentSet

READY, ALMOST = 75, 50
TAMPER_CAP = 49
_CREDIT = {CheckStatus.PASS: 1.0, CheckStatus.WARN: 0.5, CheckStatus.FAIL: 0.0}


def _from_checks(name: str, max_points: float, checks: dict[str, Check], ids: list[CrossCheck]) -> ReadinessComponent:
    present = [checks[i] for i in ids if i in checks]
    earned = sum(_CREDIT[c.status] for c in present)
    missing = len(ids) - len(present)
    note = f"{missing} check(s) waiting for documents" if missing else None
    return ReadinessComponent(name=name, points=round(max_points * earned / len(ids), 1), max_points=max_points, note=note)


def score_readiness(
    docs: DocumentSet, cross: list[Check], metrics: CashflowMetrics, bureau: BureauScore | None
) -> Readiness:
    by_id = {c.id: c for c in cross}

    have = [t for t in REQUIRED_DOCUMENTS if docs.get(t)]
    documents = ReadinessComponent(
        name="Documents complete",
        points=round(25 * len(have) / len(REQUIRED_DOCUMENTS), 1),
        max_points=25,
        note=f"{len(have)} of {len(REQUIRED_DOCUMENTS)} required documents",
    )
    identity = _from_checks(
        "Identity verified", 25, by_id,
        [CrossCheck.PAN_IN_GSTIN, CrossCheck.NAME_MATCH, CrossCheck.DOB_MATCH, CrossCheck.ADDRESS_MATCH],
    )
    integrity = _from_checks(
        "Data integrity", 15, by_id, [CrossCheck.BALANCE_MATH, CrossCheck.STATEMENT_GAPS, CrossCheck.GST_VS_BANK]
    )

    cash = 0.0
    notes = []
    if metrics.bounces_6m is not None:
        b = metrics.bounces_6m.value
        cash += 10 if b == 0 else 5 if b <= 2 else 0
        notes.append(f"{b} bounce(s) in 6 months")
    if metrics.foir is not None:
        f = metrics.foir.value
        cash += 10 if f <= 0.3 else 5 if f <= 0.5 else 0
        notes.append(f"FOIR {f:.0%}")
    cash += 5 if metrics.months_analyzed >= 6 else 2.5 if metrics.months_analyzed >= 3 else 0
    cashflow = ReadinessComponent(name="Cash flow", points=cash, max_points=25, note=", ".join(notes) or "No bank statement yet")

    if bureau is None:
        credit = ReadinessComponent(name="Credit history", points=0, max_points=10, note="Add your bureau score")
    else:
        s = bureau.value
        points = 10 if s >= 750 else 7 if s >= 700 else 4 if s >= 650 else 0
        credit = ReadinessComponent(name="Credit history", points=points, max_points=10, note=f"{s} ({bureau.source.replace('_', ' ')})")

    components = [documents, identity, integrity, cashflow, credit]
    score = round(sum(c.points for c in components))
    balance = by_id.get(CrossCheck.BALANCE_MATH)
    if balance is not None and balance.status == CheckStatus.FAIL:
        score = min(score, TAMPER_CAP)
    band = "ready" if score >= READY else "almost_ready" if score >= ALMOST else "not_ready"
    return Readiness(score=score, band=band, components=components)
