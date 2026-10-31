"""Where uploaded files live: Supabase Storage in production, a local folder otherwise. Always encrypted."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

import httpx

from app import config
from app.storage.crypto import decrypt, encrypt

log = logging.getLogger(__name__)


class FileStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes | None: ...
    def delete(self, key: str) -> None: ...


class LocalFileStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Bad file key")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encrypt(data))

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return decrypt(path.read_bytes()) if path.exists() else None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class SupabaseFileStore:
    """Private bucket via the Storage REST API, with the service key (server-side only)."""

    def __init__(self, url: str, service_key: str, bucket: str):
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        r = httpx.post(f"{self.base}/bucket", headers=self.headers, json={"id": self.bucket, "name": self.bucket, "public": False}, timeout=20)
        if r.status_code not in (200, 201, 400, 409):  # 400/409: already exists
            log.warning("Supabase bucket check failed: HTTP %s", r.status_code)

    def put(self, key: str, data: bytes) -> None:
        r = httpx.post(
            f"{self.base}/object/{self.bucket}/{key}", content=encrypt(data), timeout=60,
            headers={**self.headers, "Content-Type": "application/octet-stream", "x-upsert": "true"},
        )
        r.raise_for_status()

    def get(self, key: str) -> bytes | None:
        r = httpx.get(f"{self.base}/object/{self.bucket}/{key}", headers=self.headers, timeout=60)
        if r.status_code in (400, 404):
            return None
        r.raise_for_status()
        return decrypt(r.content)

    def delete(self, key: str) -> None:
        httpx.request("DELETE", f"{self.base}/object/{self.bucket}", headers=self.headers, json={"prefixes": [key]}, timeout=20)


def make_file_store() -> FileStore:
    if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
        return SupabaseFileStore(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY, config.SUPABASE_BUCKET)
    return LocalFileStore(Path(os.environ.get("CREDITSETU_UPLOADS", config.UPLOADS_DIR)))  # read late: tests point it
