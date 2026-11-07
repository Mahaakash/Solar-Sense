"""
tests/conftest.py
─────────────────
Pytest configuration and test database isolation fixture.
Enforces that ALL tests run strictly against a local/in-memory SQLite database,
never touching remote PostgreSQL databases.
"""

import os
from pathlib import Path

# Override DATABASE_URL before any backend modules load
TEST_DB_PATH = "data/test_solarsense.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import pytest  # noqa: E402

from backend.db import init_db, reset_engine_for_testing  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def configure_test_database():
    """Ensure test suite runs against an isolated local SQLite database."""
    reset_engine_for_testing(f"sqlite:///{TEST_DB_PATH}")
    init_db()
    yield
    try:
        test_file = Path(TEST_DB_PATH)
        if test_file.exists():
            test_file.unlink(missing_ok=True)
    except Exception:
        pass
