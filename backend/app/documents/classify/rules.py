"""Deterministic page scoring: evidence tables -> per-type scores -> label + confidence.

Confidence (computed here, never by a model):
    s1, s2     = best and second-best type scores (sum of signal weights)
    evidence   = 1 - exp(-s1 / EVIDENCE_SCALE)        # how much was found at all
    margin     = (s1 - s2) / s1                       # how clearly it beats the runner-up
    confidence = evidence * (0.5 + 0.5 * margin)
A page is labelled when s1 >= MIN_SCORE and confidence >= MIN_CONFIDENCE, else UNKNOWN.
E.g. one decisive form name (7) alone -> 0.83; two typical signals (2 + 2) -> 0.63;
strong evidence split evenly between two types -> ~0.5 or less.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.documents.classify.signals import FEATURES, KEYWORDS, extract_features
from app.documents.classify.text import PageText
from app.documents.models import DocumentType, Page

EVIDENCE_SCALE = 4.0
MIN_SCORE = 3.0
MIN_CONFIDENCE = 0.5
FUZZY_CREDIT = 0.8  # share of a keyword's weight earned by a fuzzy (not exact) match


@dataclass
class PageScore:
    page_index: int
    scores: dict[DocumentType, float] = field(default_factory=dict)
    signals: dict[DocumentType, list[tuple[float, str]]] = field(default_factory=dict)
    best: DocumentType = DocumentType.UNKNOWN
    best_score: float = 0.0
    confidence: float = 0.0  # confidence of `best`, even when not accepted
    accepted: bool = False
    has_image: bool = False

    @property
    def label(self) -> DocumentType:
        return self.best if self.accepted else DocumentType.UNKNOWN

    def signal_labels(self, doc_type: DocumentType) -> list[str]:
        return [label for _, label in sorted(self.signals.get(doc_type, []), key=lambda s: -s[0])]


def confidence_from_scores(s1: float, s2: float) -> float:
    if s1 <= 0:
        return 0.0
    evidence = 1 - math.exp(-s1 / EVIDENCE_SCALE)
    margin = (s1 - s2) / s1
    return round(evidence * (0.5 + 0.5 * margin), 3)


def _table_lines(page: Page) -> list[str]:
    return [" | ".join(cell.strip() for cell in row) for table in page.tables for row in table]


def ocr_rows(page: Page) -> list[str]:
    """Regroup OCR boxes into visual rows: boxes whose vertical centre falls inside the
    current row's span join it; each row is read left to right."""
    rows: list[tuple[float, float, list[tuple[float, str]]]] = []
    for line in sorted(page.ocr_lines, key=lambda l: (l.bbox[1] + l.bbox[3]) / 2):
        x0, y0, _, y1 = line.bbox
        centre = (y0 + y1) / 2
        if rows and rows[-1][0] <= centre <= rows[-1][1]:
            top, bottom, cells = rows[-1]
            cells.append((x0, line.text))
            rows[-1] = (min(top, y0), max(bottom, y1), cells)
        else:
            rows.append((y0, y1, [(x0, line.text)]))
    return ["  ".join(text for _, text in sorted(cells)) for _, _, cells in rows]


def score_page(page: Page) -> PageScore:
    table_lines = _table_lines(page)
    raw = page.text if not table_lines else page.text + "\n" + "\n".join(table_lines)
    result = PageScore(page_index=page.index, has_image=page.image_png is not None)
    if not raw.strip():
        return result

    text = PageText(raw)

    def add(doc_type: DocumentType, weight: float, label: str) -> None:
        result.scores[doc_type] = result.scores.get(doc_type, 0.0) + weight
        result.signals.setdefault(doc_type, []).append((weight, label + (" (counts against)" if weight < 0 else "")))

    for kw in KEYWORDS:
        quality, variant = kw.match(text)
        if quality == 1.0:
            add(kw.doc_type, kw.weight, f"text: '{variant}'")
        elif quality > 0:
            add(kw.doc_type, kw.weight * FUZZY_CREDIT, f"text~: '{variant}' (fuzzy {quality:.2f})")

    counts = extract_features(page.text, table_lines, ocr_rows(page))
    for feat in FEATURES:
        points = feat.score(counts.get(feat.name, 0))
        if points:
            add(feat.doc_type, points, feat.label.replace("{n}", str(counts[feat.name])))

    result.scores = {t: max(0.0, s) for t, s in result.scores.items()}
    ranked = sorted(result.scores.items(), key=lambda kv: -kv[1])
    if ranked:
        result.best, result.best_score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        result.confidence = confidence_from_scores(result.best_score, runner_up)
        result.accepted = result.best_score >= MIN_SCORE and result.confidence >= MIN_CONFIDENCE
    return result
