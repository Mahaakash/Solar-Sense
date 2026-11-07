"""
tests/test_deployment.py
─────────────────────────
Tests for cloud deployment endpoints and background watchdog execution:
- Protected cron webhook endpoint (POST /jobs/run-watchdog):
  - HTTP 401 on missing or incorrect secret.
  - HTTP 202 immediately with {"status": "started", "run_id": "..."}.
  - HTTP 202 with {"status": "already_running"} on overlapping runs.
- GET /jobs/status returning latest job_runs audit status.
- Error containment: one failing site does not halt evaluation for others.
- Frontend API client URL resolution.
"""

import contextlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.db import JobRun, get_session, init_db
from backend.main import _watchdog_job_lock, app
from backend.schemas import AlertRead, SiteRead
from backend.services.scheduler import execute_background_watchdog_run
from frontend.api_client import get_backend_url

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure clean database tables and reset concurrency lock before each test."""
    init_db()
    # Ensure lock is released if held by previous test
    if _watchdog_job_lock.locked():
        with contextlib.suppress(RuntimeError):
            _watchdog_job_lock.release()


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


def test_cron_watchdog_returns_202_immediately() -> None:
    """POST /jobs/run-watchdog returns HTTP 202 immediately with status started and run_id."""
    with patch("backend.main.execute_background_watchdog_run"):
        resp = client.post(
            "/jobs/run-watchdog",
            headers={"X-Cron-Secret": config.CRON_SECRET},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "started"
        assert "run_id" in data
        assert isinstance(data["run_id"], str)

        # Verify JobRun was recorded in database
        with get_session() as session:
            run_rec = session.query(JobRun).filter(JobRun.id == int(data["run_id"])).first()
            assert run_rec is not None
            assert run_rec.status == "running"

    # Clean up lock acquired during test
    if _watchdog_job_lock.locked():
        _watchdog_job_lock.release()


def test_cron_watchdog_prevents_overlapping_runs() -> None:
    """Second request while a job is running returns HTTP 202 with status already_running."""
    # Manually acquire the lock to simulate an active background run
    assert _watchdog_job_lock.acquire(blocking=False) is True
    try:
        resp = client.post(
            "/jobs/run-watchdog",
            headers={"X-Cron-Secret": config.CRON_SECRET},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "already_running"
    finally:
        _watchdog_job_lock.release()


def test_failing_site_does_not_stop_others() -> None:
    """One site throwing an exception must not stop remaining sites from being evaluated."""
    from datetime import date

    # Create dummy sites
    site1 = SiteRead(
        id=101, user_id=1, name="Site A (Healthy)", lat=22.5, lon=88.3,
        capacity_kw=5.0, tilt=20.0, azimuth=180.0, installed_on=date(2022, 1, 1),
    )
    site2 = SiteRead(
        id=102, user_id=1, name="Site B (Failing)", lat=28.6, lon=77.2,
        capacity_kw=10.0, tilt=28.0, azimuth=180.0, installed_on=date(2022, 1, 1),
    )
    site3 = SiteRead(
        id=103, user_id=1, name="Site C (Healthy)", lat=19.0, lon=72.8,
        capacity_kw=6.0, tilt=19.0, azimuth=180.0, installed_on=date(2022, 1, 1),
    )

    alert1 = AlertRead(
        id=1, site_id=101, date="2023-01-10", severity="info",
        cause="insufficient_data", message="Testing alert", created_at="2023-01-10 12:00:00",
    )

    def mock_eval(site_id: int, days: int = 45):
        if site_id == 101:
            return [alert1]
        elif site_id == 102:
            raise RuntimeError("Simulated Open-Meteo timeout for Site B")
        elif site_id == 103:
            return []
        return []

    # Provision JobRun record
    with get_session() as session:
        job = JobRun(status="running")
        session.add(job)
        session.flush()
        job_id = job.id

    with (
        patch("backend.services.scheduler.list_sites", return_value=[site1, site2, site3]),
        patch("backend.services.scheduler.evaluate_site_health", side_effect=mock_eval),
        patch("backend.services.scheduler.dispatch_alerts", return_value={"Email": 1}),
    ):
        result = execute_background_watchdog_run(job_id)

    assert result["status"] == "completed"
    assert result["sites_checked"] == 2  # site1 and site3 checked successfully
    assert result["alerts_created"] == 1

    # Verify audit record in database
    with get_session() as session:
        record = session.query(JobRun).filter(JobRun.id == job_id).first()
        assert record is not None
        assert record.status == "completed"
        assert record.sites_checked == 2
        assert record.alerts_created == 1
        assert record.finished_at is not None


def test_jobs_status_endpoint() -> None:
    """GET /jobs/status validates secret and returns latest JobRun state."""
    # 1. Unauthorized without secret
    resp_unauth = client.get("/jobs/status")
    assert resp_unauth.status_code == 401

    # 2. Authorized check
    with get_session() as session:
        run = JobRun(
            status="completed",
            sites_checked=8,
            alerts_created=3,
        )
        session.add(run)
        session.flush()
        expected_run_id = str(run.id)

    resp = client.get(
        "/jobs/status",
        headers={"X-Cron-Secret": config.CRON_SECRET},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["run_id"] == expected_run_id
    assert data["sites_checked"] == 8
    assert data["alerts_created"] == 3


def test_frontend_backend_url_resolution() -> None:
    """Frontend api_client should correctly resolve backend URL from environment."""
    with patch.dict("os.environ", {"BACKEND_URL": "https://solarsense-api.onrender.com/"}):
        assert get_backend_url() == "https://solarsense-api.onrender.com"
