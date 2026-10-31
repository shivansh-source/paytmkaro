"""Shared helpers for the assessment tests: build the sample applicants' ScoreCards from the real pipeline."""

from __future__ import annotations

import json
from functools import lru_cache

from app.assessment import ScoreCard, score_sme
from app.samples import AS_OF, BUREAU_A, BUREAU_B, applicant_a, applicant_b
from app.scoring import assess


@lru_cache(maxsize=None)
def _assessed(which: str):
    docs, bureau = (applicant_a(), BUREAU_A) if which == "A" else (applicant_b(), BUREAU_B)
    return assess(f"SAMPLE-{which}", docs, bureau=bureau, sector="retail", as_of=AS_OF)


def pipeline(which: str):
    """(profile, validated documents) for applicant A or B. Treat as read-only; copy before editing."""
    a = _assessed(which)
    return a.profile, list(a.documents)


def card(which: str) -> ScoreCard:
    profile, docs = pipeline(which)
    return score_sme(profile, docs, as_of=AS_OF)


def by_id(c: ScoreCard) -> dict:
    return {r.id: r for r in c.parameters}


def dump(c: ScoreCard) -> str:
    return json.dumps(c.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


# Strings that identify the synthetic applicants; none may appear in the feature table or the ScoreCard.
def sensitive_strings() -> list[str]:
    out = ["RAVI", "KUMAR", "KUMAAR", "SAMPLE FATHER", "KUMAR STORES", "RAVI TRADERS", "Gandhi Bazaar", "Basavanagudi",
           "Bengaluru", "Karnataka", "560004", "4821", "7310", "SMPL0001234", "UDYAM-KA", "1986", "1990-09-03", "1986-04-12"]
    for which in ("A", "B"):
        profile, _ = pipeline(which)
        ident = profile.identity
        out += [ident.pan.value, ident.gstin.value, ident.udyam_number.value]
    return out
