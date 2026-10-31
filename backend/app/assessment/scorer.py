"""score_sme: SmeProfile + validated DocumentEnvelopes -> ScoreCard. Deterministic; an LLM never sets a number.

Math (all constants in config.json):
- each computed parameter gets band points 0-100 from its bands
- effective weight = weight (x review_weight_factor when its inputs need review); 0 when not computed
- index = sum(effective_weight x points) / sum(effective_weight), over computed parameters only
- coverage = sum(effective_weight) / sum(weight of applicable parameters in the weight base)
- grade from index thresholds; "insufficient_data" below min coverage or with nothing computed
- a computed `critical` parameter at 0 points caps the grade at critical_failure_grade_cap (index unchanged)
Pending and not_applicable parameters never reduce the index; they lower coverage (pending) or leave the
base (not_applicable).

`as_of` falls back to the profile's own timestamp, never the system clock.
"""

from __future__ import annotations

from datetime import date

from app.assessment.config import AssessmentConfig, band_for, load_config
from app.assessment.confidence import input_quality
from app.assessment.features import Context, Feature, Unavailable
from app.assessment.fieldlock import lock_features
from app.assessment.models import (
    CategorySummary,
    Coverage,
    FeatureTable,
    MissingInput,
    ParameterResult,
    ScoreCard,
)
from app.assessment.registry import BY_ID, CATEGORIES, REGISTRY, Parameter
from app.schemas.common import CheckStatus, CrossCheck
from app.schemas.documents import DocumentEnvelope
from app.schemas.profile import SmeProfile

BANK_UNVERIFIED = "The bank statement behind this figure does not reconcile and may include an edited row, so treat it as unverified."


def _evaluate(p: Parameter, ctx: Context, cfg: AssessmentConfig, bank_failed: bool) -> ParameterResult:
    pc = cfg.parameters[p.id]
    base = dict(id=p.id, name=p.name, category=p.category, weight=pc.weight, weight_source=pc.weight_source, in_total=p.in_total)

    def pending(reason: str, waits_for: str) -> ParameterResult:
        return ParameterResult(**base, status="pending", reason=f"Not scored: {reason}", waits_for=waits_for)

    if p.applies is not None and (why := p.applies(ctx)):
        return ParameterResult(**base, status="not_applicable", reason=f"Not applicable: {why}")
    if p.feature is None:
        return pending(p.pending_reason or "no input exists yet.", p.waits_for or "")
    out = p.feature(ctx)
    if isinstance(out, Unavailable):
        return pending(out.reason, out.waits_for)
    assert isinstance(out, Feature)
    if not pc.bands:
        raise ValueError(f"{p.id} is computable but has no bands in config.json")

    quality = input_quality(ctx, out.evidence, cfg.confidence)
    if quality.tier == "unusable":
        return pending(
            f"an input is missing or read with very low confidence ({'; '.join(quality.notes)}).",
            "SME confirmation or re-upload of " + ", ".join(quality.fields),
        )
    band = band_for(pc.bands, out.value)
    low_confidence = quality.tier == "review" or out.low_confidence is not None
    flags = list(quality.notes) + ([out.low_confidence] if out.low_confidence else [])
    reason = f"{out.display}." if out.terse else f"{out.display}: {band.label}."
    if low_confidence:
        reason += f" Counted at {cfg.confidence.review_weight_factor:.0%} weight because an input is unconfirmed."
    if p.review_flag:
        flags.append(f"Fairness review: {p.review_flag}")
    if p.uses_bank and bank_failed:
        flags.append(BANK_UNVERIFIED)
        reason += f" {BANK_UNVERIFIED}"
    return ParameterResult(
        **base,
        status="computed",
        effective_weight=pc.weight * (cfg.confidence.review_weight_factor if low_confidence else 1.0),
        value=out.value,
        value_display=out.display,
        band=band.label,
        points=band.points,
        evidence=list(out.evidence),
        reason=reason,
        low_confidence=low_confidence,
        flags=flags,
    )


def _index(results: list[ParameterResult]) -> float | None:
    weight = sum(r.effective_weight for r in results)
    if weight <= 0:
        return None
    return round(sum(r.effective_weight * r.points for r in results) / weight, 1)


