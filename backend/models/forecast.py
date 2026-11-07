"""
backend/models/forecast.py
──────────────────────────
Inference service for SolarSense solar power forecasting:
- Caches the trained XGBoost model bundle in memory.
- Provides predict_hourly() using Open-Meteo forecast data.
- Provides predict_for_dates() using Open-Meteo historical weather data.
- Enforces capacity scaling, nighttime zeroing, and physical limits [0, capacity_kw].
"""

from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from backend import config
from backend.services.features import engineer_features
from backend.services.weather import get_forecast_weather, get_historical_weather

# Module-level in-memory model cache
_CACHED_MODEL_BUNDLE: dict[str, Any] | None = None


def load_model(force_reload: bool = False) -> dict[str, Any]:
    """
    Load the trained solar forecast model bundle into memory.

    Raises FileNotFoundError with clear instructions if the model artifact has not been trained.
    """
    global _CACHED_MODEL_BUNDLE

    if _CACHED_MODEL_BUNDLE is not None and not force_reload:
        return _CACHED_MODEL_BUNDLE

    model_path = Path(config.MODEL_PATH)
    if not model_path.exists():
        err_msg = (
            f"\n{'='*70}\n"
            f"FATAL STARTUP ERROR: Trained model artifact not found!\n"
            f"Expected file at: {model_path.resolve()}\n"
            f"Please ensure 'backend/models/solar_xgb.joblib' is committed to the repository, "
            f"or run 'python scripts/train_model.py' to generate it.\n"
            f"{'='*70}\n"
        )
        print(err_msg, flush=True)
        msg = (
            f"Model file not found at '{model_path}'. "
            "Please run 'python scripts/train_model.py' to train and save the model."
        )
        raise FileNotFoundError(msg)

    bundle = joblib.load(model_path)
    _CACHED_MODEL_BUNDLE = bundle
    return bundle


def _run_model_inference(
    weather_df: pd.DataFrame,
    capacity_kw: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Shared inference engine for both forecast and historical weather.

    Returns:
      (hourly_df, daily_df)
    """
    bundle = load_model()
    model = bundle["model"]
    feature_names = bundle["feature_names"]
    ref_capacity = bundle.get("reference_capacity_kw", config.REFERENCE_PLANT_CAPACITY_KW)

    # 1. Feature Engineering
    X, _ = engineer_features(weather_df)
    X = X[feature_names]  # Ensure column order strictly matches training order

    # 2. Raw Predictions & Scaling
    raw_predictions = model.predict(X)

    # Scale linearly with requested site capacity
    capacity_scale = capacity_kw / ref_capacity
    scaled_predictions = raw_predictions * capacity_scale

    # 3. Physical Constraints:
    # - Nighttime output must be strictly 0.0 kW when irradiance is zero or negligible (< 0.1 W/m²)
    # - Power must not fall below 0.0 or exceed installed nameplate capacity
    irradiance = weather_df.get(
        "global_tilted_irradiance",
        weather_df.get("shortwave_radiation", pd.Series(0.0, index=weather_df.index)),
    )
    is_night = (irradiance <= 0.1).to_numpy()

    predicted_power = np.clip(scaled_predictions, 0.0, capacity_kw)
    predicted_power[is_night] = 0.0

    # 4. Hourly Output DataFrame
    hourly_df = pd.DataFrame(
        {
            "predicted_power_kw": np.round(predicted_power, 3),
            "irradiance": np.round(irradiance.to_numpy(), 1),
            "temperature_2m": np.round(weather_df["temperature_2m"].to_numpy(), 1),
        },
        index=weather_df.index,
    )

    # 5. Daily Aggregation Summary (1 kW for 1 hour = 1 kWh)
    # Group by local calendar date (preserving day boundaries)
    daily_groups = hourly_df.groupby(hourly_df.index.strftime("%Y-%m-%d"))
    daily_df = pd.DataFrame(
        {
            "predicted_energy_kwh": daily_groups["predicted_power_kw"].sum().round(2),
            "peak_power_kw": daily_groups["predicted_power_kw"].max().round(3),
        }
    )
    daily_df.index.name = "date"

    return hourly_df, daily_df


def predict_hourly(
    lat: float,
    lon: float,
    capacity_kw: float,
    tilt: float | None = None,
    azimuth: float | None = None,
    days: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generate hourly solar power forecasts using Open-Meteo forecast API.

    Returns:
      (hourly_df, daily_df)
    """
    weather_df = get_forecast_weather(
        lat=lat,
        lon=lon,
        days=days,
        tilt=tilt,
        azimuth=azimuth,
    )
    return _run_model_inference(weather_df=weather_df, capacity_kw=capacity_kw)


def predict_for_dates(
    lat: float,
    lon: float,
    capacity_kw: float,
    tilt: float | None = None,
    azimuth: float | None = None,
    start_date: str | date = "2023-01-01",
    end_date: str | date = "2023-01-07",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generate weather-adjusted solar power predictions for past dates using historical weather.

    Used by the Watchdog diagnostic engine to establish expected performance.
    Returns:
      (hourly_df, daily_df)
    """
    weather_df = get_historical_weather(
        lat=lat,
        lon=lon,
        start_date=start_date,
        end_date=end_date,
        tilt=tilt,
        azimuth=azimuth,
    )
    return _run_model_inference(weather_df=weather_df, capacity_kw=capacity_kw)
