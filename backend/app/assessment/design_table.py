"""Render the parameter registry as the markdown table embedded in DESIGN.md.

DESIGN.md holds the output between the `registry-table` markers and a test compares it with `render_table()`,
so the document cannot drift from registry.py and config.json. To refresh it after a change:

    python -m app.assessment.design_table   # prints the table; paste between the markers
"""

from __future__ import annotations

from app.assessment.config import ParameterConfig, load_config
from app.assessment.registry import REGISTRY, Parameter

HEADER = (
    "| id | category | India source documents | input field | formula | bands (value=points) | weight | status today | waits for |\n"
    "|---|---|---|---|---|---|---|---|---|"
)


def _bands(pc: ParameterConfig) -> str:
    out = []
    for b in pc.bands:
        if b.value is not None:
            out.append(f"{b.value}={b.points:g}")
        elif b.min is not None and b.max is not None:
            out.append(f"{b.min:g}-{b.max:g}={b.points:g}")
        elif b.min is not None:
            out.append(f">={b.min:g}={b.points:g}")
        elif b.max is not None:
            out.append(f"<={b.max:g}={b.points:g}")
        else:
            out.append(f"else={b.points:g}")
    return "; ".join(out) or "not defined until computable"


def _status(p: Parameter) -> str:
    if p.id.startswith("sp.itr"):
        return "computable when ITR-V uploaded"
    status = "computable" if p.computable else "pending (schema)"
    return status + ("; not applicable if not a trading business" if p.applies else "")


def render_table() -> str:
    cfg = load_config()
    rows = [HEADER]
    for p in REGISTRY:
        pc = cfg.parameters[p.id]
        weight = f"{pc.weight:g} ({pc.weight_source}{'; outside weight base' if not p.in_total else ''})"
        rows.append(
            f"| `{p.id}` | {p.category} | {p.documents} | `{p.field_path}` | {p.formula} | {_bands(pc)} | {weight} | {_status(p)} | {p.waits_for or ''} |"
        )
    return "\n".join(rows)


if __name__ == "__main__":
    print(render_table())
