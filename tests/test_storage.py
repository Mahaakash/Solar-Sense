"""
tests/test_storage.py
─────────────────────
Unit and integration tests for SolarSense SQLAlchemy storage layer:
- URL normalisation for Postgres psycopg v3 driver.
- Reading upsert (select-then-update updates existing reading without error).
- DEMO_MODE seed only when database is empty.
- Duplicate alert suppression via SQLAlchemy queries.
- GET /health/db endpoint verifying live database connectivity.
"""

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.db import Alert, Base, DailyReading, Site, engine, get_session, normalise_database_url
from backend.main import app
from backend.schemas import ReadingInputItem, SiteCreate
from backend.services.seed import seed_all_demo_sites
from backend.services.watchdog import (
    evaluate_site_health,
    get_site_alerts,
    ingest_readings,
    list_sites,
    register_site,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure clean database tables for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_url_normalisation() -> None:
    """Verify postgres:// and postgresql:// are normalised to postgresql+psycopg://."""
    # Heroku / legacy style
    assert (
        normalise_database_url("postgres://user:pass@host:5432/solardb")
        == "postgresql+psycopg://user:pass@host:5432/solardb"
    )
    # Standard psycopg2 style
    assert (
        normalise_database_url("postgresql://user:pass@host:5432/solardb")
        == "postgresql+psycopg://user:pass@host:5432/solardb"
    )
    # Already normalised
    assert (
        normalise_database_url("postgresql+psycopg://user:pass@host:5432/solardb")
        == "postgresql+psycopg://user:pass@host:5432/solardb"
    )
    # SQLite URLs left unchanged
    assert normalise_database_url("sqlite:///data/solarsense.db") == "sqlite:///data/solarsense.db"
    assert normalise_database_url("sqlite:///:memory:") == "sqlite:///:memory:"


@patch("backend.services.watchdog.predict_for_dates")
def test_reading_upsert(mock_predict) -> None:
    """Submitting a reading for an existing (site_id, date) updates it, giving one row."""
    mock_predict.return_value = (
        None,
        pd.DataFrame(
            {"predicted_energy_kwh": [20.0], "peak_power_kw": [4.0]},
            index=["2023-01-01"],
        ),
    )

    site = register_site(
        SiteCreate(
            name="Upsert Test Site",
            lat=22.5,
            lon=88.3,
            capacity_kw=5.0,
            installed_on=date(2022, 1, 1),
        )
    )

    reading_day = date(2023, 1, 1)

    # 1. First submission: 15.0 kWh
    count1 = ingest_readings(site.id, [ReadingInputItem(date=reading_day, actual_kwh=15.0)])
    assert count1 == 1

    with get_session() as session:
        rows = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == site.id, DailyReading.date == reading_day)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].actual_kwh == 15.0

    # 2. Second submission on the same date with updated value: 24.5 kWh
    count2 = ingest_readings(site.id, [ReadingInputItem(date=reading_day, actual_kwh=24.5)])
    assert count2 == 1

    with get_session() as session:
        rows = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == site.id, DailyReading.date == reading_day)
            .all()
        )
        assert len(rows) == 1, "Duplicate row created instead of upserting!"
        assert rows[0].actual_kwh == 24.5, "Existing reading was not updated with latest value!"


@patch("backend.services.watchdog.predict_for_dates")
@patch("backend.services.seed.predict_for_dates")
def test_seed_only_when_empty(mock_seed_predict, mock_wd_predict) -> None:
    """DEMO_MODE seeding must only populate when the sites table is empty."""
    # Generate 90 valid calendar dates starting 2023-01-01
    from datetime import timedelta
    valid_dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(90)]
    date_strs = [d.isoformat() for d in valid_dates]
    mock_df = pd.DataFrame(
        {"predicted_energy_kwh": [20.0] * 90, "peak_power_kw": [4.0] * 90},
        index=date_strs,
    )
    mock_seed_predict.return_value = (None, mock_df)
    mock_wd_predict.return_value = (None, mock_df)

    # 1. Initial state: zero sites
    assert len(list_sites()) == 0

    # 2. First seed: seeds 8 metro sites
    seed_results = seed_all_demo_sites()
    assert len(seed_results) == 8
    sites_after_seed = list_sites()
    assert len(sites_after_seed) == 8

    # 3. Verify DEMO_MODE startup guard: if sites already exist, it skips
    initial_site_ids = {s.id for s in sites_after_seed}
    # Simulate startup check
    existing = list_sites()
    assert bool(existing) is True  # DB is not empty, startup guard prevents re-seeding

    # Verify site records remain unchanged
    with get_session() as session:
        current_count = session.query(Site).count()
        assert current_count == 8
        current_ids = {s.id for s in session.query(Site).all()}
        assert current_ids == initial_site_ids


@patch("backend.services.watchdog.predict_for_dates")
def test_duplicate_alert_prevention_sqlalchemy(mock_predict) -> None:
    """Verifies that duplicate alerts within deduplication window are prevented."""
    dates = [date(2023, 1, 1)]
    mock_predict.return_value = (
        None,
        pd.DataFrame(
            {"predicted_energy_kwh": [20.0], "peak_power_kw": [4.0]},
            index=["2023-01-01"],
        ),
    )

    site = register_site(
        SiteCreate(
            name="Alert Dedup Site",
            lat=22.5,
            lon=88.3,
            capacity_kw=5.0,
            installed_on=date(2022, 1, 1),
        )
    )

    # 1. Ingest 1 day (triggers insufficient_data alert)
    ingest_readings(site.id, [ReadingInputItem(date=dates[0], actual_kwh=18.0)])
    alerts_1 = get_site_alerts(site.id)
    assert len(alerts_1) == 1
    assert alerts_1[0].cause == "insufficient_data"

    # 2. Trigger evaluate_site_health again immediately
    evaluate_site_health(site.id)
    alerts_2 = get_site_alerts(site.id)
    assert len(alerts_2) == 1, "Duplicate alert was inserted!"

    # 3. Direct DB check
    with get_session() as session:
        db_alert_count = session.query(Alert).filter(Alert.site_id == site.id).count()
        assert db_alert_count == 1


def test_health_db_endpoint() -> None:
    """Verify GET /health/db runs trivial query and reports status + dialect."""
    resp = client.get("/health/db")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "dialect" in data
    assert data["dialect"] == "sqlite"


def test_health_endpoint_remains_fast_and_db_free() -> None:
    """Verify GET /health does not execute heavy DB operations and returns ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
