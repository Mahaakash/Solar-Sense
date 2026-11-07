"""
tests/test_weather.py
─────────────────────
Unit tests for backend/services/weather.py using mocked responses.
Ensures zero external network calls during test execution.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from backend import config
from backend.services.weather import (
    EmptyDataError,
    PlaceNotFoundError,
    WeatherAPIError,
    geocode,
    get_forecast_weather,
    get_historical_weather,
)

# ── Mock Payloads ───────────────────────────────────────────────────

MOCK_GEO_RESPONSE = {
    "results": [
        {
            "id": 1275004,
            "name": "Kolkata",
            "latitude": 22.56263,
            "longitude": 88.36304,
            "admin1": "West Bengal",
            "country": "India",
        }
    ]
}

MOCK_HOURLY_RESPONSE = {
    "latitude": 22.56,
    "longitude": 88.36,
    "timezone": "Asia/Kolkata",
    "hourly": {
        "time": [
            "2023-01-01T00:00",
            "2023-01-01T01:00",
            "2023-01-01T02:00",
        ],
        "shortwave_radiation": [0.0, 150.0, 350.0],
        "direct_radiation": [0.0, 100.0, 250.0],
        "diffuse_radiation": [0.0, 50.0, 100.0],
        "temperature_2m": [18.2, 19.5, 22.1],
        "cloud_cover": [10.0, 15.0, 5.0],
        "relative_humidity_2m": [75.0, 68.0, 55.0],
        "wind_speed_10m": [2.1, 2.5, 3.0],
        "precipitation": [0.0, 0.0, 0.0],
    },
}


# ── Geocoding Tests ─────────────────────────────────────────────────

@patch("backend.services.weather._load_from_cache", return_value=None)
@patch("backend.services.weather._save_to_cache")
@patch("requests.Session.get")
def test_geocode_success(mock_get, mock_save, mock_cache):
    """Test successful geocode lookup parses lat, lon, and display_name."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_GEO_RESPONSE
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    lat, lon, name = geocode("Kolkata")

    assert pytest.approx(lat, 0.001) == 22.562
    assert pytest.approx(lon, 0.001) == 88.363
    assert name == "Kolkata, West Bengal, India"
    mock_save.assert_called_once()


@patch("backend.services.weather._load_from_cache", return_value=None)
@patch("backend.services.weather._save_to_cache")
@patch("requests.Session.get")
def test_geocode_not_found_raises_error(mock_get, mock_save, mock_cache):
    """Test unknown location raises PlaceNotFoundError."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    with pytest.raises(PlaceNotFoundError, match="Could not find coordinates"):
        geocode("NonExistentPlaceXYZ999")
    mock_save.assert_not_called()


def test_geocode_empty_string_raises_error():
    """Empty place string raises PlaceNotFoundError without calling API."""
    with pytest.raises(PlaceNotFoundError, match="Place name cannot be empty"):
        geocode("   ")


# ── Weather Data Retrieval Tests ────────────────────────────────────

@patch("backend.services.weather._load_from_cache", return_value=None)
@patch("backend.services.weather._save_to_cache")
@patch("requests.Session.get")
def test_get_historical_weather_success(mock_get, mock_save, mock_cache):
    """Historical weather parses into a DataFrame with tz-aware DatetimeIndex."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_HOURLY_RESPONSE
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    df = get_historical_weather(22.56, 88.36, "2023-01-01", "2023-01-01")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None
    # Check default tilt factor fallback calculation
    expected_tilted = 150.0 * config.TILT_FACTOR
    assert df["global_tilted_irradiance"].iloc[1] == expected_tilted
    mock_save.assert_called_once()


@patch("backend.services.weather._load_from_cache", return_value=None)
@patch("backend.services.weather._save_to_cache")
@patch("requests.Session.get")
def test_get_forecast_weather_success(mock_get, mock_save, mock_cache):
    """Forecast weather returns valid DataFrame."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_HOURLY_RESPONSE
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    df = get_forecast_weather(22.56, 88.36, days=3)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3
    assert "temperature_2m" in df.columns
    assert "precipitation" in df.columns


# ── Caching & Error Handling Tests ──────────────────────────────────

@patch("backend.services.weather._load_from_cache", return_value=MOCK_HOURLY_RESPONSE)
@patch("requests.Session.get")
def test_cache_hit_bypasses_network(mock_get, mock_cache):
    """When disk cache has the data, no HTTP request should be sent."""
    df = get_historical_weather(22.56, 88.36, "2023-01-01", "2023-01-01")

    assert len(df) == 3
    mock_get.assert_not_called()


@patch("backend.services.weather._load_from_cache", return_value=None)
@patch("requests.Session.get", side_effect=requests.exceptions.Timeout("Timed out"))
def test_network_timeout_raises_weather_api_error(mock_get, mock_cache):
    """Network timeout gets translated to WeatherAPIError."""
    with pytest.raises(WeatherAPIError, match="Open-Meteo request failed"):
        get_forecast_weather(22.56, 88.36, days=3)


@patch("backend.services.weather._load_from_cache", return_value=None)
@patch("backend.services.weather._save_to_cache")
@patch("requests.Session.get")
def test_empty_hourly_payload_raises_empty_data_error(mock_get, mock_save, mock_cache):
    """Empty or missing hourly payload raises EmptyDataError."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hourly": {"time": []}}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    with pytest.raises(EmptyDataError, match="contains no hourly weather data"):
        get_forecast_weather(22.56, 88.36, days=3)
