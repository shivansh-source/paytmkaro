"""Output contracts of the assessment: ParameterResult, Coverage, ScoreCard.

Every registry parameter appears in `ScoreCard.parameters` (the "null column" principle):
- computed: has value, band, points (0-100) and evidence
- pending: could not be computed; `reason` says why and `waits_for` names the exact field or document
- not_applicable: does not apply to this business (e.g. warehouse for a service firm); excluded from the
  weight base and said so

The index is an INDICATIVE number for a lender, who makes the credit decision. It is not a probability of
default, not approval odds and not a bureau score.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from app.assessment.fieldlock import lock_features
from app.schemas.common import EvidenceRef, Schema

ParameterStatus = Literal["computed", "pending", "not_applicable"]
Scalar = float | int | str | bool

DISCLAIMER = (
    "Indicative assessment of an SME's credit-relevant signals, computed by fixed rules from the documents "
    "provided. It is not a credit decision, not a probability of default and not a bureau score. The lender "
    "makes the credit decision. Weights are uncalibrated placeholders until a lender validates them against "
    "its own outcomes. Read the index together with the coverage figure."
)


class ParameterResult(Schema):
    id: str
    name: str
    category: str
    status: ParameterStatus
    weight: float  # nominal weight from config
    weight_source: Literal["placeholder", "reference"]
    effective_weight: float = 0  # weight actually used: 0 unless computed; halved for inputs needing review
    in_total: bool = True  # False: shown for completeness but outside the weight base
    value: Scalar | None = None
    value_display: str | None = None
    band: str | None = None
    points: float | None = None  # 0-100
    evidence: list[EvidenceRef] = []
    reason: str  # plain language, written from the band or the pending reason, never copied from documents
    waits_for: str | None = None  # pending: the exact field or document this parameter needs
    low_confidence: bool = False
    flags: list[str] = []


class Coverage(Schema):
    total_weight: float  # all parameters inside the weight base
    applicable_weight: float  # total minus not_applicable
    computed_weight: float  # nominal weight of computed parameters
    effective_weight: float  # what the index is actually averaged over
    coverage_pct: float  # effective_weight / applicable_weight
    label: str
    computed_count: int
    pending_count: int
    not_applicable_count: int


class CategorySummary(Schema):
    category: str
    index: float | None
    coverage_pct: float
    computed_count: int
    pending_count: int


class MissingInput(Schema):
    parameter: str
    weight: float
    waits_for: str


class FeatureTable(Schema):
    """The model-facing table: one column per registry parameter, null when pending. Field-locked."""

    features: dict[str, Scalar | None]

    @model_validator(mode="after")
    def _locked(self) -> FeatureTable:
        lock_features(self.features, self.features.keys())
        return self


class ScoreCard(Schema):
    sme_id: str
    as_of: date
    config_version: str
    weights_calibrated: bool
    index: float | None = Field(default=None, ge=0, le=100)
    grade: str  # strong | moderate | cautious | weak | insufficient_data
    grade_capped_by: list[str] = []  # critical parameters that capped the grade
    provisional: bool  # True when the index rests on unconfirmed or unverified inputs
    provisional_reasons: list[str] = []
    coverage: Coverage
    categories: list[CategorySummary]
    strengths: list[str] = []
    concerns: list[str] = []
    biggest_missing_inputs: list[MissingInput] = []
    parameters: list[ParameterResult]
    features: FeatureTable
    disclaimer: str = DISCLAIMER
