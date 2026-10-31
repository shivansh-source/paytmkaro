"""Field lock: what may and may not reach the model-facing feature table (DPDP Act 2023 data minimisation).

The feature table is the only thing a scoring parameter sees. It is an ALLOWLIST: its keys must be
registry parameter ids, so a new column cannot appear by accident. On top of that this module rejects:

- keys whose words name a personal identifier or a protected / proxy attribute (gender, religion,
  caste, age and date of birth, pincode / state / district / city / address ...). Age is a lender
  ELIGIBILITY rule in the recommendation engine and is never scored here. Geography is not scored
  (redlining risk).
- values that look like an identifier: PAN, GSTIN, Udyam number, a long digit string (Aadhaar, account
  or phone number), an e-mail, or an ISO date (a date of birth would be one). Strings that remain are
  short lower_snake tokens such as "pass", "micro", "proprietorship".

Reasons shown to the lender are written from bands and statuses, never copied from document text, so
names and addresses cannot leak through them either (tested on the full ScoreCard JSON).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from app.schemas.common import GSTIN_RE, PAN_RE, UDYAM_RE

# Locked at the source: personal identifiers (never leave extraction/validation as scored inputs).
PERSONAL_IDENTIFIER_FIELDS = frozenset({
    "pan", "pan_number", "name", "legal_name", "trade_name", "father_name", "account_holder_name",
    "dob", "promoter_dob", "gstin", "aadhaar_last4", "account_number_last4", "ifsc", "udyam_number",
    "address", "principal_address", "acknowledgement_number", "phone", "email",
})
# Never scored: protected attributes and proxies for them.
PROTECTED_OR_PROXY_WORDS = frozenset({
    "gender", "sex", "religion", "caste", "community", "age", "dob", "birth", "nationality", "marital",
    "race", "ethnicity", "pincode", "pin", "state", "district", "city", "region", "location", "address",
})

KEY_IDENTIFIER_WORDS = frozenset({"gstin", "aadhaar", "ifsc", "phone", "email", "passport", "account"})

_SAFE_TOKEN =re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_DIGITS = re.compile(r"\d{8,}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}(-\d{2})?")
_EMAIL = re.compile(r"\S+@\S+")


class FieldLockError(ValueError):
    pass


def words(name: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", name.lower()) if w}


def check_name(name: str) -> None:
    # "name" and "pan" alone are fine in a key ("name_agreement" is a status); identifiers are caught by value.
    banned = words(name) & (PROTECTED_OR_PROXY_WORDS | KEY_IDENTIFIER_WORDS)
    if banned:
        raise FieldLockError(f"feature '{name}' names a locked or protected attribute: {sorted(banned)}")


def check_value(name: str, value: object) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if not isinstance(value, str):
        raise FieldLockError(f"feature '{name}' has a non-scalar value")
    text = value.strip()
    looks_like_id = (
        not _SAFE_TOKEN.match(text)
        or PAN_RE.match(text.upper())
        or GSTIN_RE.match(text.upper())
        or UDYAM_RE.match(text.upper())
        or _DIGITS.search(text)
        or _ISO_DATE.search(text)
        or _EMAIL.search(text)
    )
    if looks_like_id:
        raise FieldLockError(f"feature '{name}' has a value that is not a plain category token")


def lock_features(features: Mapping[str, object], allowed: Iterable[str]) -> dict[str, object]:
    """Return the table if every key is allowlisted and every key and value passes; else raise."""
    allowed = set(allowed)
    for name, value in features.items():
        if name not in allowed:
            raise FieldLockError(f"feature '{name}' is not a registered parameter")
        check_name(name)
        check_value(name, value)
    return dict(features)