def _coverage(results: list[ParameterResult], cfg: AssessmentConfig) -> Coverage:
    base = [r for r in results if r.in_total]
    applicable = [r for r in base if r.status != "not_applicable"]
    computed = [r for r in applicable if r.status == "computed"]
    applicable_w = sum(r.weight for r in applicable)
    effective = sum(r.effective_weight for r in computed)
    pct = round(100 * effective / applicable_w, 1) if applicable_w else 0.0
    label = next(c.label for c in cfg.coverage_labels if pct >= c.min_pct)
    return Coverage(
        total_weight=sum(r.weight for r in base),
        applicable_weight=applicable_w,
        computed_weight=sum(r.weight for r in computed),
        effective_weight=effective,
        coverage_pct=pct,
        label=label,
        computed_count=len(computed),
        pending_count=sum(1 for r in applicable if r.status == "pending"),
        not_applicable_count=sum(1 for r in base if r.status == "not_applicable"),
    )


def score_sme(
    profile: SmeProfile,
    documents: list[DocumentEnvelope],
    *,
    as_of: date | None = None,
    config: AssessmentConfig | None = None,
) -> ScoreCard:
    """`documents` must be the VALIDATED envelopes (app.scoring.assess(...).documents): tags and statuses
    are set by validation."""
    cfg = config or load_config()
    as_of = as_of or profile.updated_at.date()
    ctx = Context.build(profile, documents, as_of)
    balance = ctx.check(CrossCheck.BALANCE_MATH)
    bank_failed = balance is not None and balance.status == CheckStatus.FAIL

    results = [_evaluate(p, ctx, cfg, bank_failed) for p in REGISTRY]
    # Results only count where the registry says they are in the weight base.
    scored = [r for r in results if r.status == "computed" and r.in_total]

    coverage = _coverage(results, cfg)
    index = _index(scored)

    caps = [p.name for p, r in zip(REGISTRY, results) if p.critical and r.status == "computed" and r.points == 0]
    grade_order = [g.grade for g in cfg.grades]
    if index is None or coverage.coverage_pct < cfg.min_coverage_for_grade_pct:
        grade = "insufficient_data"
    else:
        grade = next(g.grade for g in cfg.grades if index >= g.min_index)
        if caps and grade_order.index(grade) < grade_order.index(cfg.critical_failure_grade_cap):
            grade = cfg.critical_failure_grade_cap

    provisional_reasons = [f"{r.name}: {r.flags[0]}" for r in scored if r.low_confidence]
    provisional_reasons += [f"Critical check failed: {name}" for name in caps]
    if bank_failed and not caps:
        provisional_reasons.append("Bank statement does not reconcile")

    categories = []
    for category in CATEGORIES:
        rows = [r for r in results if r.category == category]
        cov = _coverage(rows, cfg)
        categories.append(CategorySummary(
            category=category,
            index=_index([r for r in rows if r.status == "computed" and r.in_total]),
            coverage_pct=cov.coverage_pct,
            computed_count=cov.computed_count,
            pending_count=cov.pending_count,
        ))

    # Largest weighted shortfall first; ties fall back to registry order (stable sort).
    # Structural attributes under fairness review (size, constitution ...) are scored but never headlined.
    headline = [r for r in scored if BY_ID[r.id].review_flag is None]
    concerns = [f"{r.name}: {r.reason}" for r in sorted(headline, key=lambda r: r.effective_weight * (100 - r.points), reverse=True) if r.points <= 50][:6]
    strengths = [f"{r.name}: {r.reason}" for r in sorted(headline, key=lambda r: r.effective_weight * r.points, reverse=True) if r.points >= 80][:4]
    missing = sorted((r for r in results if r.status == "pending" and r.in_total), key=lambda r: -r.weight)[:6]

    table = lock_features({r.id: (r.value if r.status == "computed" else None) for r in results}, [p.id for p in REGISTRY])
    return ScoreCard(
        sme_id=profile.sme_id,
        as_of=as_of,
        config_version=cfg.config_version,
        weights_calibrated=cfg.calibrated,
        index=index,
        grade=grade,
        grade_capped_by=caps,
        provisional=bool(provisional_reasons),
        provisional_reasons=provisional_reasons,
        coverage=coverage,
        categories=categories,
        strengths=strengths,
        concerns=concerns,
        biggest_missing_inputs=[MissingInput(parameter=r.name, weight=r.weight, waits_for=r.waits_for or "") for r in missing],
        parameters=results,
        features=FeatureTable(features=table),
    )
