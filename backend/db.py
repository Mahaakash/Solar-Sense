"""
backend/db.py
─────────────
SQLAlchemy 2.x ORM setup for SolarSense.
Supports SQLite (local development) and Postgres (production) via DATABASE_URL.
Call ``init_db()`` once at application startup to create all tables.
"""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.config import DATABASE_URL

logger = logging.getLogger("solarsense.db")


# ── URL Normalisation ───────────────────────────────────────────────

def normalise_database_url(url: str) -> str:
    """
    Convert Postgres connection URLs to use the psycopg v3 driver.

    Heroku / Render / Neon often provide ``postgres://`` or ``postgresql://``.
    SQLAlchemy 2.x requires ``postgresql+psycopg://`` for the psycopg v3 driver.
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# ── Engine & Session Factory ────────────────────────────────────────

_normalised_url = normalise_database_url(DATABASE_URL)
_is_sqlite = _normalised_url.startswith("sqlite")

if _is_sqlite:
    # Ensure parent directory exists for file-based SQLite
    db_path = _normalised_url.replace("sqlite:///", "", 1)
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            _normalised_url,
            connect_args={"check_same_thread": False, "timeout": 15},
            echo=False,
        )
    else:
        engine = create_engine(
            _normalised_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )
else:
    engine = create_engine(
        _normalised_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=3,
        echo=False,
    )

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional session scope — commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── ORM Models ──────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Declarative base for all SolarSense models."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    capacity_kw: Mapped[float] = mapped_column(Float, nullable=False)
    tilt: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    azimuth: Mapped[float] = mapped_column(Float, nullable=False, default=180.0)
    installed_on: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        Index("ix_sites_user_id", "user_id"),
    )


class DailyReading(Base):
    __tablename__ = "daily_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("sites.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_kwh: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("site_id", "date", name="uq_reading_site_date"),
        Index("ix_readings_site_id", "site_id"),
        Index("ix_readings_date", "date"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("sites.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    cause: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_alerts_site_id", "site_id"),
    )


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    sites_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_job_runs_started_at", "started_at"),
    )


# ── Startup Initialisation ─────────────────────────────────────────

def init_db(max_retries: int = 3, backoff: float = 1.0) -> None:
    """
    Create all tables if they do not exist.

    Retries on the first connection to handle slow-waking free-tier databases.
    """
    for attempt in range(1, max_retries + 1):
        try:
            Base.metadata.create_all(bind=engine)

            # Enable WAL and FK enforcement for SQLite connections
            if _is_sqlite:
                with engine.connect() as conn:
                    conn.execute(text("PRAGMA journal_mode=WAL"))
                    conn.execute(text("PRAGMA foreign_keys=ON"))
                    conn.commit()

            logger.info("Database tables initialised successfully (attempt %d).", attempt)
            return
        except Exception as exc:
            if attempt < max_retries:
                logger.warning(
                    "Database connection attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt, max_retries, exc, backoff,
                )
                time.sleep(backoff)
                backoff *= 2
            else:
                logger.error("Database initialisation failed after %d attempts.", max_retries)
                raise


def reset_engine_for_testing(url: str) -> None:
    """
    Replace the module-level engine and session factory for test isolation.

    Only call from test fixtures — never from production code.
    """
    global engine, SessionLocal, _normalised_url, _is_sqlite
    _normalised_url = normalise_database_url(url)
    _is_sqlite = _normalised_url.startswith("sqlite")

    if _is_sqlite:
        db_path = _normalised_url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                _normalised_url,
                connect_args={"check_same_thread": False, "timeout": 15},
                echo=False,
            )
        else:
            engine = create_engine(
                _normalised_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )
    else:
        engine = create_engine(
            _normalised_url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=3,
            echo=False,
        )

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
