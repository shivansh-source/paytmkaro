"""Accounts and sessions. Login is a mock OTP (hackathon), but sessions are real: a random bearer token,
stored only as a hash, that every MSME and lender endpoint checks. One business can't read another's file."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app import config
from app.recommendation import load_lender_products
from app.storage import Database

DEMO_OTP = "123456"
Role = Literal["msme", "lender"]


class LoginRequest(BaseModel):
    role: Role
    name: str = Field(min_length=1, max_length=200)
    organisation: str = Field(min_length=1, max_length=200)
    mobile: str = Field(pattern=r"^[6-9][0-9]{9}$")
    otp: str


class Account(BaseModel):
    id: str  # an MSME's id is its sme_id: SME-<mobile>
    role: Role
    name: str
    organisation: str
    mobile: str


class LoginResponse(BaseModel):
    token: str
    account: Account


class AuthError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code, self.message = status_code, message


def account_id(role: Role, mobile: str) -> str:
    return f"{'SME' if role == 'msme' else 'LENDER'}-{mobile}"


def login(db: Database, body: LoginRequest) -> LoginResponse:
    if body.otp != DEMO_OTP:
        raise AuthError(401, "That code doesn't match. For the demo, use 123456.")
    organisation = body.organisation.strip()
    if body.role == "lender" and organisation not in {p.lender for p in load_lender_products()}:
        raise AuthError(400, "Choose your institution from the list")
    row = db.upsert_account(account_id=account_id(body.role, body.mobile), role=body.role, mobile=body.mobile,
                            name=body.name.strip(), organisation=organisation)
    token = secrets.token_urlsafe(32)
    db.create_session(row["id"], token, datetime.now(timezone.utc) + timedelta(days=config.SESSION_DAYS))
    return LoginResponse(token=token, account=Account(**{k: row[k] for k in Account.model_fields}))


def account_for(db: Database, token: str | None) -> Account | None:
    row = db.account_for_token(token) if token else None
    return Account(**{k: row[k] for k in Account.model_fields}) if row else None


__all__ = ["DEMO_OTP", "Account", "AuthError", "LoginRequest", "LoginResponse", "account_for", "account_id", "login"]
