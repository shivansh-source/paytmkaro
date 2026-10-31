"""Who is calling: the bearer token from POST /v1/auth/login, checked against the sessions table."""

from fastapi import Depends, Header, HTTPException

from app.accounts import Account, account_for
from app.storage import Database, get_db


def db() -> Database:
    return get_db()


def current_account(authorization: str | None = Header(None), database: Database = Depends(db)) -> Account:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    account = account_for(database, token)
    if account is None:
        raise HTTPException(status_code=401, detail="Please sign in again")
    return account


def current_msme(account: Account = Depends(current_account)) -> Account:
    if account.role != "msme":
        raise HTTPException(status_code=403, detail="This is for business accounts")
    return account


def current_lender(account: Account = Depends(current_account)) -> Account:
    if account.role != "lender":
        raise HTTPException(status_code=403, detail="This is for lender accounts")
    return account
