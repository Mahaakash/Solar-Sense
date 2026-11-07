"""
backend/services/scheduler.py
─────────────────────────────
Watchdog background execution and APScheduler service for SolarSense.
Automates daily watchdog evaluations across all registered sites and dispatches alerts.
Includes memory-efficient, single-site background runner with JobRun audit persistence.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from backend import config
from backend.db import JobRun, get_session
from backend.services.notifier import dispatch_alerts
from backend.services.watchdog import evaluate_site_health, list_sites

logger = logging.getLogger("solarsense.scheduler")

_scheduler: BackgroundScheduler | None = None


def execute_background_watchdog_run(
    job_run_id: int, lock: Any | None = None
) -> dict[str, Any]:
    """
    Execute watchdog evaluation sequentially across all registered sites in a background thread.

    - Processes sites one at a time.
    - Limits evaluations to the last 45 days (config.WATCHDOG_EVALUATION_DAYS).
    - Logs start, per-site duration, and final summary.
    - Captures per-site errors so one failure does not halt the run.
    - Updates JobRun audit record in database.
    - Releases concurrency lock in a finally block.
    """
    t_start = time.time()
    logger.info("Watchdog background execution started (run_id=%s)", job_run_id)

    total_sites_checked = 0
    total_alerts_created = 0
    notifications_sent: dict[str, int] = {}
    fatal_error: str | None = None

    try:
        sites = list_sites()
        total_sites = len(sites)
        logger.info("Found %d registered site(s) to evaluate.", total_sites)

        for site in sites:
            site_id = site.id
            site_name = site.name
            site_t0 = time.time()
            logger.info("Evaluating site ID %s ('%s')...", site_id, site_name)

            try:
                # Bounded evaluation window (default 45 days)
                alerts = evaluate_site_health(site_id, days=config.WATCHDOG_EVALUATION_DAYS)
                duration = time.time() - site_t0
                count = len(alerts) if alerts else 0
                total_alerts_created += count
                total_sites_checked += 1

                logger.info(
                    "Site ID %s ('%s') evaluated in %.2fs. Alerts diagnosed: %d",
                    site_id, site_name, duration, count,
                )

                if alerts:
                    disp_result = dispatch_alerts(site_name, alerts)
                    for k, v in disp_result.items():
                        notifications_sent[k] = notifications_sent.get(k, 0) + v

            except Exception as site_exc:
                duration = time.time() - site_t0
                logger.error(
                    "Error evaluating site ID %s ('%s') after %.2fs: %s",
                    site_id, site_name, duration, site_exc, exc_info=True,
                )
                # Continue loop — one failing site does NOT abort the remaining sites

        total_duration = time.time() - t_start
        logger.info(
            "Watchdog background run %s finished in %.2fs: %d/%d sites checked, %d alerts created.",
            job_run_id, total_duration, total_sites_checked, total_sites, total_alerts_created,
        )

    except Exception as exc:
        fatal_error = str(exc)
        logger.critical(
            "Fatal failure in watchdog background run %s: %s",
            job_run_id, exc, exc_info=True,
        )

    finally:
        # Update JobRun database record
        try:
            with get_session() as session:
                run_record = session.query(JobRun).filter(JobRun.id == job_run_id).first()
                if run_record:
                    run_record.finished_at = datetime.now(UTC)
                    run_record.sites_checked = total_sites_checked
                    run_record.alerts_created = total_alerts_created
                    if fatal_error:
                        run_record.status = "failed"
                        run_record.error = fatal_error
                    else:
                        run_record.status = "completed"
        except Exception as db_exc:
            logger.error("Failed to update JobRun record %s in DB: %s", job_run_id, db_exc)

        # Release in-process lock
        if lock is not None:
            try:
                lock.release()
                logger.debug("Watchdog job concurrency lock released for run %s", job_run_id)
            except Exception as lock_exc:
                logger.warning("Could not release lock for run %s: %s", job_run_id, lock_exc)

    return {
        "status": "completed" if not fatal_error else "failed",
        "run_id": str(job_run_id),
        "sites_checked": total_sites_checked,
        "alerts_created": total_alerts_created,
        "notifications_sent": notifications_sent,
    }


def run_all_sites_watchdog_check() -> dict[str, Any]:
    """
    Evaluate generation telemetry across all sites (synchronous wrapper for local scheduler).
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
            alerts = evaluate_site_health(site_id, days=config.WATCHDOG_EVALUATION_DAYS)
            if alerts:
                total_alerts += len(alerts)
                disp_result = dispatch_alerts(site_name, alerts)
                for k, v in disp_result.items():
                    notifications_sent[k] = notifications_sent.get(k, 0) + v
        except Exception as exc:
            logger.error(
                "Error evaluating watchdog health for site %s (ID %s): %s",
                site_name, site_id, exc,
            )

    logger.info(
        "Watchdog check complete. Sites screened: %d, Alerts detected: %d",
        total_sites, total_alerts,
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
