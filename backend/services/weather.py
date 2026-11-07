"""
backend/services/weather.py
───────────────────────────
Service for fetching and caching weather data from Open-Meteo APIs.
Provides geocoding, historical weather archive retrieval, and short-term forecasting.
"""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend import config

# Standard hourly variables required for solar yield forecasting
BASE_HOURLY_VARIABLES: list[str] = [
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "temperature_2m",
    "cloud_cover",
    "relative_humidity_2m",
    "wind_speed_10m",
    "precipitation",
]


# ── Custom Exceptions ───────────────────────────────────────────────

class WeatherServiceError(Exception):
    """Base exception for all weather service errors."""


class PlaceNotFoundError(WeatherServiceError):
    """Raised when geocoding cannot find the requested location."""


class WeatherAPIError(WeatherServiceError):
    """Raised when Open-Meteo returns an HTTP error, network failure, or timeout."""


class EmptyDataError(WeatherServiceError):
    """Raised when the API response contains no hourly weather records."""


# ── Internal Helpers ────────────────────────────────────────────────

def _create_http_session() -> requests.Session:
    """Create a requests session with automatic retries and exponential backoff."""
    session = requests.Session()
    retry_strategy = Retry(
        total=config.OPEN_METEO_MAX_RETRIES,
        backoff_factor=config.OPEN_METEO_BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _get_cache_dir() -> Path:
    """Return the raw data cache directory, ensuring it exists."""
    cache_path = Path(config.CACHE_DIR_RAW)
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path


def _load_from_cache(cache_file: Path) -> dict[str, Any] | None:
    """Read cached JSON if the file exists, or return None."""
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_to_cache(cache_file: Path, data: dict[str, Any]) -> None:
    """Save dictionary to disk as formatted JSON."""
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        # Cache write failures should not abort successful API responses
        pass


def _execute_api_request(
    session: requests.Session, url: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Execute GET request with timeout, returning parsed JSON dictionary."""
    try:
        resp = session.get(url, params=params, timeout=config.OPEN_METEO_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        raise WeatherAPIError(f"Open-Meteo request failed for {url}: {exc}") from exc


def _hourly_json_to_dataframe(
    payload: dict[str, Any], tilt: float | None = None
) -> pd.DataFrame:
    """Convert Open-Meteo hourly JSON into a pandas DataFrame with timezone-aware index."""
    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly or not hourly["time"]:
        raise EmptyDataError("Response contains no hourly weather data.")

    df = pd.DataFrame(hourly)

    # Convert time strings to a timezone-aware DatetimeIndex
    timezone_name = payload.get("timezone", "UTC")
    time_series = pd.to_datetime(df["time"])
    try:
        df["time"] = time_series.dt.tz_localize(timezone_name)
    except Exception:
        # If timezone name is unrecognized or already has timezone info, fallback to UTC
        df["time"] = pd.to_datetime(df["time"], utc=True)

    df = df.set_index("time")

    # Tilted-plane irradiance support with fallback to config.TILT_FACTOR
    if "global_tilted_irradiance" not in df.columns:
        if "shortwave_radiation" in df.columns:
            df["global_tilted_irradiance"] = df["shortwave_radiation"] * config.TILT_FACTOR
        else:
            df["global_tilted_irradiance"] = 0.0

    return df


# ── Public Service Functions ────────────────────────────────────────

def geocode(place_name: str) -> tuple[float, float, str]:
    """
    Look up latitude, longitude, and formatted display name for a given location.

    Results are cached on disk in data/raw/.
    """
    clean_name = place_name.strip()
    if not clean_name:
        raise PlaceNotFoundError("Place name cannot be empty.")

    safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", clean_name.lower())
    cache_file = _get_cache_dir() / f"geo_{safe_slug}.json"

    cached_data = _load_from_cache(cache_file)
    if cached_data is not None:
        data = cached_data
    else:
        session = _create_http_session()
        params = {
            "name": clean_name,
            "count": 1,
            "language": "en",
            "format": "json",
        }
        data = _execute_api_request(session, config.OPEN_METEO_GEOCODING_URL, params)
        if data.get("results"):
            _save_to_cache(cache_file, data)

    results = data.get("results")
    if not results:
        raise PlaceNotFoundError(f"Could not find coordinates for place: '{place_name}'")

    top_match = results[0]
    lat = float(top_match["latitude"])
    lon = float(top_match["longitude"])

    # Build human-readable display string
    parts = [
        top_match.get("name"),
        top_match.get("admin1"),
        top_match.get("country"),
    ]
    display_name = ", ".join(p for p in parts if p)

    return lat, lon, display_name


def _fetch_single_range_historical(
    lat: float,
    lon: float,
    start_str: str,
    end_str: str,
    tilt: float | None = None,
    azimuth: float | None = None,
) -> pd.DataFrame:
    """Fetch a single contiguous historical date range (e.g. <= 1 year)."""
    tilt_key = f"{tilt:.1f}" if tilt is not None else "none"
    azim_key = f"{azimuth:.1f}" if azimuth is not None else "none"
    cache_file = (
        _get_cache_dir()
        / f"hist_{lat:.4f}_{lon:.4f}_{start_str}_{end_str}_t{tilt_key}_a{azim_key}.json"
    )

    cached_data = _load_from_cache(cache_file)
    if cached_data is not None:
        data = cached_data
    else:
        session = _create_http_session()
        hourly_vars = list(BASE_HOURLY_VARIABLES)
        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_str,
            "end_date": end_str,
            "timezone": "auto",
        }

        # Request tilted-plane irradiance directly from Open-Meteo if parameters are provided
        if tilt is not None and azimuth is not None:
            hourly_vars.append("global_tilted_irradiance")
            params["tilt"] = tilt
            params["azimuth"] = azimuth

        params["hourly"] = ",".join(hourly_vars)

        data = _execute_api_request(session, config.OPEN_METEO_HISTORICAL_URL, params)
        _save_to_cache(cache_file, data)

    return _hourly_json_to_dataframe(data, tilt=tilt)


def get_historical_weather(
    lat: float,
    lon: float,
    start_date: str | date,
    end_date: str | date,
    tilt: float | None = None,
    azimuth: float | None = None,
) -> pd.DataFrame:
    """
    Fetch hourly historical weather from the Open-Meteo Archive API.

    Automatically chunks multi-year requests into annual requests to prevent
    Open-Meteo 503 throttling on large queries, and caches each year individually.
    Returns a pandas DataFrame indexed by timezone-aware datetime.
    """
    start_dt = (
        start_date if isinstance(start_date, date) else pd.to_datetime(start_date).date()
    )
    end_dt = end_date if isinstance(end_date, date) else pd.to_datetime(end_date).date()

    if start_dt > end_dt:
        msg = f"start_date ({start_dt}) cannot be after end_date ({end_dt})."
        raise ValueError(msg)

    # If query spans across multiple calendar years, chunk year by year
    if start_dt.year < end_dt.year:
        chunks: list[pd.DataFrame] = []
        for year in range(start_dt.year, end_dt.year + 1):
            chunk_start = max(start_dt, date(year, 1, 1))
            chunk_end = min(end_dt, date(year, 12, 31))
            chunk_df = _fetch_single_range_historical(
                lat=lat,
                lon=lon,
                start_str=chunk_start.isoformat(),
                end_str=chunk_end.isoformat(),
                tilt=tilt,
                azimuth=azimuth,
            )
            chunks.append(chunk_df)

        combined = pd.concat(chunks)
        return combined[~combined.index.duplicated(keep="first")]

    return _fetch_single_range_historical(
        lat=lat,
        lon=lon,
        start_str=start_dt.isoformat(),
        end_str=end_dt.isoformat(),
        tilt=tilt,
        azimuth=azimuth,
    )


def get_forecast_weather(
    lat: float,
    lon: float,
    days: int = 3,
    tilt: float | None = None,
    azimuth: float | None = None,
) -> pd.DataFrame:
    """
    Fetch hourly weather forecast from the Open-Meteo Forecast API.

    Results are cached per day (UTC date) so repeating calls on the same day use cache.
    """
    today_utc = datetime.now(UTC).strftime("%Y%m%d")
    tilt_key = f"{tilt:.1f}" if tilt is not None else "none"
    azim_key = f"{azimuth:.1f}" if azimuth is not None else "none"
    cache_file = (
        _get_cache_dir()
        / f"fc_{lat:.4f}_{lon:.4f}_{days}d_{today_utc}_t{tilt_key}_a{azim_key}.json"
    )

    cached_data = _load_from_cache(cache_file)
    if cached_data is not None:
        data = cached_data
    else:
        session = _create_http_session()
        hourly_vars = list(BASE_HOURLY_VARIABLES)
        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "forecast_days": days,
            "timezone": "auto",
        }

        if tilt is not None and azimuth is not None:
            hourly_vars.append("global_tilted_irradiance")
            params["tilt"] = tilt
            params["azimuth"] = azimuth

        params["hourly"] = ",".join(hourly_vars)

        data = _execute_api_request(session, config.OPEN_METEO_FORECAST_URL, params)
        _save_to_cache(cache_file, data)

    return _hourly_json_to_dataframe(data, tilt=tilt)
