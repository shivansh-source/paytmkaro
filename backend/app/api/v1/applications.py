from fastapi import APIRouter, HTTPException

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

router = APIRouter(tags=["applications"])


def _raise(e: ApplicationError):
    raise HTTPException(status_code=e.status_code, detail=e.message) from e


@router.post("/applications", response_model=Application, status_code=201)
def create_application(body: ApplyRequest) -> Application:
    """MSME applies to one lender product with explicit consent. The file is re-verified server-side."""
    try:
        return submit(get_store(), body)
    except ApplicationError as e:
        _raise(e)


@router.get("/applications", response_model=list[ApplicationSummary])
def list_applications(lender: str | None = None, sme_id: str | None = None) -> list[ApplicationSummary]:
    """A lender's inbox (`?lender=`) or one business's applications (`?sme_id=`)."""
    return [a.summary() for a in get_store().list(lender=lender, sme_id=sme_id)]


@router.get("/applications/{application_id}", response_model=Application)
def get_application(application_id: str) -> Application:
    app = get_store().get(application_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"No application '{application_id}'")
    return app


@router.post("/applications/{application_id}/decision", response_model=Application)
def decide_application(application_id: str, body: DecisionRequest) -> Application:
    """Lender action: start_review, approve_in_principle, request_info (note required), decline (reason required)."""
    try:
        return decide(get_store(), application_id, body)
    except ApplicationError as e:
        _raise(e)
