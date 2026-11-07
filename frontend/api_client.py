"""
frontend/api_client.py
──────────────────────
Centralized HTTP client for communicating with the SolarSense FastAPI backend.
- Resolves backend URL dynamically from st.secrets, BACKEND_URL environment variable, or defaults to http://localhost:8000.
- Implements automated retry logic with a waking spinner for free-tier cloud platforms (e.g., Render spindown).
"""

import os
import time
from typing import Any

import requests

DEFAULT_TIMEOUT = 30  # seconds
MAX_WAKEUP_RETRIES = 3
RETRY_DELAY_SECONDS = 8


def get_backend_url() -> str:
    """Resolve the FastAPI backend URL from Streamlit secrets, environment, or default."""
    try:
        import streamlit as st

        if hasattr(st, "secrets") and "BACKEND_URL" in st.secrets:
            return str(st.secrets["BACKEND_URL"]).rstrip("/")
    except Exception:
        pass

    return os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")


BASE_URL = get_backend_url()


class ApiClientError(Exception):
    """Raised when an API request to the backend fails."""


def _handle_request(method: str, path: str, allow_retry: bool = True, **kwargs: Any) -> Any:
    """
    Execute an HTTP request with error handling.
    If the backend is sleeping/unresponsive, retries up to 3 times with an informative waking spinner.
    """
    base = get_backend_url()
    url = f"{base}{path}"
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

    max_attempts = MAX_WAKEUP_RETRIES if allow_retry else 1

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.request(method, url, **kwargs)
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as err:
            if attempt < max_attempts:
                # Display waking notification in Streamlit UI if available
                try:
                    import streamlit as st

                    with st.spinner(
                        f"Backend is waking up, this can take up to a minute (attempt {attempt}/{max_attempts})..."
                    ):
                        time.sleep(RETRY_DELAY_SECONDS)
                except Exception:
                    time.sleep(3)
            else:
                msg = (
                    f"Backend is not responding at {base}. "
                    "If hosted on Render free tier, the service may take up to a minute to wake up. "
                    "Please refresh the page in a moment."
                )
                raise ApiClientError(msg) from err
        except Exception as err:
            msg = f"Network error contacting backend: {err}"
            raise ApiClientError(msg) from err

    if not response.ok:
        try:
            err_data = response.json()
            detail = err_data.get("detail", response.text)
        except Exception:
            detail = response.text or f"HTTP {response.status_code}"
        raise ApiClientError(f"{detail}")

    try:
        return response.json()
    except Exception as err:
        raise ApiClientError(f"Invalid JSON returned from {path}: {err}") from err


def check_health() -> bool:
    """Check whether the backend is alive and responding (fast non-blocking probe)."""
    try:
        data = _handle_request("GET", "/health", allow_retry=False, timeout=4)
        return bool(data.get("status") == "ok")
    except Exception:
        return False


def get_advisor_recommendation(
    place: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    monthly_bill_inr: float = 3000.0,
    roof_area_m2: float | None = None,
    tilt: float | None = None,
    azimuth: float | None = None,
) -> dict[str, Any]:
    """Request pre-installation rooftop solar sizing & financial returns."""
    payload: dict[str, Any] = {"monthly_bill_inr": monthly_bill_inr}
    if place:
        payload["place_name"] = place
    if lat is not None and lon is not None:
        payload["lat"] = lat
        payload["lon"] = lon
    if roof_area_m2 and roof_area_m2 > 0:
        payload["roof_area_m2"] = roof_area_m2
    if tilt is not None:
        payload["tilt"] = tilt
    if azimuth is not None:
        payload["azimuth"] = azimuth

    return _handle_request("POST", "/advisor", json=payload)


def list_sites() -> list[dict[str, Any]]:
    """Retrieve all registered solar installations."""
    return _handle_request("GET", "/sites")


def register_site(
    name: str,
    lat: float,
    lon: float,
    capacity_kw: float,
    installed_on: str,
    tilt: float = 20.0,
    azimuth: float = 180.0,
    user_id: int = 1,
) -> dict[str, Any]:
    """Register a new rooftop solar site for watchdog monitoring."""
    payload = {
        "user_id": user_id,
        "name": name,
        "lat": lat,
        "lon": lon,
        "capacity_kw": capacity_kw,
        "tilt": tilt,
        "azimuth": azimuth,
        "installed_on": installed_on,
    }
    return _handle_request("POST", "/sites", json=payload)


def submit_readings_json(site_id: int, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Submit a batch of daily readings as JSON."""
    payload = {"site_id": site_id, "readings": readings}
    return _handle_request("POST", "/readings", json=payload)


def upload_readings_csv(
    site_id: int, csv_bytes: bytes, filename: str = "readings.csv"
) -> dict[str, Any]:
    """Upload a CSV of daily readings via multipart form."""
    files = {"file": (filename, csv_bytes, "text/csv")}
    data = {"site_id": str(site_id)}
    return _handle_request("POST", "/readings", data=data, files=files)


def get_site_health(site_id: int, days: int = 30) -> dict[str, Any]:
    """Fetch expected vs actual generation, 7-day PR, and recent alerts for a site."""
    return _handle_request("GET", f"/sites/{site_id}/health?days={days}")


def get_site_alerts(site_id: int) -> list[dict[str, Any]]:
    """Fetch historical alerts diagnosed by the watchdog engine for a site."""
    return _handle_request("GET", f"/sites/{site_id}/alerts")


def trigger_site_check(site_id: int) -> list[dict[str, Any]]:
    """Trigger an immediate watchdog health check for a single site."""
    return _handle_request("POST", f"/sites/{site_id}/check")


def trigger_global_watchdog_check() -> dict[str, Any]:
    """Trigger an immediate watchdog health check across all registered sites."""
    return _handle_request("POST", "/watchdog/run-check")
