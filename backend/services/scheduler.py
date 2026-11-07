"""
backend/services/scheduler.py
─────────────────────────────
APScheduler background service for SolarSense.
Automates daily watchdog evaluations across all registered sites and dispatches alerts.
"""

import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from backend import config
from backend.services.notifier import dispatch_alerts
from backend.services.watchdog import evaluate_site_health, list_sites

logger = logging.getLogger("solarsense.scheduler")

_scheduler: BackgroundScheduler | None = None


def run_all_sites_watchdog_check() -> dict[str, Any]:
    """
    Evaluate generation telemetry against weather predictions for all registered sites.
    Dispatches alerts to configured notification channels (Email, WhatsApp).
    """
    logger.info("Executing scheduled watchdog screening across all registered sites...")
    sites = list_sites()
    total_sites = len(sites)
    total_alerts = 0
    notifications_sent: dict[str, int] = {}

    for site in sites:
        site_id = site.id
        site_name = site.name
        try:
            alerts = evaluate_site_health(site_id)
            if alerts:
                total_alerts += len(alerts)
                disp_result = dispatch_alerts(site_name, alerts)
                for k, v in disp_result.items():
                    notifications_sent[k] = notifications_sent.get(k, 0) + v
        except Exception as exc:
            logger.error(
                "Error evaluating watchdog health for site %s (ID %s): %s",
                site_name,
                site_id,
                exc,
            )

    logger.info(
        "Watchdog check complete. Sites screened: %d, Alerts detected: %d",
        total_sites,
        total_alerts,
    )
    return {
        "status": "ok",
        "sites_checked": total_sites,
        "alerts_found": total_alerts,
        "notifications_sent": notifications_sent,
    }


def start_scheduler() -> BackgroundScheduler | None:
    """Initialize and start the background watchdog scheduler if enabled."""
    global _scheduler
    if not config.SCHEDULER_ENABLED:
        logger.info("Watchdog APScheduler is disabled (SCHEDULER_ENABLED=False).")
        return None

    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)
    # Schedule daily check at the configured hour (default 21:00 / 9 PM local time)
    _scheduler.add_job(
        run_all_sites_watchdog_check,
        trigger="cron",
        hour=config.WATCHDOG_DAILY_RUN_HOUR,
        minute=0,
        id="daily_watchdog_evaluation",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Watchdog APScheduler started successfully. Scheduled daily at %02d:00.",
        config.WATCHDOG_DAILY_RUN_HOUR,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    """Gracefully terminate background scheduler on application shutdown."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Watchdog APScheduler stopped.")
        _scheduler = None
