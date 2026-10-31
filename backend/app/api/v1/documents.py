from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.accounts import Account
from app.api.deps import current_msme, db
from app.documents.process import ProcessResult, default_engines, process_upload
from app.schemas import DocumentEnvelope, DocumentType
from app.storage import Database
from app import workspace

router = APIRouter(tags=["documents"])


@router.post("/documents", response_model=ProcessResult)
def upload_document(
    file: UploadFile = File(...),
    document_type: DocumentType | None = Form(None),  # the slot the SME chose; a hint, not trusted
    password: str | None = Form(None),  # for password-protected PDFs (e-Aadhaar, bank statements)
    account: Account = Depends(current_msme),
    database: Database = Depends(db),
) -> ProcessResult:
    """One file -> ingest, classify, extract -> envelopes, stored (encrypted) in the SME's file.

    Always 200: `status` is ok / nothing_recognised / password_required / unsupported_format / unreadable /
    too_large / error, with a user-facing `message`. `envelopes` holds what was read (status "failed" when a
    recognised document had nothing readable), `skipped` every unusable part with a reason, and `bureau` a
    score read from an uploaded bureau report (self-declared, unverified).
    """
    data = file.file.read()
    ocr, vlm = default_engines()
    result = process_upload(data, file.filename or "upload", sme_id=account.id, password=password or None,
                            expected_type=document_type, ocr=ocr, vlm=vlm)
    if result.status == "ok":
        workspace.store_upload(database, account.id, data, result)
    return result


@router.get("/documents", response_model=list[DocumentEnvelope])
def list_documents(account: Account = Depends(current_msme), database: Database = Depends(db)) -> list[DocumentEnvelope]:
    """The SME's stored documents (what applications are built from)."""
    return workspace.documents(database, account.id)


@router.delete("/documents", status_code=204)
def clear_documents(account: Account = Depends(current_msme), database: Database = Depends(db)) -> None:
    """Start over: removes every stored document and file."""
    database.delete_documents(account.id)


@router.get("/progress")
def get_progress(account: Account = Depends(current_msme), database: Database = Depends(db)) -> dict[str, Any] | None:
    """The dashboard state saved from another device or session, or null."""
    return workspace.get_progress(database, account.id)


@router.put("/progress", status_code=204)
def put_progress(state: dict[str, Any], account: Account = Depends(current_msme), database: Database = Depends(db)) -> None:
    try:
        workspace.save_progress(database, account.id, state)
    except workspace.WorkspaceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
