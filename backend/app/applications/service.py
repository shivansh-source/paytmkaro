"""Submitting applications and recording lender decisions."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from app.applications.models import (
    CONSENT_TEXT,
    DECLINE_REASON_TEXT,
    Application,
    ApplyRequest,
    Consent,
    Decision,
    DecisionRequest,
    Event,
)
from app.applications.store import ApplicationStore
from app import config
from app.schemas import DocumentEnvelope
from app.recommendation import evaluate, load_lender_products, match_input
from app.schemas.profile import LoanRequest
from app.scoring import assess


class ApplicationError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


DECIDABLE = {"submitted", "in_review", "info_requested"}


def _sentence(text: str | None) -> str:
    """Trim a free-text note and end it with a full stop, so messages read as sentences."""
    text = (text or "").strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def submit(store: ApplicationStore, body: ApplyRequest, *, documents: list[DocumentEnvelope] | None = None,
           at: datetime | None = None) -> Application:
    """`documents`: the SME's stored file (the route passes app.workspace.for_application). Only the demo
    seed omits it and uses body.documents."""
    if not body.consent_accepted:
        raise ApplicationError(422, "Consent is required to share your file with a lender")
    product = next((p for p in load_lender_products() if p.id == body.product_id), None)
    if product is None:
        raise ApplicationError(404, f"Unknown lender product '{body.product_id}'")

    # Recompute everything server-side: the lender only ever sees what our checks produced.
    assessment = assess(body.sme_id, documents if documents is not None else body.documents, bureau=body.bureau, sector=body.sector, as_of=body.as_of)
    request = LoanRequest(**{**body.request.model_dump(), "sme_id": body.sme_id})
    verdict = evaluate(match_input(assessment.profile, request), product)
    if verdict.status != "matched":
        raise ApplicationError(409, f"Not eligible for {product.lender} yet: {'; '.join(verdict.reasons[:2])}")

    at = at or _now()
    app = Application(
        id=f"APP-{uuid.uuid4().hex[:8].upper()}",
        status="submitted",
        submitted_at=at,
        updated_at=at,
        lender=product.lender,
        product_id=product.id,
        product=product.product,
        request=request,
        match=verdict,
        profile=assessment.profile,
        documents=assessment.documents,
        consent=Consent(text=CONSENT_TEXT.format(lender=product.lender), accepted_at=at),
        history=[Event(at=at, actor="msme", action="submitted", note=f"Applied for ₹{request.amount:,}")],
    )
    return store.save(app)


def decide(store: ApplicationStore, application_id: str, body: DecisionRequest) -> Application:
    app = store.get(application_id)
    if app is None:
        raise ApplicationError(404, f"No application '{application_id}'")
    now = _now()

    if body.action == "start_review":
        if app.status == "submitted":
            app = app.model_copy(update={"status": "in_review", "updated_at": now,
                                          "history": [*app.history, Event(at=now, actor="lender", action="review_started")]})
            store.save(app)
        return app

    if app.status not in DECIDABLE:
        raise ApplicationError(409, f"Application is already {app.status.replace('_', ' ')}")
    if body.action == "decline" and body.reason is None:
        raise ApplicationError(400, "A decline needs a reason, so the business knows what to change")
    if body.action == "request_info" and not (body.note or "").strip():
        raise ApplicationError(400, "Say what information you need")

    lender = app.lender
    note = _sentence(body.note)
    if body.action == "approve_in_principle":
        status, message = "approved_in_principle", f"{lender} has approved your loan in principle. They will contact you to complete the paperwork."
    elif body.action == "request_info":
        status, message = "info_requested", f"{lender} needs more information: {note}"
    else:
        status = "declined"
        message = f"{lender} can't offer this loan right now: {DECLINE_REASON_TEXT[body.reason]}."
        if note:
            message += f" Their note: {note}"
        message += " This is a 'not yet': your matches page shows what to change."

    decision = Decision(action=body.action, reason=body.reason, note=body.note, decided_at=now, message_for_msme=message)
    app = app.model_copy(update={
        "status": status,
        "updated_at": now,
        "decision": decision,
        "history": [*app.history, Event(at=now, actor="lender", action=body.action, note=body.note)],
    })
    return store.save(app)


def seed_demo(store: ApplicationStore) -> None:
    """Pre-filled inbox so the lender screen is never empty in a demo. SAMPLE data only.

    Seeded applications use their own business ids (SEED-*), so a live demo that loads sample applicant A
    or B on the MSME side starts with no applications and can apply for real."""
    if store.count():
        return
    from app.samples import AS_OF, BUREAU_A, BUREAU_B, applicant_a, applicant_b

    base = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
    plans = [
        ("SEED-A", applicant_a, BUREAU_A, "demo-bank-a-unsecured", 800_000, base),
        ("SEED-A", applicant_a, BUREAU_A, "demo-nbfc-b-flexi", 500_000, base + timedelta(hours=2)),
        ("SEED-B", applicant_b, BUREAU_B, "demo-nbfc-b-flexi", 500_000, base + timedelta(hours=5)),
    ]
    for sme_id, docs, bureau, product_id, amount, at in plans:
        submit(store, ApplyRequest(
            sme_id=sme_id, documents=docs(), bureau=bureau, sector="retail", as_of=AS_OF,
            request=LoanRequest(sme_id=sme_id, amount=amount, tenure_months=24, purpose="Working capital"),
            product_id=product_id, consent_accepted=True,
        ), at=at)


@lru_cache(maxsize=1)
def get_store() -> ApplicationStore:
    """The app-wide store on the shared database (app.storage.get_db). Seeds the demo inbox unless
    CREDITSETU_SEED=0 (tests)."""
    from app.storage import get_db

    store = ApplicationStore(get_db())
    if os.environ.get("CREDITSETU_SEED", "1" if config.SEED_DEMO else "0") == "1":
        seed_demo(store)
    return store
