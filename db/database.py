"""
db/database.py — SQLAlchemy engine and session factory.

Reads DATABASE_URL from environment / .env file.
Default: SQLite (zero-config, file-based).
To use PostgreSQL: set DATABASE_URL=postgresql://user:pass@localhost:5432/smart_mas
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# ── Load .env ──────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# ── Database URL ───────────────────────────────────────────────────────────────
_DEFAULT_DB = "sqlite:///" + str(Path(__file__).parent.parent / "smart_mas.db")
DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_DB)

# SQLite needs check_same_thread=False for FastAPI's threaded request handling
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Safe to call multiple times (CREATE IF NOT EXISTS)."""
    from db import models  # noqa: F401 — import so Base.metadata knows all models
    Base.metadata.create_all(bind=engine)
