"""Encryption at rest (Fernet: AES-128-CBC + HMAC). One app secret, any length, stretched to a Fernet key."""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app import config

log = logging.getLogger(__name__)
DEV_SECRET = "creditsetu-local-development-only"  # never used when CREDITSETU_ENV=production


class SecretMissing(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    secret = config.CREDITSETU_SECRET
    if not secret:
        if config.CREDITSETU_ENV == "production":
            raise SecretMissing("Set CREDITSETU_SECRET: stored documents are encrypted with it")
        log.warning("CREDITSETU_SECRET is not set: using the development key (fine locally, never in production)")
        secret = DEV_SECRET
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken as exc:
        raise ValueError("Stored data could not be decrypted: CREDITSETU_SECRET changed?") from exc


def encrypt_text(text: str) -> str:
    return encrypt(text.encode()).decode()


def decrypt_text(token: str) -> str:
    return decrypt(token.encode()).decode()
