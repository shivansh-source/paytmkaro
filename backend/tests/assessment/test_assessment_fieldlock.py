"""Field lock, fairness and wording: no identifiers or protected attributes reach the model-facing table."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.assessment import REGISTRY, FeatureTable
from app.assessment.fieldlock import (
    PROTECTED_OR_PROXY_WORDS,
    FieldLockError,
    check_name,
    check_value,
    lock_features,
    words,
)
from assessment_support import card, dump, sensitive_strings

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "assessment"


@pytest.mark.parametrize("which", ["A", "B"])
def test_feature_table_contains_no_personal_identifiers(which):
    c = card(which)
    table = json.dumps(c.features.model_dump(mode="json"), ensure_ascii=False)
    for secret in sensitive_strings():
        assert secret.lower() not in table.lower(), secret
    # every non-null value is a number, a bool or a plain category token
    for name, value in c.features.features.items():
        check_value(name, value)


@pytest.mark.parametrize("which", ["A", "B"])
def test_whole_scorecard_leaks_no_identifiers_or_document_text(which):
    out = dump(card(which)).lower()
    for secret in sensitive_strings():
        assert secret.lower() not in out, secret


def test_gstin_pan_and_account_digits_are_absent_even_as_substrings():
    profile_pan = card("A").model_dump_json()
    assert not re.search(r"[A-Z]{5}[0-9]{4}[A-Z]", profile_pan)  # PAN shape
    assert not re.search(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", profile_pan)  # GSTIN shape
    assert not re.search(r"\b\d{10,}\b", profile_pan)  # long digit strings


def test_lock_rejects_unregistered_protected_and_identifier_columns():
    ids = [p.id for p in REGISTRY]
    with pytest.raises(FieldLockError):
        lock_features({"bc.foir": 0.2, "extra.column": 1}, ids)
    for bad in ("gender", "applicant_age", "dob", "promoter_pincode", "state_code", "religion", "caste_group", "gstin", "aadhaar_last4"):
        with pytest.raises(FieldLockError):
            check_name(bad)
    for bad in ("ABCPK1234F", "29ABCPK1234F1Z5", "UDYAM-KA-03-0001234", "123456789012", "1986-04-12", "Ravi Kumar", "a@b.co", "560004999"):
        with pytest.raises(FieldLockError):
            check_value("x", bad)
    for ok in (None, 3, 0.25, True, "pass", "micro", "proprietorship"):
        check_value("x", ok)
    with pytest.raises(FieldLockError):
        check_value("x", ["list"])
    with pytest.raises(ValueError):
        FeatureTable(features={"bc.foir": "RAVI KUMAR"})


def test_words_are_matched_by_token_not_substring():
    # "age" is inside vintage, average and coverage; "state" inside statement: these must NOT be flagged
    for fine in ("cp.vintage", "bc.statement_depth", "bc.liquidity_cushion", "di.statement_gaps", "bc.gst_registration_tenure"):
        check_name(fine)
    assert words("bc.low_balance_days") == {"bc", "low", "balance", "days"}


def test_registry_feature_names_carry_no_protected_attribute():
    for p in REGISTRY:
        assert not (words(p.id) & PROTECTED_OR_PROXY_WORDS), p.id
        check_name(p.id)
        assert not (words(p.name) & {"gender", "religion", "caste", "pincode", "state", "district"}), p.name


def test_registry_never_reads_protected_or_identifier_source_fields():
    forbidden_paths = (
        "SmeProfile.identity.address", "SmeProfile.identity.promoter_dob", "SmeProfile.identity.pan",
        "SmeProfile.identity.gstin", "SmeProfile.identity.legal_name", "SmeProfile.identity.trade_name",
        "SmeProfile.identity.udyam_number", "SmeProfile.identity.sector",
    )
    for p in REGISTRY:
        assert not p.field_path.startswith(forbidden_paths), p.id
        path = p.field_path.lower()
        assert "gender" not in path, p.id
        assert "dob" not in path or path.endswith(".status"), p.id  # only the status of the PAN-vs-Aadhaar check
    # features.py never touches a protected or identifier attribute (checked on attribute access, not prose)
    tree = ast.parse((PACKAGE / "features.py").read_text(encoding="utf-8"))
    touched = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not touched & {"dob", "gender", "promoter_dob", "address", "principal_address", "narration", "pincode", "state",
                          "district", "city", "pan", "gstin", "pan_number", "legal_name", "trade_name", "name", "account_holder_name"}


def test_review_flags_are_set_on_structural_parameters():
    flagged = {p.id for p in REGISTRY if p.review_flag}
    assert flagged == {"cp.constitution", "cp.msme_category", "bc.turnover_scale", "bc.cash_credit_share"}
    # and the warning travels with the score to the lender
    rows = {r.id: r for r in card("A").parameters}
    for pid in flagged:
        assert any(f.startswith("Fairness review:") for f in rows[pid].flags), pid


@pytest.mark.parametrize("which", ["A", "B"])
def test_output_makes_no_forbidden_claims(which):
    c = card(which)
    body = json.loads(dump(c))
    body.pop("disclaimer")  # the disclaimer names these words only to deny them
    text = json.dumps(body).lower()
    for word in ("probability", "approved", "approval", "rejected", "credit score", "default risk of"):
        assert word not in text, word
    assert "indicative" in c.disclaimer.lower() and "not a probability of default" in c.disclaimer


def test_package_does_not_carry_the_confidential_reference():
    banned = ("capscore", "capmob", "cap-15", "aecb", "ejari", "emirates", "muroor", "cbrb", "moody", "dubai", " uae", "aed ")
    for path in PACKAGE.rglob("*"):
        if path.suffix in (".py", ".md", ".json"):
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                assert word not in text, f"{word!r} in {path.name}"
