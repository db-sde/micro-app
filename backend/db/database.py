"""
Database connection and session management for DegreeBaba backend.

Supports PostgreSQL (production) and SQLite (development fallback).
If DATABASE_URL is not set or PostgreSQL is unreachable, falls back to SQLite.
"""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Determine engine configuration ──────────────────────────────────
_SQLITE_PATH = Path(__file__).resolve().parent.parent / "degreebaba.db"
_SQLITE_URL = f"sqlite:///{_SQLITE_PATH}"


def _build_engine():
    """Create the SQLAlchemy engine, falling back to SQLite if needed."""
    url = DATABASE_URL

    if url and url.startswith("postgresql"):
        try:
            eng = create_engine(
                url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                echo=False,
            )
            # Quick connectivity check
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Connected to PostgreSQL: %s", url.split("@")[-1] if "@" in url else url)
            return eng
        except Exception as exc:
            logger.warning(
                "PostgreSQL unavailable (%s). Falling back to SQLite at %s",
                exc, _SQLITE_PATH,
            )

    # Fallback to SQLite
    logger.info("Using SQLite database: %s", _SQLITE_PATH)
    return create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )


engine = _build_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
