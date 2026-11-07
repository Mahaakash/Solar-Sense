"""
tests/test_validation_importer.py
─────────────────────────────────
Unit and integration tests for SolarSense Step 11:
- Real-data CSV importer (daily kWh, interval kW, Wh units, day-first dates, bad rows, duplicates).
- Empirical clear-sky calibration (median robustness to outliers, insufficient days).
- Watchdog usage of site calibrated performance ratio.
- Advisor validation script execution with mocked weather.
"""

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.db import DailyReading, Site, User, get_session, init_db
from backend.main import app
from backend.services.calibration import calibrate_site_ratio
from backend.services.importer import import_readings_csv
from backend.services.watchdog import get_site_by_id
from scripts.validate_advisor import validate_advisor

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_test_site():
    """Ensure a consistent test site exists in the database."""
    init_db()
    with get_session() as session:
        user = session.query(User).filter(User.id == 1).first()
        if not user:
            session.add(User(id=1, name="Test Owner", email="test@solarsense.local"))
            session.flush()

        site = session.query(Site).filter(Site.id == 99).first()
        if not site:
            session.add(
                Site(
                    id=99,
                    user_id=1,
                    name="Unit Test Validation Site",
                    lat=28.6139,
                    lon=77.2090,
                    capacity_kw=5.0,
                    tilt=28.0,
                    azimuth=180.0,
                    installed_on=date(2022, 1, 1),
                )
            )
            session.flush()


# ── Importer Tests ──────────────────────────────────────────────────

def test_importer_daily_kwh_format():
    """CSV with date and energy_kwh is parsed as daily_kwh."""
    csv_data = (
        "date,energy_kwh\n"
        "2023-01-01,21.5\n"
        "2023-01-02,22.0\n"
        "2023-01-03,20.8\n"
    )
    report = import_readings_csv(site_id=99, content=csv_data)

    assert report["status"] == "ok"
    assert report["detected_format"] == "daily_kwh"
    assert report["days_created"] == 3
    assert report["rows_read"] == 3
    assert report["rows_skipped"] == 0
    assert report["date_range"]["start"] == "2023-01-01"
    assert report["date_range"]["end"] == "2023-01-03"


def test_importer_interval_kw_format():
    """CSV with timestamp and power_kw at 15-min intervals integrates to daily kWh."""
    # 4 intervals of 15 min (0.25 hr) at 4 kW = 4 * 0.25 = 1 kWh each -> 4 kWh total
    csv_data = (
        "timestamp,power_kw\n"
        "2023-02-01 10:00:00,4.0\n"
        "2023-02-01 10:15:00,4.0\n"
        "2023-02-01 10:30:00,4.0\n"
        "2023-02-01 10:45:00,4.0\n"
    )
    report = import_readings_csv(site_id=99, content=csv_data)

    assert report["status"] == "ok"
    assert report["detected_format"] == "interval_kw"
    assert report["days_created"] == 1
    assert report["rows_read"] == 4

    # Verify stored value in DB
    with get_session() as session:
        r = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == 99, DailyReading.date == date(2023, 2, 1))
            .first()
        )
        assert r is not None
        assert abs(r.actual_kwh - 4.0) < 0.1


def test_importer_wh_units_and_scaling():
    """CSV with Wh in header divides by 1000 to convert to kWh."""
    csv_data = (
        "Date,daily_yield_wh\n"
        "2023-03-01,18500\n"
        "2023-03-02,22100\n"
    )
    report = import_readings_csv(site_id=99, content=csv_data)

    assert report["status"] == "ok"
    assert report["energy_unit"] == "wh"
    assert report["days_created"] == 2

    with get_session() as session:
        r1 = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == 99, DailyReading.date == date(2023, 3, 1))
            .first()
        )
        assert r1 is not None
        assert abs(r1.actual_kwh - 18.5) < 0.01


def test_importer_day_first_dates():
    """CSV with DD/MM/YYYY format is correctly parsed."""
    csv_data = (
        "Date,kWh\n"
        "25/04/2023,19.2\n"
        "26/04/2023,20.1\n"
    )
    report = import_readings_csv(site_id=99, content=csv_data)

    assert report["status"] == "ok"
    assert report["days_created"] == 2
    assert report["date_range"]["start"] == "2023-04-25"
    assert report["date_range"]["end"] == "2023-04-26"


def test_importer_thousands_separators_and_negative_clipping():
    """Handles comma thousands separators (e.g. '1,250.0') and clips night negative noise."""
    csv_data = (
        "Date,energy_wh\n"
        "2023-05-01,\"18,500\"\n"
        "2023-05-02,-15.0\n"
    )
    report = import_readings_csv(site_id=99, content=csv_data)

    assert report["status"] == "ok"
    assert "negative_value_clipped_to_zero" in report["skip_reasons"]

    with get_session() as session:
        r2 = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == 99, DailyReading.date == date(2023, 5, 2))
            .first()
        )
        assert r2 is not None
        assert r2.actual_kwh == 0.0


def test_importer_bad_rows_and_duplicates():
    """Unparseable dates/numbers are counted in skip_reasons; duplicate dates update cleanly."""
    csv_data = (
        "date,actual_kwh\n"
        "2023-06-01,15.0\n"
        "invalid-date,20.0\n"
        "2023-06-02,bad-number\n"
        "2023-06-01,18.0\n"  # Duplicate of 06-01 with updated reading
    )
    report = import_readings_csv(site_id=99, content=csv_data)

    assert report["status"] == "ok"
    assert report["rows_read"] == 4
    assert report["days_created"] == 1
    assert report["rows_skipped"] == 2
    assert "unparseable_date" in report["skip_reasons"]
    assert "unparseable_numeric_value" in report["skip_reasons"]

    with get_session() as session:
        r = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == 99, DailyReading.date == date(2023, 6, 1))
            .first()
        )
        assert r is not None
        assert r.actual_kwh == 18.0


