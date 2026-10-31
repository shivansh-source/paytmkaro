from fastapi import APIRouter, Depends, HTTPException

from app import workspace
from app.accounts import Account
from app.api.deps import current_account, current_lender, current_msme, db
from app.applications import (
    Application,
    ApplicationError,
    ApplicationSummary,
    ApplyRequest,
    DecisionRequest,
    decide,
    get_store,
    submit,
)
from app.storage import Database

router = APIRouter(tags=["applications"])


def _raise(status_code: int, message: str):
    raise HTTPException(status_code=status_code, detail=message)


def _visible(app: Application, account: Account) -> bool:
    return app.profile.sme_id == account.id if account.role == "msme" else app.lender == account.organisation


@router.post("/applications", response_model=Application, status_code=201)
def create_application(body: ApplyRequest, account: Account = Depends(current_msme), database: Database = Depends(db)) -> Application:
    """MSME applies to one lender product with explicit consent. Built from the SME's stored documents and
    re-verified server-side; only the SME's own confirmations come from the request."""
    body = body.model_copy(update={"sme_id": account.id})
    try:
        documents = workspace.for_application(database, account.id, body.documents)
        return submit(get_store(), body, documents=documents)
    except (ApplicationError, workspace.WorkspaceError) as e:
        _raise(e.status_code, e.message)


@router.get("/applications", response_model=list[ApplicationSummary])
def list_applications(account: Account = Depends(current_account)) -> list[ApplicationSummary]:
    """A lender sees its own inbox; a business sees its own applications."""
    if account.role == "lender":
        apps = get_store().list(lender=account.organisation)
    else:
        apps = get_store().list(sme_id=account.id)
    return [a.summary() for a in apps]


@router.get("/applications/{application_id}", response_model=Application)
def get_application(application_id: str, account: Account = Depends(current_account)) -> Application:
    app = get_store().get(application_id)
    if app is None or not _visible(app, account):
        _raise(404, f"No application '{application_id}'")
    return app


@router.post("/applications/{application_id}/decision", response_model=Application)
def decide_application(application_id: str, body: DecisionRequest, account: Account = Depends(current_lender)) -> Application:
    """Lender action: start_review, approve_in_principle, request_info (note required), decline (reason required)."""
    app = get_store().get(application_id)
    if app is None or not _visible(app, account):
        _raise(404, f"No application '{application_id}'")
    try:
        return decide(get_store(), application_id, body)
    except ApplicationError as e:
        _raise(e.status_code, e.message)
