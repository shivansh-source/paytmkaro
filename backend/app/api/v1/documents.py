from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["documents"])


class DocumentUploadRequest(BaseModel):
    sme_id: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    file_name: str = Field(min_length=1)


class DocumentUploadResponse(BaseModel):
    job_id: str
    status: Literal["queued"]
    next_step: str


@router.post("/documents", response_model=DocumentUploadResponse)
def create_document_upload(request: DocumentUploadRequest) -> DocumentUploadResponse:
    return DocumentUploadResponse(
        job_id=f"job-{request.sme_id}-{request.document_type}",
        status="queued",
        next_step="Run extraction + cross-document checks asynchronously",
    )
