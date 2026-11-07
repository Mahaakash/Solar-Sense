"""
tests/test_forecast.py
──────────────────────
Unit tests for backend/models/forecast.py and GET /forecast endpoint.
All external weather service calls are mocked to ensure offline execution.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.main import app
from backend.models import forecast
from backend.models.forecast import (
    load_model,
    predict_for_dates,
    predict_hourly,
)

client = TestClient(app)


@pytest.fixture
def sample_weather_forecast_df() -> pd.DataFrame:
    """Create a 72-hour synthetic weather forecast DataFrame (3 days)."""
    times = pd.date_range("2026-11-07 00:00", periods=72, freq="1h", tz="Asia/Kolkata")
    n = len(times)

    hours = times.hour
    daylight = (hours >= 6) & (hours < 18)
    irradiance = np.where(daylight, 750.0 * np.sin(np.pi * (hours - 6) / 12), 0.0)
    irradiance = np.maximum(0.0, irradiance)

    return pd.DataFrame(
        {
            "global_tilted_irradiance": irradiance,
            "shortwave_radiation": irradiance,
            "direct_radiation": irradiance * 0.7,
            "diffuse_radiation": irradiance * 0.3,
            "temperature_2m": np.linspace(20.0, 32.0, n),
            "cloud_cover": np.linspace(5.0, 40.0, n),
            "relative_humidity_2m": np.linspace(45.0, 75.0, n),
            "wind_speed_10m": np.linspace(1.5, 4.0, n),
            "precipitation": np.zeros(n),
        },
        index=times,
    )


def test_missing_model_raises_informative_error(monkeypatch) -> None:
    """Missing model joblib file must raise FileNotFoundError with actionable instructions."""
    monkeypatch.setattr(config, "MODEL_PATH", "backend/models/non_existent_model.joblib")
    forecast._CACHED_MODEL_BUNDLE = None

    with pytest.raises(FileNotFoundError, match=r"run 'python scripts/train_model\.py'"):
        load_model(force_reload=True)


@patch("backend.models.forecast.get_forecast_weather")
def test_predict_hourly_output_shape(mock_weather, sample_weather_forecast_df) -> None:
    """predict_hourly output shape must match weather timestamps and days."""
    mock_weather.return_value = sample_weather_forecast_df

    hourly_df, daily_df = predict_hourly(
        lat=22.56, lon=88.36, capacity_kw=5.0, days=3
    )

    assert len(hourly_df) == 72
    assert "predicted_power_kw" in hourly_df.columns
    assert "irradiance" in hourly_df.columns
    assert len(daily_df) == 3
    assert "predicted_energy_kwh" in daily_df.columns
    assert "peak_power_kw" in daily_df.columns


@patch("backend.models.forecast.get_forecast_weather")
def test_predict_hourly_bounds_and_night_zero(mock_weather, sample_weather_forecast_df) -> None:
    """Predicted power must be non-negative, <= capacity, and strictly 0 at night."""
    mock_weather.return_value = sample_weather_forecast_df
    capacity = 8.0

    hourly_df, _ = predict_hourly(
        lat=22.56, lon=88.36, capacity_kw=capacity, days=3
    )

    power = hourly_df["predicted_power_kw"]
    irradiance = hourly_df["irradiance"]

    assert (power >= 0.0).all(), "Negative power predictions detected."
    assert (power <= capacity).all(), f"Power exceeded capacity of {capacity} kW."

    night_mask = irradiance <= 0.0
    night_power = power[night_mask]
    nonzero = night_power[night_power != 0.0]
    assert (night_power == 0.0).all(), f"Non-zero nighttime power: {nonzero}"


@patch("backend.models.forecast.get_forecast_weather")
def test_predict_capacity_scaling(mock_weather, sample_weather_forecast_df) -> None:
    """A 10 kW plant should predict twice the power of a 5 kW plant under identical weather."""
    mock_weather.return_value = sample_weather_forecast_df

    hourly_5kw, _ = predict_hourly(lat=22.56, lon=88.36, capacity_kw=5.0, days=3)
    hourly_10kw, _ = predict_hourly(lat=22.56, lon=88.36, capacity_kw=10.0, days=3)

    ratio = hourly_10kw["predicted_power_kw"] / (hourly_5kw["predicted_power_kw"] + 1e-6)
    daylight = hourly_5kw["irradiance"] > 100.0

    # During daylight, 10kW output should be approx 2.0x 5kW output
    assert np.allclose(ratio[daylight], 2.0, atol=0.01)


@patch("backend.models.forecast.get_historical_weather")
def test_predict_for_dates_historical(mock_hist_weather, sample_weather_forecast_df) -> None:
    """predict_for_dates retrieves historical weather and returns valid predictions."""
    mock_hist_weather.return_value = sample_weather_forecast_df

    hourly_df, daily_df = predict_for_dates(
        lat=22.56,
        lon=88.36,
        capacity_kw=5.0,
        start_date="2023-01-01",
        end_date="2023-01-03",
    )

    assert len(hourly_df) == 72
    assert (hourly_df["predicted_power_kw"] >= 0.0).all()
    assert len(daily_df) == 3


@patch("backend.models.forecast.get_forecast_weather")
def test_get_forecast_endpoint(mock_weather, sample_weather_forecast_df) -> None:
    """GET /forecast returns HTTP 200 with matching schema."""
    mock_weather.return_value = sample_weather_forecast_df

    resp = client.get("/forecast?lat=22.56&lon=88.36&capacity_kw=5.0&days=3")
    assert resp.status_code == 200
    data = resp.json()

    assert data["site_capacity_kw"] == 5.0
    assert len(data["hourly"]) == 72
    assert len(data["daily"]) == 3
    assert "predicted_power_kw" in data["hourly"][0]
    assert "predicted_energy_kwh" in data["daily"][0]
