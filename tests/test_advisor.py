"""
tests/test_advisor.py
─────────────────────
Unit and integration tests for SolarSense Advisor service and POST /advisor endpoint.
External weather and geocoding services are mocked to guarantee fast, deterministic offline tests.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.weather import PlaceNotFoundError

client = TestClient(app)


@pytest.fixture
def mock_one_year_weather() -> pd.DataFrame:
    """Create a simulated 1-year (8,760 hours) weather DataFrame for 2023."""
    times = pd.date_range("2023-01-01 00:00", periods=8760, freq="1h", tz="Asia/Kolkata")
    hours = times.hour
    daylight = (hours >= 6) & (hours < 18)

    # Moderate solar curve producing ~1,400 kWh/kWp annual yield
    irradiance = np.where(daylight, 650.0 * np.sin(np.pi * (hours - 6) / 12), 0.0)
    irradiance = np.maximum(0.0, irradiance)

    return pd.DataFrame(
        {
            "global_tilted_irradiance": irradiance,
            "shortwave_radiation": irradiance,
            "direct_radiation": irradiance * 0.7,
            "diffuse_radiation": irradiance * 0.3,
            "temperature_2m": np.full(8760, 26.0),
            "cloud_cover": np.full(8760, 20.0),
            "relative_humidity_2m": np.full(8760, 60.0),
            "wind_speed_10m": np.full(8760, 2.5),
            "precipitation": np.zeros(8760),
        },
        index=times,
    )


@patch("backend.services.advisor.geocode", return_value=(22.5626, 88.3630, "Kolkata, WB, India"))
@patch("backend.models.forecast.get_historical_weather")
def test_advisor_small_domestic_bill(
    mock_weather, mock_geo, mock_one_year_weather
) -> None:
    """A small monthly bill (~₹2,000) recommends a modest system with positive payback."""
    mock_weather.return_value = mock_one_year_weather

    payload = {
        "place_name": "Kolkata",
        "monthly_bill_inr": 2000.0,
    }
    resp = client.post("/advisor", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["system_size_kw"] >= 0.5
    assert data["payback_period_years"] > 0
    assert data["yearly_savings_inr"] > 0
    assert data["system_cost_inr"] > 0
    assert not data["roof_area_capped"]
    assert len(data["monthly_generation"]) == 12
    assert len(data["cumulative_savings_25yr"]) == 25
    assert data["net_25yr_savings_inr"] > 0
    assert "tariff_inr_per_kwh" in data["assumptions"]


@patch("backend.services.advisor.geocode", return_value=(22.5626, 88.3630, "Kolkata, WB, India"))
@patch("backend.models.forecast.get_historical_weather")
def test_advisor_large_bill_scales_system_size_and_savings(
    mock_weather, mock_geo, mock_one_year_weather
) -> None:
    """A higher electricity bill scales the recommended system size and yearly savings."""
    mock_weather.return_value = mock_one_year_weather

    resp_small = client.post(
        "/advisor", json={"place_name": "Kolkata", "monthly_bill_inr": 2000.0}
    )
    resp_large = client.post(
        "/advisor", json={"place_name": "Kolkata", "monthly_bill_inr": 10000.0}
    )

    small_data = resp_small.json()
    large_data = resp_large.json()

    assert large_data["system_size_kw"] > small_data["system_size_kw"]
    assert large_data["yearly_savings_inr"] > small_data["yearly_savings_inr"]
    assert large_data["system_cost_inr"] > small_data["system_cost_inr"]


@patch("backend.services.advisor.geocode", return_value=(22.5626, 88.3630, "Kolkata, WB, India"))
@patch("backend.models.forecast.get_historical_weather")
def test_advisor_tiny_roof_area_cap(
    mock_weather, mock_geo, mock_one_year_weather
) -> None:
    """When roof area is restricted, system capacity is clamped and roof_area_capped is True."""
    mock_weather.return_value = mock_one_year_weather

    # High bill wants ~10 kW, but 20 m² roof limits to 20 / 10 = 2.0 kW
    payload = {
        "place_name": "Kolkata",
        "monthly_bill_inr": 15000.0,
        "roof_area_m2": 20.0,
    }
    resp = client.post("/advisor", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["roof_area_capped"] is True
    assert data["system_size_kw"] <= 2.0


def test_advisor_rejects_negative_bill() -> None:
    """A zero or negative monthly bill must return HTTP 400."""
    payload = {
        "place_name": "Kolkata",
        "monthly_bill_inr": -1200.0,
    }
    resp = client.post("/advisor", json=payload)
    assert resp.status_code == 400
    assert "greater than zero" in resp.json()["detail"]


def test_advisor_rejects_negative_roof_area() -> None:
    """Negative roof area must return HTTP 400."""
    payload = {
        "place_name": "Kolkata",
        "monthly_bill_inr": 2500.0,
        "roof_area_m2": -15.0,
    }
    resp = client.post("/advisor", json=payload)
    assert resp.status_code == 400
    assert "greater than zero" in resp.json()["detail"]


def test_advisor_rejects_missing_location() -> None:
    """Request with neither place_name nor coordinates must return HTTP 400."""
    payload = {
        "monthly_bill_inr": 3000.0,
    }
    resp = client.post("/advisor", json=payload)
    assert resp.status_code == 400
    assert "coordinates must be provided" in resp.json()["detail"]


@patch("backend.services.advisor.geocode", side_effect=PlaceNotFoundError("Place not found"))
def test_advisor_handles_unknown_place(mock_geo) -> None:
    """An unresolvable place name must return HTTP 404."""
    payload = {
        "place_name": "NonExistentPlaceXYZ",
        "monthly_bill_inr": 3000.0,
    }
    resp = client.post("/advisor", json=payload)
    assert resp.status_code == 404
    assert "Place not found" in resp.json()["detail"]


@patch("backend.models.forecast.get_historical_weather")
def test_advisor_supports_direct_lat_lon(mock_weather, mock_one_year_weather) -> None:
    """Direct latitude and longitude coordinates work without geocoding."""
    mock_weather.return_value = mock_one_year_weather

    payload = {
        "lat": 19.0760,
        "lon": 72.8777,
        "monthly_bill_inr": 3500.0,
    }
    resp = client.post("/advisor", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert pytest.approx(data["latitude"], 0.01) == 19.0760
    assert pytest.approx(data["longitude"], 0.01) == 72.8777
