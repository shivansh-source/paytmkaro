"""The v1 JSON schema files must agree with the pydantic field models (the source of truth).
Regenerate with: python -c "from app.documents.extract.schemas import write_schema_files; write_schema_files()"."""

import json

import pytest

from app.config import DOCUMENT_SCHEMAS_DIR
from app.documents.extract.prompts import FIELDS
from app.documents.extract.schemas import FIELD_MODELS, REQUIRED, SCHEMA_FILES, json_schema
from app.documents.models import DocumentType


@pytest.mark.parametrize("document_type", list(SCHEMA_FILES))
def test_schema_file_matches_models(document_type):
    on_disk = json.loads((DOCUMENT_SCHEMAS_DIR / SCHEMA_FILES[document_type]).read_text(encoding="utf-8"))
    assert on_disk == json_schema(document_type)
    assert on_disk["$schema"] == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize("document_type", list(SCHEMA_FILES))
def test_required_and_prompted_fields_exist_in_model(document_type):
    model_fields = set(FIELD_MODELS[document_type].model_fields)
    assert set(REQUIRED[document_type]) <= model_fields
    assert {k for k in FIELDS[document_type] if k not in {"periods", "accounts", "settlements", "<amount>"}} <= model_fields


def test_every_extractable_type_has_a_schema():
    assert set(SCHEMA_FILES) == set(DocumentType) - {DocumentType.UNKNOWN}
