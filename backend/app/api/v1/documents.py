from fastapi import APIRouter, File, Form, UploadFile

from app.documents.process import ProcessResult, default_engines, process_upload
from app.schemas import DocumentType

router = APIRouter(tags=["documents"])


@router.post("/documents", response_model=ProcessResult)
def upload_document(
    file: UploadFile = File(...),
    sme_id: str = Form(..., min_length=1, max_length=64),
    document_type: DocumentType | None = Form(None),  # the slot the SME chose; a hint, not trusted
    password: str | None = Form(None),  # for password-protected PDFs (e-Aadhaar, bank statements)
) -> ProcessResult:
    """One file -> ingest, classify, extract -> envelopes ready for /v1/assess.

    Always 200: `status` is ok / nothing_recognised / password_required / unsupported_format / unreadable /
    too_large / error, with a user-facing `message`. `envelopes` holds what was read (status "failed" when a
    recognised document had nothing readable), `skipped` every unusable part with a reason, and `bureau` a
    score read from an uploaded bureau report (self-declared, unverified). Nothing is stored.
    """
    ocr, vlm = default_engines()
    return process_upload(
        file.file.read(), file.filename or "upload", sme_id=sme_id, password=password or None,
        expected_type=document_type, ocr=ocr, vlm=vlm,
    )
