"""The lender JSON Schema (/schemas/v1/lender) is the source of truth; app.schemas.lender mirrors it.

These tests fail when the two drift apart: same fields, same required fields, same enum values, for
the record and every sub-object. Edit the JSON first, then mirror the change in lender.py.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.config import LENDERS_FILE
from app.schemas.lender import LenderProduct

LENDER_DIR = Path(__file__).resolve().parents[2] / "schemas" / "v1" / "lender"
JSON_SCHEMA = json.loads((LENDER_DIR / "lender_product.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((LENDER_DIR / "examples" / "lender_product.json").read_text(encoding="utf-8"))
RECORDS = json.loads(LENDERS_FILE.read_text(encoding="utf-8"))["products"]

PYDANTIC_SCHEMA = LenderProduct.model_json_schema()

# JSON $defs name -> Pydantic model name
DEFS = {
    "inrRange": "InrRange",
    "monthRange": "MonthRange",
    "numberRange": "NumberRange",
    "pricing": "Pricing",
    "amountTier": "AmountTier",
    "facilityTenure": "FacilityTenure",
    "constitutionRule": "ConstitutionRule",
    "charge": "Charge",
    "documentRequirement": "DocumentRequirement",
    "guarantee": "Guarantee",
    "margin": "Margin",
    "scoreThresholds": "ScoreThresholds",
    "condition": "Condition",
    "kfsRequirements": "KfsRequirements",
    "sourceRecord": "SourceRecord",
    "conflict": "Conflict",
}


def enum_values(node: dict, defs: dict) -> frozenset | None:
    """Allowed values of a property, following $ref / anyOf / items; None if unconstrained."""
    if "$ref" in node:
        return enum_values(defs[node["$ref"].split("/")[-1]], defs)
    if "enum" in node:
        return frozenset(node["enum"])
    if "const" in node:
        return frozenset([node["const"]])
    for key in ("anyOf", "oneOf"):
        if key in node:
            found = [v for sub in node[key] if (v := enum_values(sub, defs)) is not None]
            return frozenset().union(*found) if found else None
    if isinstance(node.get("items"), dict):
        return enum_values(node["items"], defs)
    return None


def shape(node: dict, defs: dict) -> dict:
    return {
        "fields": set(node.get("properties", {})),
        "required": set(node.get("required", [])),
        "enums": {name: enum_values(prop, defs) for name, prop in node.get("properties", {}).items()},
    }


def test_json_schema_itself_is_valid():
    Draft202012Validator.check_schema(JSON_SCHEMA)


def test_record_fields_match_json():
    assert shape(PYDANTIC_SCHEMA, PYDANTIC_SCHEMA["$defs"]) == shape(JSON_SCHEMA, JSON_SCHEMA["$defs"])


@pytest.mark.parametrize(("json_name", "model_name"), DEFS.items())
def test_sub_object_matches_json(json_name, model_name):
    assert shape(PYDANTIC_SCHEMA["$defs"][model_name], PYDANTIC_SCHEMA["$defs"]) == shape(
        JSON_SCHEMA["$defs"][json_name], JSON_SCHEMA["$defs"]
    )


def test_every_json_sub_object_is_mirrored():
    assert set(JSON_SCHEMA["$defs"]) == set(DEFS)


@pytest.mark.parametrize("record", [EXAMPLE, *RECORDS], ids=lambda r: r["id"])
def test_lender_records_pass_both_schemas(record):
    errors = [e.message for e in Draft202012Validator(JSON_SCHEMA).iter_errors(record)]
    assert not errors
    LenderProduct.model_validate(record)
