"""
Database package for Smart Manufacturing MAS.

Exports SessionLocal, engine, Base for use across the application.
Currently uses SQLite for zero-config setup.
Switch to PostgreSQL by changing DATABASE_URL in .env.
"""

from db.database import SessionLocal, engine, Base, get_db

__all__ = ["SessionLocal", "engine", "Base", "get_db"]
