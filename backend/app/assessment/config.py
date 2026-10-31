"""Weights, bands and policy for the assessment, loaded from config.json and validated.

Everything a credit team would want to tune lives in `config.json`, not in code:
- `parameters.<id>.weight` and `weight_source` ("placeholder" = our guess, "reference" = the weight
  documented in an internal lender reference scorecard; neither is calibrated for India)
- `parameters.<id>.bands`: ordered; the FIRST band that matches wins. A numeric band matches when
  `min <= value` and `value <= max` (either side optional; a band with neither is the catch-all and
  must be last). A categorical band matches when `value` equals the band's `value`.
- grade thresholds, the minimum coverage below which no grade is given, the confidence policy

`config_version` is copied into every ScoreCard so an output can be traced to the exact config.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import Schema

CONFIG_PATH = Path(__file__).with_name("config.json")


class Band(Schema):
    label: str  # plain-language phrase shown to the lender, e.g. "light existing EMI burden"
    points: float = Field(ge=0, le=100)
    min: float | None = None
    max: float | None = None
    value: str | None = None  # categorical band


class ParameterConfig(Schema):
    weight: float = Field(gt=0)
    weight_source: Literal["placeholder", "reference"]
    bands: list[Band] = []  # empty only for parameters that cannot be computed yet

    @model_validator(mode="after")
    def _bands_are_well_formed(self) -> ParameterConfig:
        if not self.bands:
            return self
        categorical = [b.value is not None for b in self.bands]
        if any(categorical):
            if not all(categorical):
                raise ValueError("a parameter's bands are either all categorical or all numeric")
            if any(b.min is not None or b.max is not None for b in self.bands):
                raise ValueError("categorical bands cannot carry min/max")
            if len({b.value for b in self.bands}) != len(self.bands):
                raise ValueError("duplicate categorical band value")
            return self
        last = self.bands[-1]
        if last.min is not None or last.max is not None:
            raise ValueError("the last numeric band must be a catch-all (no min, no max)")
        for b in self.bands:
            if b.min is not None and b.max is not None and b.min > b.max:
                raise ValueError(f"band '{b.label}' has min > max")
        return self


class GradeThreshold(Schema):
    grade: str
    min_index: float = Field(ge=0, le=100)


class CoverageLabel(Schema):
    label: str
    min_pct: float = Field(ge=0, le=100)


class ConfidencePolicy(Schema):
    unusable_below: float = Field(gt=0, lt=1)  # field confidence below this: parameter is not scored
    review_weight_factor: float = Field(gt=0, le=1)  # weight multiplier for inputs that need review
    table_row_share_review: float = Field(ge=0, le=1)  # share of low-confidence rows that flags a table
    table_row_share_unusable: float = Field(ge=0, le=1)


class AssessmentConfig(Schema):
    config_version: str
    calibrated: bool
    note: str
    grades: list[GradeThreshold]
    min_coverage_for_grade_pct: float = Field(ge=0, le=100)
    coverage_labels: list[CoverageLabel]
    critical_failure_grade_cap: str
    confidence: ConfidencePolicy
    parameters: dict[str, ParameterConfig]

    @model_validator(mode="after")
    def _policy_is_consistent(self) -> AssessmentConfig:
        mins = [g.min_index for g in self.grades]
        if mins != sorted(mins, reverse=True) or mins[-1] != 0:
            raise ValueError("grades must be listed best to worst and the last must start at 0")
        if self.critical_failure_grade_cap not in {g.grade for g in self.grades}:
            raise ValueError("critical_failure_grade_cap must be one of the grades")
        pcts = [c.min_pct for c in self.coverage_labels]
        if pcts != sorted(pcts, reverse=True) or pcts[-1] != 0:
            raise ValueError("coverage_labels must be listed high to low and the last must start at 0")
        return self


@lru_cache(maxsize=1)
def load_config() -> AssessmentConfig:
    return AssessmentConfig.model_validate(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))


def band_for(bands: list[Band], value: float | int | str | bool) -> Band:
    """First matching band. Raises if nothing matches (a config bug, never silently scored)."""
    for band in bands:
        if band.value is not None:
            if str(value) == band.value:
                return band
            continue
        v = float(value)
        if (band.min is None or v >= band.min) and (band.max is None or v <= band.max):
            return band
    raise ValueError(f"no band matches value {value!r}")
