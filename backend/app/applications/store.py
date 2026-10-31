"""Applications on the shared database (app.storage): one row per application, the body encrypted."""

from __future__ import annotations

from app.applications.models import Application
from app.storage import Database


class ApplicationStore:
    def __init__(self, db: Database):
        self.db = db

    def save(self, app: Application) -> Application:
        self.db.save_application(app_id=app.id, lender=app.lender, sme_id=app.profile.sme_id, status=app.status,
                                 submitted_at=app.submitted_at, body_json=app.model_dump_json())
        return app

    def get(self, application_id: str) -> Application | None:
        body = self.db.get_application(application_id)
        return Application.model_validate_json(body) if body else None

    def list(self, *, lender: str | None = None, sme_id: str | None = None) -> list[Application]:
        return [Application.model_validate_json(b) for b in self.db.list_applications(lender=lender, sme_id=sme_id)]

    def count(self) -> int:
        return self.db.count_applications()
