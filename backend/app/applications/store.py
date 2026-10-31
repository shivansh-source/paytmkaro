"""SQLite storage for applications. One table, the full application as JSON: enough for the demo, easy to
swap for Postgres later. stdlib only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.applications.models import Application


class ApplicationStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS applications (
                       id TEXT PRIMARY KEY,
                       lender TEXT NOT NULL,
                       sme_id TEXT NOT NULL,
                       status TEXT NOT NULL,
                       submitted_at TEXT NOT NULL,
                       body TEXT NOT NULL
                   )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, app: Application) -> Application:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO applications (id, lender, sme_id, status, submitted_at, body) VALUES (?, ?, ?, ?, ?, ?)",
                (app.id, app.lender, app.profile.sme_id, app.status, app.submitted_at.isoformat(), app.model_dump_json()),
            )
        return app

    def get(self, application_id: str) -> Application | None:
        with self._connect() as db:
            row = db.execute("SELECT body FROM applications WHERE id = ?", (application_id,)).fetchone()
        return Application.model_validate_json(row[0]) if row else None

    def list(self, *, lender: str | None = None, sme_id: str | None = None) -> list[Application]:
        query, args = "SELECT body FROM applications WHERE 1=1", []
        if lender:
            query, args = query + " AND lender = ?", [*args, lender]
        if sme_id:
            query, args = query + " AND sme_id = ?", [*args, sme_id]
        with self._connect() as db:
            rows = db.execute(query + " ORDER BY submitted_at DESC", args).fetchall()
        return [Application.model_validate_json(r[0]) for r in rows]

    def count(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
