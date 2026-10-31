"""Page decisions -> context fill-in -> segments -> dominant document type."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.documents.classify.rules import PageScore
from app.documents.models import DocumentSegment, DocumentType

MAX_GAP = 2  # at most this many unknown pages are absorbed between two same-type pages
CONTEXT_FACTOR = 0.8  # a page labelled from its neighbours gets this share of their confidence

UNKNOWN = DocumentType.UNKNOWN
# Types that run over many pages whose continuation pages can be blank or rows-only. Other
# types (ID cards, certificates, letters) are one or two pages, so a gap is not assumed to
# belong to them.
CONTINUABLE = {DocumentType.BANK_STATEMENT, DocumentType.SETTLEMENT_REPORT, DocumentType.FINANCIAL_STATEMENTS}


@dataclass
class Decision:
    """Mutable per-page label while the pipeline runs; becomes a PageClassification."""

    page_index: int
    doc_type: DocumentType
    confidence: float
    signals: list[str] = field(default_factory=list)
    by: str = "rules"  # rules | context | vlm | rules+vlm | none


def from_score(score: PageScore) -> Decision:
    if score.accepted:
        return Decision(score.page_index, score.best, score.confidence, score.signal_labels(score.best))
    if score.best_score > 0:
        signals = [
            "no document type reached the threshold",
            f"best guess: {score.best.value} (score {score.best_score:.1f}, confidence {score.confidence:.2f})",
            *score.signal_labels(score.best),
        ]
    else:
        signals = ["no recognisable document signals"]
    return Decision(score.page_index, UNKNOWN, 0.0, signals, by="none")


def fill_from_context(decisions: list[Decision], scores: list[PageScore]) -> None:
    """Label weak pages from neighbours: a short unknown run between two pages of the same
    type joins them (statement continuation pages, a blank separator) unless a page's own
    best guess is a different type; otherwise an unknown
    page next to a segment joins it only when its own best guess is that type (Aadhaar back
    side after the front)."""
    n = len(decisions)
    i = 0
    while i < n:
        if decisions[i].doc_type is not UNKNOWN:
            i += 1
            continue
        j = i
        while j + 1 < n and decisions[j + 1].doc_type is UNKNOWN:
            j += 1
        left = decisions[i - 1] if i > 0 else None
        right = decisions[j + 1] if j + 1 < n else None
        if (
            left
            and right
            and left.doc_type == right.doc_type
            and left.doc_type in CONTINUABLE
            and j - i + 1 <= MAX_GAP
        ):
            # Only pages with no evidence, or evidence for the same type, are absorbed; a
            # page pointing elsewhere stays unknown so the VLM can look at it.
            neutral = all(scores[k].best_score == 0 or scores[k].best == left.doc_type for k in range(i, j + 1))
        else:
            neutral = False
        if neutral and left:
            conf = round(min(left.confidence, right.confidence) * CONTEXT_FACTOR, 3)
            for k in range(i, j + 1):
                _relabel(decisions[k], left.doc_type, conf, f"context: between two {left.doc_type.value} pages")
        i = j + 1

    # Best-guess adjacency, both directions so a run can grow from either end.
    for order in (range(n), range(n - 1, -1, -1)):
        step = 1 if order.step == 1 else -1
        for k in order:
            d, prev = decisions[k], k - step
            if d.doc_type is not UNKNOWN or not 0 <= prev < n:
                continue
            neighbour = decisions[prev]
            s = scores[k]
            if neighbour.doc_type is not UNKNOWN and s.best == neighbour.doc_type and s.best_score > 0:
                conf = round(neighbour.confidence * CONTEXT_FACTOR, 3)
                note = f"context: weak {s.best.value} evidence next to a {neighbour.doc_type.value} page"
                _relabel(d, neighbour.doc_type, conf, note, s.signal_labels(s.best))


def _relabel(d: Decision, doc_type: DocumentType, conf: float, note: str, extra: list[str] | None = None) -> None:
    d.doc_type, d.confidence, d.by = doc_type, conf, "context"
    d.signals = [note] + (extra or [])


def build_segments(decisions: list[Decision]) -> list[DocumentSegment]:
    """Consecutive pages with the same label form a segment; unknown runs get their own
    segment, so segments cover every page exactly once."""
    segments: list[DocumentSegment] = []
    run: list[Decision] = []
    for d in decisions + [None]:  # type: ignore[list-item]
        if run and (d is None or d.doc_type != run[0].doc_type):
            segments.append(
                DocumentSegment(
                    document_type=run[0].doc_type,
                    page_indexes=[r.page_index for r in run],
                    confidence=round(sum(r.confidence for r in run) / len(run), 3),
                )
            )
            run = []
        if d is not None:
            run.append(d)
    return segments


def dominant(decisions: list[Decision]) -> tuple[DocumentType, float]:
    """Type covering the most pages (ties: higher mean confidence) and its mean confidence."""
    by_type: dict[DocumentType, list[float]] = {}
    for d in decisions:
        if d.doc_type is not UNKNOWN:
            by_type.setdefault(d.doc_type, []).append(d.confidence)
    if not by_type:
        return UNKNOWN, 0.0
    doc_type, confs = max(by_type.items(), key=lambda kv: (len(kv[1]), sum(kv[1]) / len(kv[1])))
    return doc_type, round(sum(confs) / len(confs), 3)
