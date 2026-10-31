"""VLM fallback for pages the rules could not label.

Only page images go out (already Aadhaar-redacted by ingest), never page text. Up to
IMAGES_PER_REQUEST pages share one request, and at most
config.VLM_MAX_REQUESTS_PER_DOCUMENT requests are made per document. The model only
picks a label from a fixed list; confidence is set here in code:
- uncorroborated VLM label: VLM_ONLY_CONFIDENCE (0.6, below anything rules can reach
  with a decisive signal);
- corroborated (the rules found at least one signal for the same type):
  0.7 + 0.15 * evidence(rule score), capped at 0.85.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app import config
from app.documents.classify.rules import EVIDENCE_SCALE, PageScore
from app.documents.classify.segments import Decision
from app.documents.models import DocumentType
from app.documents.ports import VlmBudgetExceeded, VlmClient, VlmError

IMAGES_PER_REQUEST = 3
VLM_ONLY_CONFIDENCE = 0.6
VLM_MAX_TOKENS = 300
_LABELS = [t.value for t in DocumentType]

PROMPT = """You are sorting scanned Indian KYC and business documents for a loan application.
For each of the {n} attached page image(s), pick exactly ONE label from this list:
- aadhaar: Aadhaar card or e-Aadhaar letter (UIDAI), front or back
- pan_card: PAN card issued by the Income Tax Department
- gst_certificate: GST registration certificate (Form GST REG-06)
- gstr_3b: GSTR-3B GST return
- itr: income tax return form or ITR-V acknowledgement
- bank_statement: a page of a bank account statement
- bureau_report: credit bureau report (CIBIL, Experian, Equifax, CRIF), consumer or commercial
- udyam_certificate: Udyam (MSME) registration certificate
- financial_statements: balance sheet and/or profit and loss account, audited, CA-certified or provisional
- sanction_letter: loan or credit facility sanction letter or Key Fact Statement
- settlement_report: payment gateway, POS or UPI merchant settlement report
- unknown: none of the above, blank, or unreadable
Do not copy any names, ID numbers or amounts from the images.
Reply with JSON only, one entry per image in order:
{{"pages": [{{"image": 1, "document_type": "<label>", "reason": "<at most 12 words>"}}]}}"""


def _clean_reason(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    text = re.sub(r"\d{4,}", "####", text)  # never store ID-like numbers from a model reply
    return " ".join(text.split())[:120]


def parse_reply(reply: Any, n: int) -> dict[int, tuple[DocumentType, str]]:
    """Map image number (1-based) -> (label, reason). Anything malformed, out of range,
    duplicated or outside the label list is dropped (the page stays unknown)."""
    if not isinstance(reply, dict):
        return {}
    entries = reply.get("pages")
    if not isinstance(entries, list):
        entries = [dict(reply, image=1)] if n == 1 and "document_type" in reply else []
    out: dict[int, tuple[DocumentType, str]] = {}
    seen: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        image = entry.get("image")
        label = entry.get("document_type")
        if not isinstance(image, int) or isinstance(image, bool) or not 1 <= image <= n:
            continue
        if image in seen:  # contradictory duplicate: trust neither
            out.pop(image, None)
            continue
        seen.add(image)
        if isinstance(label, str) and label.strip().lower() in _LABELS:
            out[image] = (DocumentType(label.strip().lower()), _clean_reason(entry.get("reason")))
    return out


def _corroborated_confidence(rule_score: float) -> float:
    evidence = 1 - math.exp(-rule_score / EVIDENCE_SCALE)
    return round(min(0.85, 0.7 + 0.15 * evidence), 3)


def vlm_fallback(
    decisions: list[Decision],
    scores: list[PageScore],
    images: dict[int, bytes],
    vlm: VlmClient,
    budget: object | None = None,
) -> tuple[int, list[str]]:
    """Ask the VLM about still-unknown pages that have an image; mutate their decisions.
    Returns (requests made, warnings). VLM failures leave the rules result untouched.

    `budget` is an optional shared pool (see app.documents.vlm.budget.VlmBudget), duck-typed:
    `spend() -> bool` takes one request (False when empty) and an optional `drain()` empties
    it after a rate limit. Without one, config.VLM_MAX_REQUESTS_PER_DOCUMENT applies."""
    warnings: list[str] = []
    todo = [d for d in decisions if d.doc_type is DocumentType.UNKNOWN and d.page_index in images]
    batches = [todo[i : i + IMAGES_PER_REQUEST] for i in range(0, len(todo), IMAGES_PER_REQUEST)]
    local_limit = max(0, config.VLM_MAX_REQUESTS_PER_DOCUMENT)
    by_index = {s.page_index: s for s in scores}
    requests = 0
    for b, batch in enumerate(batches):
        if budget is not None:
            out_of_requests = not budget.spend()  # type: ignore[attr-defined]
        else:
            out_of_requests = requests >= local_limit
        if out_of_requests:
            for d in (d for rest in batches[b:] for d in rest):
                d.signals.append("vlm: not asked (per-document request limit reached)")
            warnings.append("VLM request limit for this document reached; remaining pages kept as unknown")
            break
        requests += 1
        try:
            reply = vlm.complete_json(
                PROMPT.format(n=len(batch)), [images[d.page_index] for d in batch], max_tokens=VLM_MAX_TOKENS
            )
        except VlmBudgetExceeded:
            if budget is not None and hasattr(budget, "drain"):
                budget.drain()  # type: ignore[attr-defined]
            for d in (d for rest in batches[b:] for d in rest):
                d.signals.append("vlm: not available (rate limit or budget reached)")
            warnings.append("VLM rate limit or budget exhausted; rules result kept")
            break
        except VlmError:
            for d in batch:
                d.signals.append("vlm: request failed; kept the rules result")
            warnings.append("A VLM request failed; rules result kept for its pages")
            continue
        labels = parse_reply(reply, len(batch))
        for pos, d in enumerate(batch, start=1):
            _apply(d, labels.get(pos), by_index.get(d.page_index))
    return requests, warnings


def _apply(d: Decision, answer: tuple[DocumentType, str] | None, score: PageScore | None) -> None:
    if answer is None:
        d.signals.append("vlm: no valid label in the reply; kept unknown")
        return
    label, reason = answer
    note = f"vlm: {label.value}" + (f" ({reason})" if reason else "")
    if label is DocumentType.UNKNOWN:
        d.signals.append(note)
        return
    rule_score = score.scores.get(label, 0.0) if score else 0.0
    if rule_score > 0:
        d.doc_type, d.by = label, "rules+vlm"
        d.confidence = _corroborated_confidence(rule_score)
        d.signals = [note, *score.signal_labels(label)]  # type: ignore[union-attr]
    else:
        d.doc_type, d.by = label, "vlm"
        d.confidence = VLM_ONLY_CONFIDENCE
        d.signals = [note, "no rule signal for this type: confidence capped"]
