"""
backend/services/features.py
────────────────────────────
Feature engineering and synthetic power generation pipeline for SolarSense.
Transforms raw meteorological time-series into ML-ready tabular features and
generates physically grounded synthetic solar generation targets.
"""

import numpy as np
import pandas as pd

from backend import config


def _get_irradiance_series(weather_df: pd.DataFrame) -> pd.Series:
    """Extract preferred irradiance column (tilted plane or fallback shortwave)."""
    if "global_tilted_irradiance" in weather_df.columns:
        return weather_df["global_tilted_irradiance"].clip(lower=0.0)
    if "shortwave_radiation" in weather_df.columns:
        return (weather_df["shortwave_radiation"] * config.TILT_FACTOR).clip(lower=0.0)
    msg = "Weather DataFrame must contain 'global_tilted_irradiance' or 'shortwave_radiation'."
    raise KeyError(msg)


def generate_synthetic_power(
    weather_df: pd.DataFrame,
    capacity_kw: float = config.REFERENCE_PLANT_CAPACITY_KW,
    random_seed: int = 42,
) -> pd.Series:
    """
    Generate synthetic hourly power output (kW) using physical solar formulas.

    Formula:
      cell_temp = temperature_2m + CELL_TEMP_IRRADIANCE_FACTOR * irradiance
      power_kw = capacity_kw * (irradiance / 1000) * PERFORMANCE_RATIO *
                 (1 + TEMPERATURE_COEFFICIENT * (cell_temp - STC_TEMPERATURE_C))
      Multiplicative Gaussian noise (3-5%) and random dips for cloud/soiling are added.
      Nighttime output is strictly 0.0 kW, and daytime values are clipped to [0, capacity_kw].
    """
    rng = np.random.default_rng(random_seed)
    irradiance = _get_irradiance_series(weather_df)
    temp_ambient = weather_df["temperature_2m"]

    # 1. Physical baseline
    cell_temp = temp_ambient + config.CELL_TEMP_IRRADIANCE_FACTOR * irradiance
    temp_derating = 1.0 + config.TEMPERATURE_COEFFICIENT * (
        cell_temp - config.STC_TEMPERATURE_C
    )

    base_power = capacity_kw * (irradiance / 1000.0) * config.PERFORMANCE_RATIO * temp_derating
    base_power = base_power.clip(lower=0.0, upper=capacity_kw)

    # 2. Add Gaussian noise (~3-5%) and random cloud/soiling dips to daytime hours only
    daylight_mask = irradiance > 0.0
    daylight_count = daylight_mask.sum()

    power_values = np.zeros(len(weather_df), dtype=float)

    if daylight_count > 0:
        daylight_base = base_power.to_numpy()[daylight_mask]

        # Multiplicative Gaussian noise
        gaussian_noise = rng.normal(1.0, config.SYNTHETIC_NOISE_STD, size=daylight_count)
        noisy_power = daylight_base * gaussian_noise

        # Random dips (cloud pass, localized soiling)
        is_dip = rng.random(size=daylight_count) < config.SYNTHETIC_DIP_PROBABILITY
        dip_fractions = rng.uniform(
            config.SYNTHETIC_DIP_MIN_REDUCTION,
            config.SYNTHETIC_DIP_MAX_REDUCTION,
            size=daylight_count,
        )
        noisy_power[is_dip] *= 1.0 - dip_fractions[is_dip]

        # Clip final noisy values to valid physical limits [0, capacity_kw]
        power_values[daylight_mask] = np.clip(noisy_power, 0.0, capacity_kw)

    # Nighttime values remain exactly 0.0
    return pd.Series(power_values, index=weather_df.index, name="power_kw")


def engineer_features(weather_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Transform raw hourly weather data into machine learning features.

    Features created:
    - Cyclical temporal: hour_sin, hour_cos, day_sin, day_cos
    - Meteorological: irradiance, direct_diffuse_ratio, temperature_2m,
                      cloud_cover, relative_humidity_2m, wind_speed_10m, is_raining
    - Temporal dynamics: irradiance_lag_1h, irradiance_lag_3h, irradiance_rolling_mean_3h

    Returns:
      (X, feature_names) where X has zero NaNs.
    """
    dt_index = pd.DatetimeIndex(weather_df.index)

    # 1. Cyclical time encodings
    hours = dt_index.hour
    day_of_year = dt_index.day_of_year

    hour_sin = np.sin(2.0 * np.pi * hours / 24.0)
    hour_cos = np.cos(2.0 * np.pi * hours / 24.0)
    day_sin = np.sin(2.0 * np.pi * (day_of_year - 1.0) / 365.25)
    day_cos = np.cos(2.0 * np.pi * (day_of_year - 1.0) / 365.25)

    # 2. Meteorological features
    irradiance = _get_irradiance_series(weather_df)
    direct = weather_df.get("direct_radiation", pd.Series(0.0, index=weather_df.index))
    diffuse = weather_df.get("diffuse_radiation", pd.Series(0.0, index=weather_df.index))
    direct_diffuse_ratio = direct / (diffuse + 1.0)

    temperature = weather_df["temperature_2m"]
    cloud_cover = weather_df.get("cloud_cover", pd.Series(0.0, index=weather_df.index))
    humidity = weather_df.get("relative_humidity_2m", pd.Series(50.0, index=weather_df.index))
    wind_speed = weather_df.get("wind_speed_10m", pd.Series(0.0, index=weather_df.index))
    precip = weather_df.get("precipitation", pd.Series(0.0, index=weather_df.index))
    is_raining = (precip > 0.1).astype(float)

    # 3. Lagged and rolling irradiance dynamics
    irradiance_lag_1h = irradiance.shift(1).bfill().fillna(0.0)
    irradiance_lag_3h = irradiance.shift(3).bfill().fillna(0.0)
    irradiance_rolling_mean_3h = (
        irradiance.rolling(window=3, min_periods=1).mean().bfill().fillna(0.0)
    )

    feature_dict = {
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "day_sin": day_sin,
        "day_cos": day_cos,
        "irradiance": irradiance,
        "direct_diffuse_ratio": direct_diffuse_ratio,
        "temperature_2m": temperature,
        "cloud_cover": cloud_cover,
        "relative_humidity_2m": humidity,
        "wind_speed_10m": wind_speed,
        "is_raining": is_raining,
        "irradiance_lag_1h": irradiance_lag_1h,
        "irradiance_lag_3h": irradiance_lag_3h,
        "irradiance_rolling_mean_3h": irradiance_rolling_mean_3h,
    }

    X = pd.DataFrame(feature_dict, index=weather_df.index)

    # Guarantee zero NaNs
    X = X.bfill().ffill().fillna(0.0)

    feature_names = list(X.columns)
    return X, feature_names


def build_training_dataset(
    weather_df: pd.DataFrame,
    capacity_kw: float = config.REFERENCE_PLANT_CAPACITY_KW,
    random_seed: int = 42,
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """
    Construct complete training dataset: feature matrix X, target series y, and feature names.
    """
    X, feature_names = engineer_features(weather_df)
    y = generate_synthetic_power(weather_df, capacity_kw=capacity_kw, random_seed=random_seed)
    return X, y, feature_names
