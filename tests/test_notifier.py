"""
tests/test_notifier.py
──────────────────────
Test suite for SolarSense alert notification channels, SMTP delivery mocking,
WhatsApp stub behavior, and manual watchdog check endpoints.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas import AlertRead
from backend.services.notifier import (
    EmailNotifier,
    WhatsAppNotifier,
    dispatch_alerts,
)

client = TestClient(app)


@pytest.fixture
def sample_alert() -> AlertRead:
    """Fixture returning a realistic critical fault alert."""
    return AlertRead(
        id=1,
        site_id=1,
        date="2023-03-16",
        severity="critical",
        cause="fault",
        message=(
            "Sudden generation drop of 60% detected on a clear day. "
            "Estimated loss: 95.3 kWh (~₹762.24)."
        ),
        created_at="2026-11-06 19:03:05",
    )


def test_email_notifier_disabled(sample_alert) -> None:
    """When disabled, EmailNotifier skips delivery and returns False."""
    notifier = EmailNotifier(enabled=False, email_to="user@example.com")
    result = notifier.send_alert("Kolkata Demo", sample_alert)
    assert result is False


@patch("smtplib.SMTP")
def test_email_notifier_success(mock_smtp_class, sample_alert) -> None:
    """EmailNotifier connects via TLS, authenticates, and sends structured email."""
    mock_server = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_server

    notifier = EmailNotifier(
        enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="testuser",
        smtp_password="testpassword",
        email_from="alerts@solarsense.local",
        email_to="homeowner@example.com",
    )

    success = notifier.send_alert("Kolkata Demo", sample_alert)
    assert success is True

    # Verify SMTP workflow
    mock_smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=15)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("testuser", "testpassword")
    mock_server.send_message.assert_called_once()

    # Verify message attributes
    sent_msg = mock_server.send_message.call_args[0][0]
    assert "[SolarSense CRITICAL] Kolkata Demo: FAULT Detected" in sent_msg["Subject"]
    assert sent_msg["To"] == "homeowner@example.com"
    payload = sent_msg.get_content()
    assert "Kolkata Demo" in payload
    assert "95.3 kWh" in payload
    assert "₹762.24" in payload


@patch("smtplib.SMTP")
def test_email_notifier_smtp_failure_handled(mock_smtp_class, sample_alert) -> None:
    """SMTP exceptions are trapped and logged without raising unhandled errors."""
    mock_server = MagicMock()
    mock_server.send_message.side_effect = Exception("SMTP timeout error")
    mock_smtp_class.return_value.__enter__.return_value = mock_server

    notifier = EmailNotifier(
        enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        email_to="homeowner@example.com",
    )

    success = notifier.send_alert("Kolkata Demo", sample_alert)
    assert success is False


def test_whatsapp_notifier_stub(sample_alert) -> None:
    """WhatsApp notifier stub logs informational warning and safely returns False."""
    notifier = WhatsAppNotifier(enabled=True)
    success = notifier.send_alert("Kolkata Demo", sample_alert)
    assert success is False


def test_dispatch_alerts_empty() -> None:
    """Dispatching empty alerts list returns zero count without processing."""
    res = dispatch_alerts("Kolkata Demo", [])
    assert res == {"dispatched": 0}


@patch("backend.services.notifier.get_enabled_notifiers")
def test_dispatch_alerts_active(mock_get_notifiers, sample_alert) -> None:
    """Dispatch sends collection of alerts to each active notifier."""
    mock_notifier = MagicMock()
    mock_notifier.send_batch.return_value = 1
    mock_get_notifiers.return_value = [mock_notifier]

    res = dispatch_alerts("Kolkata Demo", [sample_alert])
    assert mock_notifier.send_batch.called
    assert res[mock_notifier.__class__.__name__] == 1


def test_manual_check_endpoints() -> None:
    """Verify POST /watchdog/run-check and POST /sites/{id}/check endpoints."""
    # 1. Register a test site
    site_payload = {
        "name": "Notifier Endpoint Test Site",
        "lat": 13.0827,
        "lon": 80.2707,
        "capacity_kw": 3.0,
        "installed_on": "2023-01-01",
    }
    site_resp = client.post("/sites", json=site_payload)
    assert site_resp.status_code == 200
    site_id = site_resp.json()["id"]

    # 2. Trigger single site check
    site_check_resp = client.post(f"/sites/{site_id}/check")
    assert site_check_resp.status_code == 200
    assert isinstance(site_check_resp.json(), list)

    # 3. Trigger global watchdog check
    global_check_resp = client.post("/watchdog/run-check")
    assert global_check_resp.status_code == 200
    data = global_check_resp.json()
    assert data["status"] == "ok"
    assert data["sites_checked"] >= 1
