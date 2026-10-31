from fastapi import APIRouter, File, Form, UploadFile

from app.intake import UploadResult, default_engines, process_upload
from app.schemas import DocumentType

router = APIRouter(tags=["documents"])


@router.post("/documents", response_model=UploadResult)
def upload_document(
    file: UploadFile = File(...),
    sme_id: str = Form(..., min_length=1, max_length=64),
    document_type: DocumentType | None = Form(None),  # the slot the SME chose; a hint, not trusted
    password: str | None = Form(None),  # for password-protected PDFs (e-Aadhaar, bank statements)
) -> UploadResult:
    """One file -> ingest, classify, extract -> envelopes ready for /v1/assess.

    Always 200: `status` says whether the file could be opened (`password_required` asks for a password),
    `documents` holds what was read, `skipped` the parts we couldn't use and why. Nothing is stored.
    """
    data = file.file.read()
    ocr, vlm = default_engines()
    return process_upload(
        data, file.filename or "upload", sme_id=sme_id, expected_type=document_type,
        password=password or None, mime_type=file.content_type, ocr=ocr, vlm=vlm,
    )
