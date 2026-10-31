from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from app.questionnaire import Answers, Prequalification, prequalify
from app.questionnaire.understand import InterpretRequest, Interpretation, interpret

router = APIRouter(tags=["questionnaire"])


class PrequalifyRequest(BaseModel):
    answers: Answers
    as_of: date | None = None  # defaults to today; fixed in tests


@router.post("/prequalify", response_model=Prequalification)
def prequalify_answers(body: PrequalifyRequest) -> Prequalification:
    """Self-declared answers -> estimates, a 'likely lenders' preview and a personalised document checklist."""
    return prequalify(body.answers, body.as_of)


@router.post("/questionnaire/interpret", response_model=Interpretation)
def interpret_answer(body: InterpretRequest) -> Interpretation:
    """A free-typed answer (English / Hindi / Hinglish) -> validated answer fields. Rules first, then Sarvam."""
    return interpret(body)
