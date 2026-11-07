"""
backend/services/notifier.py
────────────────────────────
Alert notification delivery subsystem for SolarSense.
Supports:
1. Abstract Notifier base class.
2. EmailNotifier: production-ready SMTP delivery using Python standard library smtplib.
3. WhatsAppNotifier: Twilio-ready stub, disabled by default and clearly marked as not implemented.
4. Dispatcher: sends newly diagnosed watchdog alerts across all enabled channels.
"""

import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any

from backend import config
from backend.schemas import AlertRead

logger = logging.getLogger("solarsense.notifier")


class Notifier(ABC):
    """Abstract base class for all SolarSense alert delivery channels."""

    @abstractmethod
    def send_alert(self, site_name: str, alert: AlertRead | dict[str, Any]) -> bool:
        """
        Deliver a single diagnosed alert.

        Returns True if successfully dispatched, False otherwise.
        """

    def send_batch(self, site_name: str, alerts: list[AlertRead | dict[str, Any]]) -> int:
        """
        Deliver a collection of alerts for a given site.

        Returns the number of alerts successfully sent.
        """
        sent_count = 0
        for alert in alerts:
            if self.send_alert(site_name, alert):
                sent_count += 1
        return sent_count


class EmailNotifier(Notifier):
    """
    SMTP Email notification service using standard library smtplib.
    Credentials and configuration are loaded from environment variables via backend/config.py.
    """

    def __init__(
        self,
        enabled: bool | None = None,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        email_from: str | None = None,
        email_to: str | None = None,
    ) -> None:
        self.enabled = config.EMAIL_ENABLED if enabled is None else enabled
        self.smtp_host = smtp_host or config.SMTP_HOST
        self.smtp_port = smtp_port or config.SMTP_PORT
        self.smtp_user = smtp_user or config.SMTP_USER
        self.smtp_password = smtp_password or config.SMTP_PASSWORD
        self.email_from = email_from or config.EMAIL_FROM
        self.email_to = email_to or config.EMAIL_TO

    def send_alert(self, site_name: str, alert: AlertRead | dict[str, Any]) -> bool:
        """Format and send an alert notification via SMTP."""
        if not self.enabled:
            logger.info("Email notifications disabled (EMAIL_ENABLED=False). Skipping.")
            return False

        if not self.email_to or not self.smtp_host:
            logger.warning("Email recipient (EMAIL_TO) or SMTP_HOST missing. Skipping.")
            return False

        alert_data = alert.model_dump() if isinstance(alert, AlertRead) else dict(alert)
        severity = str(alert_data.get("severity", "WARNING")).upper()
        cause = str(alert_data.get("cause", "UNDERPERFORMANCE")).upper()
        alert_date = str(alert_data.get("date", ""))
        message_body = str(alert_data.get("message", ""))

        subject = f"[SolarSense {severity}] {site_name}: {cause} Detected on {alert_date}"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = self.email_to

        content_text = (
            f"SolarSense Performance Watchdog Alert\n"
            f"{'=' * 45}\n\n"
            f"Site Name:   {site_name}\n"
            f"Date:        {alert_date}\n"
            f"Severity:    {severity}\n"
            f"Diagnosis:   {cause}\n\n"
            f"Diagnostic Message:\n{message_body}\n\n"
            f"{'=' * 45}\n"
            f"View live telemetry and graphs at your SolarSense dashboard.\n"
        )
        msg.set_content(content_text)

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            logger.info("Email alert successfully sent to %s for %s", self.email_to, site_name)
            return True
        except Exception as exc:
            logger.error("Failed to deliver email alert to %s: %s", self.email_to, exc)
            return False


class WhatsAppNotifier(Notifier):
    """
    Twilio WhatsApp notification stub.
    Disabled by default and clearly marked as not implemented.
    """

    def __init__(
        self,
        enabled: bool | None = None,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        to_number: str | None = None,
    ) -> None:
        self.enabled = config.WHATSAPP_ENABLED if enabled is None else enabled
        self.account_sid = account_sid or config.TWILIO_ACCOUNT_SID
        self.auth_token = auth_token or config.TWILIO_AUTH_TOKEN
        self.from_number = from_number or config.TWILIO_WHATSAPP_NUMBER
        self.to_number = to_number or config.WHATSAPP_TO

    def send_alert(self, site_name: str, alert: AlertRead | dict[str, Any]) -> bool:
        """Stub method indicating WhatsApp delivery is not yet implemented."""
        logger.info(
            "WhatsApp alert delivery is a stub (not implemented). "
            "To enable production delivery, configure Twilio credentials in .env. "
            "Alert for '%s' was skipped.",
            site_name,
        )
        return False


def get_enabled_notifiers() -> list[Notifier]:
    """Return all active notifiers based on current configuration."""
    active: list[Notifier] = []
    email_notifier = EmailNotifier()
    if email_notifier.enabled:
        active.append(email_notifier)

    whatsapp_notifier = WhatsAppNotifier()
    if whatsapp_notifier.enabled:
        active.append(whatsapp_notifier)

    return active


def dispatch_alerts(
    site_name: str, alerts: list[AlertRead | dict[str, Any]]
) -> dict[str, int]:
    """
    Deliver alerts across all active notifiers.
    Returns dictionary with counts of successfully dispatched notifications per channel.
    """
    if not alerts:
        return {"dispatched": 0}

    results: dict[str, int] = {}
    for notifier in get_enabled_notifiers():
        channel_name = notifier.__class__.__name__
        sent = notifier.send_batch(site_name, alerts)
        results[channel_name] = sent

    return results

