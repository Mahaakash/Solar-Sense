"""
tests/test_watchdog.py
──────────────────────
Unit tests for backend/services/watchdog.py and Watchdog API endpoints:
- Healthy site raises no alert.
- Sudden fault diagnosis (critical).
- Dust & soiling diagnosis with rain advisory (warning).
- Ageing diagnosis (warning).
- Insufficient data diagnosis (info).
- Alert deduplication.
- API endpoints: POST /sites, POST /readings (JSON & CSV),
  GET /sites/{id}/health, GET /sites/{id}/alerts.
"""

from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.db import Base, engine
from backend.main import app
from backend.schemas import ReadingInputItem, SiteCreate
from backend.services.watchdog import (
    evaluate_site_health,
    get_site_alerts,
    ingest_readings,
    register_site,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    """Ensure clean database tables exist before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def test_site():
    """Create a temporary site for testing."""
    site_in = SiteCreate(
        name="Test Solar Site",
        lat=22.5626,
        lon=88.3630,
        capacity_kw=5.0,
        tilt=20.0,
        azimuth=180.0,
        installed_on=date(2022, 1, 1),
    )
    return register_site(site_in)


def make_mock_daily_expected(dates: list[date], daily_kwh: float = 20.0) -> pd.DataFrame:
    """Helper to create a mock daily expected generation DataFrame."""
    date_strs = [d.isoformat() for d in dates]
    return pd.DataFrame(
        {
            "predicted_energy_kwh": [daily_kwh] * len(dates),
            "peak_power_kw": [daily_kwh / 5.0] * len(dates),
        },
        index=date_strs,
    )


@patch("backend.services.watchdog.predict_for_dates")
def test_healthy_site_raises_no_alert(mock_predict, test_site) -> None:
    """A site operating at ~95% of expected output raises no alerts."""
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(20)]
    mock_predict.return_value = (None, make_mock_daily_expected(dates, daily_kwh=20.0))

    readings = [ReadingInputItem(date=d, actual_kwh=19.0) for d in dates]
    ingest_readings(test_site.id, readings)

    alerts = get_site_alerts(test_site.id)
    assert len(alerts) == 0, f"Expected 0 alerts for healthy site, got: {alerts}"


@patch("backend.services.watchdog.predict_for_dates")
def test_insufficient_data_diagnosis(mock_predict, test_site) -> None:
    """Fewer than 7 days of readings triggers an 'insufficient_data' informational alert."""
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(4)]
    mock_predict.return_value = (None, make_mock_daily_expected(dates, daily_kwh=20.0))

    readings = [ReadingInputItem(date=d, actual_kwh=18.0) for d in dates]
    ingest_readings(test_site.id, readings)

    alerts = get_site_alerts(test_site.id)
    assert len(alerts) == 1
    assert alerts[0].cause == "insufficient_data"
    assert alerts[0].severity == "info"


@patch("backend.services.watchdog.predict_for_dates")
def test_sudden_fault_diagnosis(mock_predict, test_site) -> None:
    """A sudden single-day drop > 50% on a clear-sky day diagnoses a critical fault."""
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
    mock_predict.return_value = (None, make_mock_daily_expected(dates, daily_kwh=25.0))

    # Days 0-8 healthy (24 kWh), day 9 drops to 4 kWh (< 20% on a 25 kWh clear day)
    readings = [
        ReadingInputItem(date=d, actual_kwh=24.0 if i < 9 else 4.0)
        for i, d in enumerate(dates)
    ]
    ingest_readings(test_site.id, readings)

    alerts = get_site_alerts(test_site.id)
    assert len(alerts) >= 1
    fault_alert = next((a for a in alerts if a.cause == "fault"), None)
    assert fault_alert is not None
    assert fault_alert.severity == "critical"
    assert "Sudden generation drop" in fault_alert.message
    assert "Estimated loss:" in fault_alert.message


@patch("backend.services.watchdog.get_forecast_weather")
@patch("backend.services.watchdog.get_historical_weather")
@patch("backend.services.watchdog.predict_for_dates")
def test_dust_soiling_diagnosis_with_rain_forecast(
    mock_predict, mock_hist_weather, mock_fc_weather, test_site
) -> None:
    """Sustained decline over 14 days with no rain diagnoses dust, and notes upcoming rain."""
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(16)]
    mock_predict.return_value = (None, make_mock_daily_expected(dates, daily_kwh=20.0))

    # Historical weather with zero rain
    mock_hist_weather.return_value = pd.DataFrame(
        {"precipitation": [0.0] * 384},
        index=pd.date_range("2023-01-01", periods=384, freq="1h"),
    )
    # Upcoming forecast predicts 5 mm rain
    mock_fc_weather.return_value = pd.DataFrame(
        {"precipitation": [0.2] * 48},
        index=pd.date_range("2023-01-17", periods=48, freq="1h"),
    )

    # Gradual linear decline: PR starts at 0.80 (16.0 kWh) and drops to 0.45 (9.0 kWh)
    # This brings 7-day PR to ~0.52 (< 0.60 alert level) with day-to-day drop of ~4.6% (< 50% fault)
    readings = [
        ReadingInputItem(date=d, actual_kwh=round(20.0 * (0.80 - 0.35 * (i / 15.0)), 2))
        for i, d in enumerate(dates)
    ]
    ingest_readings(test_site.id, readings)

    alerts = get_site_alerts(test_site.id)
    dust_alert = next((a for a in alerts if a.cause == "dust"), None)
    assert dust_alert is not None
    assert dust_alert.severity == "warning"
    assert "Panel washing recommended" in dust_alert.message
    assert "Rain is expected soon" in dust_alert.message


@patch("backend.services.watchdog.get_historical_weather")
@patch("backend.services.watchdog.predict_for_dates")
def test_ageing_diagnosis(mock_predict, mock_hist_weather, test_site) -> None:
    """Long-term shortfall beyond normal degradation after 2 years triggers ageing alert."""
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(35)]
    mock_predict.return_value = (None, make_mock_daily_expected(dates, daily_kwh=20.0))
    mock_hist_weather.return_value = pd.DataFrame(
        {"precipitation": [5.0] * len(dates)}, index=dates
    )

    # Site installed in 2020 (3 years old in 2023). Overall PR is ~68%, below expected ~77%
    readings = [ReadingInputItem(date=d, actual_kwh=13.5) for d in dates]
    ingest_readings(test_site.id, readings)

    alerts = get_site_alerts(test_site.id)
    ageing_alert = next((a for a in alerts if a.cause == "ageing"), None)
    assert ageing_alert is not None
    assert ageing_alert.severity == "warning"
    assert "degradation curve" in ageing_alert.message


@patch("backend.services.watchdog.predict_for_dates")
def test_duplicate_alert_suppression(mock_predict, test_site) -> None:
    """Re-evaluating with the same fault condition within 7 days does not create duplicates."""
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
    mock_predict.return_value = (None, make_mock_daily_expected(dates, daily_kwh=25.0))

    readings = [
        ReadingInputItem(date=d, actual_kwh=24.0 if i < 9 else 4.0)
        for i, d in enumerate(dates)
    ]
    ingest_readings(test_site.id, readings)
    alerts_first = get_site_alerts(test_site.id)

    # Trigger second evaluation on same day
    evaluate_site_health(test_site.id)
    alerts_second = get_site_alerts(test_site.id)

    assert len(alerts_first) == len(alerts_second)


@patch("backend.services.watchdog.predict_for_dates")
def test_watchdog_endpoints_integration(mock_predict) -> None:
    """Verify POST /sites, POST /readings (JSON & CSV), GET health, and GET alerts."""
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
    mock_predict.return_value = (None, make_mock_daily_expected(dates, daily_kwh=16.0))

    # 1. Register Site
    site_payload = {
        "name": "Integration Test Site",
        "lat": 19.0760,
        "lon": 72.8777,
        "capacity_kw": 4.0,
        "installed_on": "2023-01-01",
    }
    site_resp = client.post("/sites", json=site_payload)
    assert site_resp.status_code == 200
    site_id = site_resp.json()["id"]

    # 1b. Verify GET /sites
    list_resp = client.get("/sites")
    assert list_resp.status_code == 200
    site_ids = [s["id"] for s in list_resp.json()]
    assert site_id in site_ids

    # 2. Ingest via JSON
    json_readings = {
        "site_id": site_id,
        "readings": [
            {"date": "2023-01-01", "actual_kwh": 16.5},
            {"date": "2023-01-02", "actual_kwh": 17.0},
        ],
    }
    resp_json = client.post("/readings", json=json_readings)
    assert resp_json.status_code == 200
    assert resp_json.json()["readings_ingested"] == 2

    # 3. Ingest via CSV Upload
    csv_content = "date,actual_kwh\n2023-01-03,16.8\n2023-01-04,15.9\n"
    files = {"file": ("readings.csv", csv_content, "text/csv")}
    resp_csv = client.post(
        "/readings", data={"site_id": str(site_id)}, files=files
    )
    assert resp_csv.status_code == 200
    assert resp_csv.json()["readings_ingested"] == 2

    # 4. Query Health
    resp_health = client.get(f"/sites/{site_id}/health")
    assert resp_health.status_code == 200
    health_data = resp_health.json()
    assert health_data["site_id"] == site_id
    assert len(health_data["last_30_days"]) == 4

    # 5. Query Alerts
    resp_alerts = client.get(f"/sites/{site_id}/alerts")
    assert resp_alerts.status_code == 200
    assert isinstance(resp_alerts.json(), list)
