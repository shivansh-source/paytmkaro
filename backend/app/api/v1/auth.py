from fastapi import APIRouter, Depends, Header, HTTPException

from app.accounts import Account, AuthError, LoginRequest, LoginResponse, login
from app.api.deps import current_account, db
from app.storage import Database

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login_with_otp(body: LoginRequest, database: Database = Depends(db)) -> LoginResponse:
    """Mock OTP (123456) -> account (created on first login) + a session token for every other call."""
    try:
        return login(database, body)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@router.get("/auth/me", response_model=Account)
def me(account: Account = Depends(current_account)) -> Account:
    return account


@router.post("/auth/logout", status_code=204)
def logout(authorization: str | None = Header(None), database: Database = Depends(db)) -> None:
    if authorization:
        database.delete_session(authorization.removeprefix("Bearer ").strip())
