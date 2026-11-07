"""
tests/test_features.py
──────────────────────
Unit tests for backend/services/features.py:
1. No NaNs in engineered features.
2. Nighttime power output is strictly zero.
3. Power output never exceeds plant capacity.
4. Cyclical time encodings remain within [-1, 1].
5. Feature list matches returned DataFrame columns.
"""

import numpy as np
import pandas as pd
import pytest

from backend import config
from backend.services.features import (
    build_training_dataset,
    engineer_features,
    generate_synthetic_power,
)


@pytest.fixture
def sample_weather_df() -> pd.DataFrame:
    """Create a 48-hour synthetic weather DataFrame for testing."""
    times = pd.date_range("2023-06-01 00:00", periods=48, freq="1h", tz="Asia/Kolkata")
    n = len(times)

    # Simple solar diurnal curve: 0 at night (hours 0-5 and 19-23), positive during day
    hours = times.hour
    daylight = (hours >= 6) & (hours <= 18)
    irradiance = np.where(daylight, 800.0 * np.sin(np.pi * (hours - 6) / 12), 0.0)
    irradiance = np.maximum(0.0, irradiance)

    return pd.DataFrame(
        {
            "global_tilted_irradiance": irradiance,
            "shortwave_radiation": irradiance,
            "direct_radiation": irradiance * 0.7,
            "diffuse_radiation": irradiance * 0.3,
            "temperature_2m": np.linspace(22.0, 38.0, n),
            "cloud_cover": np.linspace(0.0, 80.0, n),
            "relative_humidity_2m": np.linspace(40.0, 90.0, n),
            "wind_speed_10m": np.linspace(1.0, 6.0, n),
            "precipitation": np.zeros(n),
        },
        index=times,
    )


def test_no_nans_in_features(sample_weather_df: pd.DataFrame) -> None:
    """Feature matrix must have zero NaN values, even with lag and rolling features."""
    X, feature_names = engineer_features(sample_weather_df)

    assert isinstance(X, pd.DataFrame)
    assert X.isnull().sum().sum() == 0, f"Found NaNs in features:\n{X.isnull().sum()}"
    assert len(feature_names) == X.shape[1]
    assert list(X.columns) == feature_names


def test_nighttime_output_is_zero(sample_weather_df: pd.DataFrame) -> None:
    """Whenever irradiance is 0, power output must be exactly 0.0."""
    capacity = 5.0
    y = generate_synthetic_power(sample_weather_df, capacity_kw=capacity, random_seed=42)

    night_mask = sample_weather_df["global_tilted_irradiance"] == 0.0
    assert night_mask.sum() > 0, "Test fixture must contain night hours."

    night_power = y[night_mask]
    nonzero = night_power[night_power != 0.0]
    assert (night_power == 0.0).all(), f"Non-zero power found at night: {nonzero}"


def test_output_never_exceeds_capacity(sample_weather_df: pd.DataFrame) -> None:
    """Power generation must be bounded by [0.0, capacity_kw]."""
    capacity = 10.0
    y = generate_synthetic_power(sample_weather_df, capacity_kw=capacity, random_seed=42)

    assert (y >= 0.0).all(), "Negative power values found."
    assert (y <= capacity).all(), f"Power exceeded capacity of {capacity} kW: {y[y > capacity]}"


def test_cyclical_time_encodings_bounded(sample_weather_df: pd.DataFrame) -> None:
    """Sin and Cos encodings for hour and day must lie within [-1.0, 1.0]."""
    X, _ = engineer_features(sample_weather_df)

    for col in ["hour_sin", "hour_cos", "day_sin", "day_cos"]:
        assert (X[col] >= -1.0).all() and (X[col] <= 1.0).all(), f"{col} out of [-1, 1] bounds."


def test_build_training_dataset_alignment(sample_weather_df: pd.DataFrame) -> None:
    """build_training_dataset should return matching X and y with identical indices."""
    X, y, feature_names = build_training_dataset(
        sample_weather_df, capacity_kw=config.REFERENCE_PLANT_CAPACITY_KW
    )

    assert len(X) == len(y)
    assert (X.index == y.index).all()
    assert y.name == "power_kw"
    assert "irradiance" in feature_names
    assert "irradiance_lag_1h" in feature_names
