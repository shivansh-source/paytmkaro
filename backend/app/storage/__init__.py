"""Persistence: database (Supabase Postgres or SQLite), file store (Supabase Storage or a folder), encryption.

Everything personal is encrypted at rest with CREDITSETU_SECRET (see crypto.py).
"""

from app.storage.db import Database, get_db

__all__ = ["Database", "get_db"]
