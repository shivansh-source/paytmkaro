"""DESIGN.md must not drift from the registry and config: counts, weights, sources, statuses, schema additions."""

from __future__ import annotations

import re
from pathlib import Path

from app.assessment import REGISTRY, load_config
from app.assessment.design_table import render_table

DESIGN = (Path(__file__).resolve().parents[2] / "app" / "assessment" / "DESIGN.md").read_text(encoding="utf-8")


def _summary() -> dict[str, int]:
    m = re.search(r"<!-- registry-summary (.*?) -->", DESIGN)
    assert m, "registry-summary marker missing"
    return {k: int(v) for k, v in (pair.split("=") for pair in m.group(1).split())}


def _rows() -> dict[str, list[str]]:
    rows = {}
    for line in DESIGN.splitlines():
        m = re.match(r"\| `([a-z]{2}\.[a-z0-9_]+)` \|", line)
        if m:
            rows[m.group(1)] = [c.strip() for c in line.strip().strip("|").split("|")]
    return rows


def test_summary_claims_match_registry_and_config():
    cfg, s = load_config(), _summary()
    pending = [p for p in REGISTRY if not p.computable]
    in_base = lambda p: p.in_total  # noqa: E731
    assert s["total"] == len(REGISTRY)
    assert s["computable"] == sum(p.computable for p in REGISTRY)
    assert s["pending"] == len(pending)
    assert s["total_weight"] == sum(cfg.parameters[p.id].weight for p in REGISTRY if in_base(p))
    assert s["computable_weight"] == sum(cfg.parameters[p.id].weight for p in REGISTRY if p.computable)
    assert s["pending_weight_in_base"] == sum(cfg.parameters[p.id].weight for p in pending if in_base(p))
    ref = [p for p in REGISTRY if cfg.parameters[p.id].weight_source == "reference"]
    assert s["reference_total"] == len(ref) == 11
    assert s["reference_total_weight"] == sum(cfg.parameters[p.id].weight for p in ref) == 18
    assert s["reference_computable"] == sum(p.computable for p in ref) == 3
    assert s["outside_weight_base"] == sum(not in_base(p) for p in REGISTRY) == 1
    assert s["total_weight"] == s["computable_weight"] + s["pending_weight_in_base"]


def test_table_has_one_row_per_parameter_with_matching_weight_and_status():
    cfg, rows = load_config(), _rows()
    assert set(rows) == {p.id for p in REGISTRY}
    for p in REGISTRY:
        cells = rows[p.id]
        weight, status, waits = cells[6], cells[7], cells[8]
        pc = cfg.parameters[p.id]
        assert weight.startswith(f"{pc.weight:g} ({pc.weight_source}"), p.id
        assert status.startswith("computable" if p.computable else "pending (schema)") or p.id.startswith("sp.itr"), p.id
        if not p.computable:
            assert waits == p.waits_for, p.id
        assert p.field_path in cells[3], p.id


def test_every_pending_parameter_is_covered_by_the_schema_additions_section():
    section = DESIGN.split("## 7. Schema additions to propose", 1)[1].split("\n## ", 1)[0]
    missing = [p.id for p in REGISTRY if not p.computable and f"`{p.id}`" not in section]
    assert missing == []


def test_design_states_placeholder_weights_and_non_goals():
    assert '"calibrated": false' in DESIGN or "calibrated" in DESIGN
    for phrase in ("placeholder", "Not a probability of default", "calibrat", "Field lock", "Limitations", "What we can honestly claim"):
        assert phrase in DESIGN, phrase
    placeholders = [p for p in REGISTRY if load_config().parameters[p.id].weight_source == "placeholder"]
    assert len(placeholders) == 40
    assert "All 40 weights not documented in the reference are placeholders" in DESIGN


def test_embedded_table_is_exactly_the_rendered_registry():
    start, end = "<!-- registry-table:start -->", "<!-- registry-table:end -->"
    block = DESIGN.split(start, 1)[1].split(end, 1)[0].strip()
    assert block == render_table()
