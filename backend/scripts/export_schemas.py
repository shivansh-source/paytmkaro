"""Write JSON Schema + example files for the MSME contracts into /schemas/v1/msme.

Run from backend/:  python -m scripts.export_schemas
tests/schemas/test_msme_schemas.py fails if the committed files are out of date.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from app.schemas import (
    Aadhaar,
    BankStatement,
    BureauReport,
    DocumentEnvelope,
    FinancialStatements,
    GstRegistration,
    Gstr3b,
    ItrV,
    LoanRequest,
    PanCard,
    SanctionLetter,
    SettlementReport,
    SmeProfile,
    Udyam,
)
from app.schemas.examples import (
    example_bank_statement_envelope,
    example_loan_request,
    example_pan_envelope,
    example_sme_profile,
)

OUT_DIR = Path(__file__).resolve().parents[2] / "schemas" / "v1" / "msme"

MODELS: dict[str, type[BaseModel]] = {
    "document_envelope": DocumentEnvelope,
    "sme_profile": SmeProfile,
    "loan_request": LoanRequest,
    # Per-document schemas, e.g. for VLM prompts and extractor output.
    "documents/pan_card": PanCard,
    "documents/aadhaar": Aadhaar,
    "documents/gst_registration": GstRegistration,
    "documents/gstr3b": Gstr3b,
    "documents/bank_statement": BankStatement,
    "documents/udyam": Udyam,
    "documents/itr_v": ItrV,
    "documents/bureau_report": BureauReport,
    "documents/financial_statements": FinancialStatements,
    "documents/sanction_letter": SanctionLetter,
    "documents/settlement_report": SettlementReport,
}

EXAMPLES = {
    "examples/pan_card.envelope": example_pan_envelope,
    "examples/bank_statement.envelope": example_bank_statement_envelope,
    "examples/sme_profile": example_sme_profile,
    "examples/loan_request": example_loan_request,
}


def render() -> dict[Path, str]:
    """Everything the exporter writes, keyed by path. Shared with the freshness test."""
    files: dict[Path, str] = {}
    for name, model in MODELS.items():
        schema = model.model_json_schema(mode="serialization")
        schema["$id"] = f"creditsetu/msme/v1/{name}"
        files[OUT_DIR / f"{name}.schema.json"] = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    for name, build in EXAMPLES.items():
        files[OUT_DIR / f"{name}.json"] = build().model_dump_json(indent=2) + "\n"
    return files


def main() -> None:
    for path, text in render().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(path.relative_to(OUT_DIR.parents[2]))


if __name__ == "__main__":
    main()
