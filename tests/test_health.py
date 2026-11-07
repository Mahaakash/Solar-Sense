"""
tests/test_health.py
────────────────────
Smoke tests for the /health endpoint.
"""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    """GET /health should return HTTP 200."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_body_is_ok() -> None:
    """GET /health body must be exactly {"status": "ok"}."""
    resp = client.get("/health")
    assert resp.json() == {"status": "ok"}