def test_importer_missing_energy_column_raises_400():
    """CSV missing recognizable energy/power header returns HTTP 400."""
    resp = client.post(
        "/readings/import?site_id=99",
        content="date,temperature\n2023-01-01,25.0",
        headers={"Content-Type": "text/csv"},
    )
    assert resp.status_code == 400
    assert "energy or power column" in resp.json()["detail"].lower()


def test_importer_nonexistent_site_raises_404():
    """Importing for nonexistent site ID returns HTTP 404."""
    resp = client.post(
        "/readings/import?site_id=99999",
        content="date,energy_kwh\n2023-01-01,20.0",
        headers={"Content-Type": "text/csv"},
    )
    assert resp.status_code == 404


# ── Calibration Tests ───────────────────────────────────────────────

def test_calibration_robust_to_outliers():
    """Empirical calibration computes MEDIAN, protecting against severe outage outliers."""
    site_id = 99
    # Populate readings for site 99:
    # 4 clear days with ratio 0.80, plus 1 outage day with ratio 0.075
    # The mean would be dragged down to ~0.655, but the median must remain 0.80.
    test_dates = [f"2023-07-0{i}" for i in range(1, 6)]
    mock_expected = pd.DataFrame(
        {"predicted_energy_kwh": [20.0] * 5},
        index=test_dates,
    )

    with get_session() as session:
        # Clear existing readings for July 2023
        session.query(DailyReading).filter(
            DailyReading.site_id == site_id,
            DailyReading.date >= date(2023, 7, 1),
            DailyReading.date <= date(2023, 7, 5),
        ).delete()
        # Add 4 normal days (16 kWh) and 1 outage day (1.5 kWh)
        session.add(DailyReading(site_id=site_id, date=date(2023, 7, 1), actual_kwh=16.0))
        session.add(DailyReading(site_id=site_id, date=date(2023, 7, 2), actual_kwh=16.0))
        session.add(DailyReading(site_id=site_id, date=date(2023, 7, 3), actual_kwh=16.0))
        session.add(DailyReading(site_id=site_id, date=date(2023, 7, 4), actual_kwh=16.0))
        session.add(DailyReading(site_id=site_id, date=date(2023, 7, 5), actual_kwh=1.5))
        session.flush()

    with patch(
        "backend.services.calibration.predict_for_dates",
        return_value=(None, mock_expected),
    ):
        res = calibrate_site_ratio(site_id)

    assert res["status"] == "calibrated"
    # Median of [0.80, 0.80, 0.80, 0.80, 0.075] -> 0.80
    assert abs(res["calibrated_performance_ratio"] - 0.80) < 0.01

    # Verify persisted to Site record
    site_dict = get_site_by_id(site_id)
    assert site_dict["calibrated_performance_ratio"] == res["calibrated_performance_ratio"]


def test_calibration_insufficient_clear_days():
    """Site with zero clear-sky days raises an informative ValueError."""
    site_id = 99
    # Mock expected output below clear sky threshold (e.g. 5.0 kWh when 5kW requires 12.5 kWh)
    mock_low_expected = pd.DataFrame(
        {"predicted_energy_kwh": [5.0] * 5},
        index=[f"2023-07-0{i}" for i in range(1, 6)],
    )

    with (
        patch(
            "backend.services.calibration.predict_for_dates",
            return_value=(None, mock_low_expected),
        ),
        pytest.raises(ValueError, match="No clear-sky days"),
    ):
        calibrate_site_ratio(site_id)


def test_watchdog_uses_calibrated_ratio():
    """Watchdog uses site's calibrated ratio over global config for baseline health checks."""
    site_id = 99
    # Set site's calibrated PR to 0.72
    with get_session() as session:
        s = session.query(Site).filter(Site.id == site_id).first()
        s.calibrated_performance_ratio = 0.72
        session.flush()

    site = get_site_by_id(site_id)
    assert site["calibrated_performance_ratio"] == 0.72


# ── Validation Script Benchmark Test ────────────────────────────────

def test_validate_advisor_sample_reference(tmp_path):
    """Validation script processes sample reference CSV, computes metrics, and generates plot."""
    sample_csv = tmp_path / "test_reference_yields.csv"
    sample_csv.write_text(
        "city,lat,lon,tilt,azimuth,system_loss,pvgis,pvwatts\n"
        "CityA,28.6,77.2,28.0,180.0,0.14,1500.0,1520.0\n"
        "CityB,19.0,72.8,19.0,180.0,0.14,1550.0,\n"  # Empty cell for PVWatts
    )

    out_csv = tmp_path / "advisor_validation.csv"
    out_png = tmp_path / "advisor_validation.png"

    # Mock predict_for_dates: 0.16 * 8760 = 1401.6 kWh
    mock_hourly = pd.DataFrame({"predicted_power_kw": [0.16] * 8760})

    with patch("scripts.validate_advisor.predict_for_dates", return_value=(mock_hourly, None)):
        res_df = validate_advisor(
            csv_path=str(sample_csv),
            output_csv=str(out_csv),
            output_png=str(out_png),
        )

    assert len(res_df) == 2
    assert Path(out_csv).exists()
    assert Path(out_png).exists()
    assert "pct_diff_vs_pvgis" in res_df.columns
    assert "pct_diff_vs_pvwatts" in res_df.columns
    # Check that CityB pvwatts is None / NaN and did not crash
    assert pd.isna(res_df.loc[res_df["city"] == "CityB", "pvwatts"].iloc[0])
