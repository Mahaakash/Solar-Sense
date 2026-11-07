"""
tests/test_deployment.py
─────────────────────────
Tests for cloud deployment endpoints and configurations:
- Protected cron webhook endpoint (POST /jobs/run-watchdog).
- Model load validation and error messages.
- Frontend API client URL resolution.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import config
from backend.main import app
from frontend.api_client import get_backend_url

client = TestClient(app)


def test_cron_watchdog_missing_secret_returns_401() -> None:
    """POST /jobs/run-watchdog without X-Cron-Secret header must be rejected with HTTP 401."""
    resp = client.post("/jobs/run-watchdog")
    assert resp.status_code == 401
    assert "Missing or invalid X-Cron-Secret header" in resp.json()["detail"]


def test_cron_watchdog_invalid_secret_returns_401() -> None:
    """POST /jobs/run-watchdog with incorrect secret must be rejected with HTTP 401."""
    resp = client.post("/jobs/run-watchdog", headers={"X-Cron-Secret": "wrong-secret-token"})
    assert resp.status_code == 401
    assert "Missing or invalid X-Cron-Secret header" in resp.json()["detail"]


def test_cron_watchdog_valid_secret_runs_check() -> None:
    """POST /jobs/run-watchdog with matching X-Cron-Secret header executes successfully."""
    with patch("backend.main.run_all_sites_watchdog_check") as mock_check:
        mock_check.return_value = {"sites_checked": 8, "alerts_created": 3}
        resp = client.post(
            "/jobs/run-watchdog",
            headers={"X-Cron-Secret": config.CRON_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["summary"]["sites_checked"] == 8
        assert data["summary"]["alerts_created"] == 3


def test_frontend_backend_url_resolution() -> None:
    """Frontend api_client should correctly resolve backend URL from environment."""
    with patch.dict("os.environ", {"BACKEND_URL": "https://solarsense-api.onrender.com/"}):
        assert get_backend_url() == "https://solarsense-api.onrender.com"
