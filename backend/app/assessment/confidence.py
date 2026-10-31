"""Input quality: how far the extractor itself trusts the fields a parameter rests on.

Policy (thresholds in config.json):
- ok:        every referenced field is confident (>= REVIEW_CONFIDENCE) or was confirmed by the SME.
- review:    a referenced field needs review (confidence < 0.85, unconfirmed), or enough table rows do.
             The parameter is still scored, flagged, and counts at `review_weight_factor` of its weight, so
             uncertain evidence moves the index less and lowers coverage.
- unusable:  a referenced field is missing or below `unusable_below`, or most table rows are. The
             parameter is NOT scored (shown as pending) until the SME confirms or re-uploads.

Judged on field and row confidence, never on envelope status: a statement whose balance math failed is
`needs_review` as a document, but its bounce and FOIR figures still count (the failed check has its own
heavily weighted parameter and a grade cap).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.assessment.config import ConfidencePolicy
from app.assessment.features import Context
from app.schemas.common import REVIEW_CONFIDENCE, EvidenceRef, Extracted

Tier = Literal["ok", "review", "unusable"]
_RANK = {"ok": 0, "review": 1, "unusable": 2}


@dataclass(frozen=True)
class InputQuality:
    tier: Tier
    notes: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()  # "document_type.field" of the inputs that caused the tier


def _judge(item: object, policy: ConfidencePolicy) -> Tier:
    if isinstance(item, Extracted):
        if item.user_confirmed:
            return "ok"
        if item.value is None or item.confidence < policy.unusable_below:
            return "unusable"
        return "review" if item.needs_review else "ok"
    if isinstance(item, list) and item:
        provenance = [r.provenance for r in item if getattr(r, "provenance", None) is not None]
        if provenance:
            low = sum(1 for p in provenance if p.confidence < REVIEW_CONFIDENCE) / len(provenance)
            very_low = sum(1 for p in provenance if p.confidence < policy.unusable_below) / len(provenance)
            if very_low >= policy.table_row_share_unusable:
                return "unusable"
            if low >= policy.table_row_share_review:
                return "review"
    return "ok"


def input_quality(ctx: Context, evidence: tuple[EvidenceRef, ...] | list[EvidenceRef], policy: ConfidencePolicy) -> InputQuality:
    tier: Tier = "ok"
    notes: list[str] = []
    fields: list[str] = []
    for ref in evidence:
        env = ctx.by_id.get(ref.document_id)
        name = ref.field.removeprefix("data.")
        if env is None or env.data is None or not ref.field.startswith("data.") or "." in name or "[" in name:
            continue
        verdict = _judge(getattr(env.data, name, None), policy)
        if verdict != "ok":
            label = f"{env.document_type.value}.{name}"
            fields.append(label)
            notes.append(f"{label} {'is below the usable confidence' if verdict == 'unusable' else 'needs confirmation'}")
            if _RANK[verdict] > _RANK[tier]:
                tier = verdict
    return InputQuality(tier, tuple(notes), tuple(dict.fromkeys(fields)))
