"""An MSME's server-side file: its uploaded documents (encrypted) and dashboard progress.

Applications are built from what is stored here, never from what a browser sends: the browser may only add
the SME's own "yes, that's me / that's right" confirmations (`user_confirmed`) to stored fields.
"""

from __future__ import annotations

import json
from typing import Any

from app.documents.process import ProcessResult
from app.schemas import DocumentEnvelope, DocumentType, Extracted
from app.storage import Database


class WorkspaceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code, self.message = status_code, message


def documents(db: Database, sme_id: str) -> list[DocumentEnvelope]:
    return [DocumentEnvelope.model_validate_json(body) for body in db.list_documents(sme_id)]


def store_upload(db: Database, sme_id: str, data: bytes, result: ProcessResult) -> list[DocumentEnvelope]:
    """Keep the file (encrypted) and every usable envelope. A new document replaces older ones of the same
    type, except GSTR-3B, whose months add up across uploads."""
    usable = [e for e in result.envelopes if e.status != "failed"]
    if not usable:
        return []
    file_key = f"{sme_id}/{result.sha256 or usable[0].file.sha256}"
    db.files.put(file_key, data)
    replaced = {e.document_type for e in usable if e.document_type != DocumentType.GSTR3B}
    stale = [d.document_id for d in documents(db, sme_id) if d.document_type in replaced]
    stale = [i for i in stale if i not in {e.document_id for e in usable}]
    if stale:
        db.delete_documents(sme_id, stale)
    for env in usable:
        env = env.model_copy(update={"sme_id": sme_id})
        db.save_document(env.model_dump_json(), document_id=env.document_id, sme_id=sme_id,
                         document_type=env.document_type.value, uploaded_at=env.uploaded_at, file_key=file_key)
    return usable


def replace_with(db: Database, sme_id: str, envelopes: list[DocumentEnvelope]) -> list[DocumentEnvelope]:
    """Start the file over with these documents (a sample applicant): ids and owner rewritten to this SME."""
    db.delete_documents(sme_id)
    stored = []
    for env in envelopes:
        suffix = env.document_id.split("-", 2)[-1]
        env = env.model_copy(update={"sme_id": sme_id, "document_id": f"{sme_id.lower()}-{suffix}"})
        db.save_document(env.model_dump_json(), document_id=env.document_id, sme_id=sme_id,
                         document_type=env.document_type.value, uploaded_at=env.uploaded_at, file_key=None)
        stored.append(env)
    return stored


def _confirmed_fields(env: DocumentEnvelope) -> set[str]:
    data = env.data
    if data is None:
        return set()
    return {name for name in type(data).model_fields if isinstance(getattr(data, name), Extracted) and getattr(data, name).user_confirmed}


def for_application(db: Database, sme_id: str, submitted: list[DocumentEnvelope]) -> list[DocumentEnvelope]:
    """The stored documents, with the SME's confirmations carried over from what the browser sent."""
    stored = documents(db, sme_id)
    if not stored:
        raise WorkspaceError(409, "Upload your documents (or load a sample applicant) before applying")
    confirmed = {e.document_id: _confirmed_fields(e) for e in submitted}
    out = []
    for env in stored:
        names = confirmed.get(env.document_id, set())
        if names and env.data is not None:
            updates = {n: getattr(env.data, n).model_copy(update={"user_confirmed": True}) for n in names
                       if isinstance(getattr(env.data, n, None), Extracted)}
            env = env.model_copy(update={"data": env.data.model_copy(update=updates)})
        out.append(env)
    return out


MAX_PROGRESS_BYTES = 2_000_000  # the dashboard state: answers, request, last assessment and matches


def save_progress(db: Database, sme_id: str, state: dict[str, Any]) -> None:
    text = json.dumps(state)
    if len(text) > MAX_PROGRESS_BYTES:
        raise WorkspaceError(413, "Progress is too large to save")
    db.save_progress(sme_id, text)


def get_progress(db: Database, sme_id: str) -> dict[str, Any] | None:
    text = db.get_progress(sme_id)
    return json.loads(text) if text else None
