"""The database: Supabase Postgres in production, SQLite locally and in tests. SQLAlchemy Core, five tables.

Columns that are only used to look rows up (ids, mobile, lender, status) are plain; everything personal
(extracted documents, dashboard progress, applications) is one encrypted JSON blob per row. Uploaded file
bytes are not in the database: they live in the file store under `documents.file_key`.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, UniqueConstraint, create_engine, delete, func, insert, select, text, update
from sqlalchemy.engine import Engine

from app import config
from app.storage.crypto import decrypt_text, encrypt_text
from app.storage.files import FileStore, make_file_store

metadata = MetaData()

accounts = Table(
    "accounts", metadata,
    Column("id", String(64), primary_key=True),  # SME-<mobile> / LENDER-<mobile>; SME ids are the sme_id everywhere
    Column("role", String(16), nullable=False),
    Column("mobile", String(16), nullable=False),
    Column("name", String(200), nullable=False),
    Column("organisation", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("role", "mobile"),
)
sessions = Table(
    "sessions", metadata,
    Column("token_hash", String(64), primary_key=True),  # sha256 of the bearer token; the token itself is never stored
    Column("account_id", String(64), nullable=False, index=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)
documents = Table(
    "documents", metadata,
    Column("id", String(128), primary_key=True),  # envelope document_id
    Column("sme_id", String(64), nullable=False, index=True),
    Column("document_type", String(32), nullable=False),
    Column("uploaded_at", DateTime(timezone=True), nullable=False),
    Column("file_key", String(256)),  # None for sample documents (no file)
    Column("body", Text, nullable=False),  # encrypted DocumentEnvelope JSON
)
progress = Table(
    "progress", metadata,
    Column("sme_id", String(64), primary_key=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("body", Text, nullable=False),  # encrypted dashboard state JSON
)
applications = Table(
    "applications", metadata,
    Column("id", String(32), primary_key=True),
    Column("lender", String(200), nullable=False, index=True),
    Column("sme_id", String(64), nullable=False, index=True),
    Column("status", String(32), nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=False),
    Column("body", Text, nullable=False),  # encrypted Application JSON
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)  # SQLite drops the zone


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def database_url() -> str:
    """DATABASE_URL (Postgres) wins; else SQLite at CREDITSETU_DB (read at call time so tests can point it)."""
    if config.DATABASE_URL:
        url = config.DATABASE_URL
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    path = Path(os.environ.get("CREDITSETU_DB", config.SQLITE_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


class Database:
    def __init__(self, engine: Engine, files: FileStore):
        self.engine = engine
        self.files = files
        metadata.create_all(engine)
        if engine.dialect.name == "postgresql":
            self._lock_public_api()

    def _lock_public_api(self) -> None:
        """Supabase exposes every table in `public` through its REST API with the public anon key. Row Level
        Security with no policies shuts that door; this backend connects as the table owner and is not affected."""
        with self.engine.begin() as db:
            for table in metadata.sorted_tables:
                db.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))

    # ---- accounts and sessions ----

    def upsert_account(self, *, account_id: str, role: str, mobile: str, name: str, organisation: str) -> dict:
        with self.engine.begin() as db:
            row = db.execute(select(accounts).where(accounts.c.id == account_id)).mappings().first()
            if row is None:
                db.execute(insert(accounts).values(id=account_id, role=role, mobile=mobile, name=name,
                                                   organisation=organisation, created_at=_now()))
            else:
                db.execute(update(accounts).where(accounts.c.id == account_id).values(name=name, organisation=organisation))
            return dict(db.execute(select(accounts).where(accounts.c.id == account_id)).mappings().one())

    def create_session(self, account_id: str, token: str, expires_at: datetime) -> None:
        with self.engine.begin() as db:
            db.execute(insert(sessions).values(token_hash=token_hash(token), account_id=account_id, expires_at=expires_at))

    def account_for_token(self, token: str) -> dict | None:
        with self.engine.begin() as db:
            row = db.execute(select(sessions).where(sessions.c.token_hash == token_hash(token))).mappings().first()
            if row is None or _aware(row["expires_at"]) < _now():
                return None
            account = db.execute(select(accounts).where(accounts.c.id == row["account_id"])).mappings().first()
            return dict(account) if account else None

    def delete_session(self, token: str) -> None:
        with self.engine.begin() as db:
            db.execute(delete(sessions).where(sessions.c.token_hash == token_hash(token)))

    # ---- documents ----

    def save_document(self, envelope_json: str, *, document_id: str, sme_id: str, document_type: str,
                      uploaded_at: datetime, file_key: str | None) -> None:
        body = encrypt_text(envelope_json)
        with self.engine.begin() as db:
            db.execute(delete(documents).where(documents.c.id == document_id))
            db.execute(insert(documents).values(id=document_id, sme_id=sme_id, document_type=document_type,
                                                uploaded_at=uploaded_at, file_key=file_key, body=body))

    def list_documents(self, sme_id: str) -> list[str]:
        with self.engine.begin() as db:
            rows = db.execute(select(documents.c.body).where(documents.c.sme_id == sme_id).order_by(documents.c.uploaded_at)).all()
        return [decrypt_text(r[0]) for r in rows]

    def get_document(self, sme_id: str, document_id: str) -> str | None:
        with self.engine.begin() as db:
            row = db.execute(select(documents.c.body).where(documents.c.id == document_id, documents.c.sme_id == sme_id)).first()
        return decrypt_text(row[0]) if row else None

    def delete_documents(self, sme_id: str, document_ids: list[str] | None = None) -> None:
        """Remove documents (all of them when `document_ids` is None) and their stored files."""
        with self.engine.begin() as db:
            query = select(documents.c.id, documents.c.file_key).where(documents.c.sme_id == sme_id)
            if document_ids is not None:
                query = query.where(documents.c.id.in_(document_ids))
            rows = db.execute(query).all()
            if rows:
                db.execute(delete(documents).where(documents.c.id.in_([r[0] for r in rows])))
        for _, key in rows:
            if key and not self._file_in_use(key):
                self.files.delete(key)

    def _file_in_use(self, key: str) -> bool:
        with self.engine.begin() as db:
            return db.execute(select(func.count()).select_from(documents).where(documents.c.file_key == key)).scalar_one() > 0

    # ---- dashboard progress ----

    def save_progress(self, sme_id: str, state_json: str) -> None:
        body = encrypt_text(state_json)
        with self.engine.begin() as db:
            db.execute(delete(progress).where(progress.c.sme_id == sme_id))
            db.execute(insert(progress).values(sme_id=sme_id, updated_at=_now(), body=body))

    def get_progress(self, sme_id: str) -> str | None:
        with self.engine.begin() as db:
            row = db.execute(select(progress.c.body).where(progress.c.sme_id == sme_id)).first()
        return decrypt_text(row[0]) if row else None

    # ---- applications (JSON in, JSON out; the applications package owns the model) ----

    def save_application(self, *, app_id: str, lender: str, sme_id: str, status: str, submitted_at: datetime, body_json: str) -> None:
        body = encrypt_text(body_json)
        with self.engine.begin() as db:
            db.execute(delete(applications).where(applications.c.id == app_id))
            db.execute(insert(applications).values(id=app_id, lender=lender, sme_id=sme_id, status=status,
                                                   submitted_at=submitted_at, body=body))

    def get_application(self, app_id: str) -> str | None:
        with self.engine.begin() as db:
            row = db.execute(select(applications.c.body).where(applications.c.id == app_id)).first()
        return decrypt_text(row[0]) if row else None

    def list_applications(self, *, lender: str | None = None, sme_id: str | None = None) -> list[str]:
        query = select(applications.c.body).order_by(applications.c.submitted_at.desc())
        if lender:
            query = query.where(applications.c.lender == lender)
        if sme_id:
            query = query.where(applications.c.sme_id == sme_id)
        with self.engine.begin() as db:
            return [decrypt_text(r[0]) for r in db.execute(query).all()]

    def count_applications(self) -> int:
        with self.engine.begin() as db:
            return db.execute(select(func.count()).select_from(applications)).scalar_one()


@lru_cache(maxsize=1)
def get_db() -> Database:
    """The app-wide database. Tests clear this cache after pointing CREDITSETU_DB at a temp file."""
    url = database_url()
    kwargs = {"pool_pre_ping": True} if url.startswith("postgresql") else {"connect_args": {"check_same_thread": False}}
    return Database(create_engine(url, **kwargs), make_file_store())
