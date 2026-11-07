"""
backend/main.py
───────────────
FastAPI application entry-point for SolarSense.
Creates database tables on startup and exposes a /health endpoint.
"""

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import desc

from backend import config
from backend.db import JobRun, engine, get_session, init_db
from backend.models.forecast import load_model, predict_hourly
from backend.schemas import (
    AdvisorRequest,
    AdvisorResponse,
    AlertRead,
    CalibrationResponse,
    DailyForecastItem,
    ForecastResponse,
    HourlyForecastItem,
    ImportReportResponse,
    ReadingsSubmission,
    SiteCreate,
    SiteHealthResponse,
    SiteRead,
)
from backend.services.advisor import calculate_advisor_recommendation
from backend.services.calibration import calibrate_site_ratio
from backend.services.importer import import_readings_csv
from backend.services.notifier import dispatch_alerts
from backend.services.scheduler import (
    execute_background_watchdog_run,
    run_all_sites_watchdog_check,
    shutdown_scheduler,
    start_scheduler,
)
from backend.services.seed import seed_all_demo_sites
from backend.services.watchdog import (
    evaluate_site_health,
    get_site_alerts,
    get_site_by_id,
    get_site_health,
    ingest_readings,
    ingest_readings_csv,
    list_sites,
    register_site,
)
from backend.services.weather import PlaceNotFoundError

logger = logging.getLogger("solarsense")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup tasks (model check, DB init, demo seed & scheduler) before serving."""
    # 1. Verify model artifact exists and can be loaded
    try:
        load_model()
        logger.info("SolarSense forecast model loaded successfully.")
    except Exception as err:
        logger.error("Startup validation failed: %s", err)
        raise

    # 2. Initialize database schema
    init_db()

    # 3. DEMO_MODE: Auto-seed on startup if DB is empty
    if config.DEMO_MODE:
        existing = list_sites()
        if not existing:
            logger.info("DEMO_MODE=true and DB empty. Seeding 8 metropolitan demo sites...")
            try:
                seed_all_demo_sites()
                logger.info("DEMO_MODE auto-seeding completed.")
            except Exception as err:
                logger.error("Failed to auto-seed demo sites: %s", err)

    # 4. Background scheduler (skipped if DISABLE_SCHEDULER=true)
    if config.SCHEDULER_ENABLED:
        start_scheduler()
    else:
        logger.info("APScheduler is disabled (DISABLE_SCHEDULER=true or SCHEDULER_ENABLED=false).")

    yield

    if config.SCHEDULER_ENABLED:
        shutdown_scheduler()


app = FastAPI(
    title="SolarSense API",
    description="Rooftop solar advisor & performance watchdog — India focus.",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health_check() -> dict[str, str]:
    """Return a simple health status confirming the API is alive."""
    return {"status": "ok"}


@app.get("/health/db", tags=["meta"])
def health_db_check() -> dict[str, str]:
    """Run a trivial query to verify database connectivity (for debugging)."""
    from sqlalchemy import text as sa_text

    try:
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        dialect = engine.dialect.name
        return {"status": "ok", "dialect": dialect}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/forecast", response_model=ForecastResponse, tags=["forecast"])
def get_forecast(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees"),
    capacity_kw: float = Query(..., gt=0.0, description="Installed system capacity in kWp"),
    tilt: float = Query(0.0, ge=0.0, le=90.0, description="Panel tilt angle in degrees"),
    azimuth: float = Query(180.0, ge=0.0, le=360.0, description="Panel azimuth (180=South)"),
    days: int = Query(3, ge=1, le=7, description="Forecast window in days"),
) -> ForecastResponse:
    """
    Generate hourly and daily solar power output forecasts for a specified site.

    Returns weather-adjusted generation (kW) and aggregated daily energy production (kWh).
    """
    try:
        hourly_df, daily_df = predict_hourly(
            lat=lat,
            lon=lon,
            capacity_kw=capacity_kw,
            tilt=tilt,
            azimuth=azimuth,
            days=days,
        )
    except FileNotFoundError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(
            status_code=502, detail=f"Failed to generate solar forecast: {err}"
        ) from err

    hourly_items = [
        HourlyForecastItem(
            timestamp=ts.isoformat(),
            predicted_power_kw=float(row["predicted_power_kw"]),
            irradiance=float(row["irradiance"]),
            temperature_2m=float(row["temperature_2m"]),
        )
        for ts, row in hourly_df.iterrows()
    ]

    daily_items = [
        DailyForecastItem(
            date=str(date_key),
            predicted_energy_kwh=float(row["predicted_energy_kwh"]),
            peak_power_kw=float(row["peak_power_kw"]),
        )
        for date_key, row in daily_df.iterrows()
    ]

    return ForecastResponse(
        site_capacity_kw=capacity_kw,
        latitude=lat,
        longitude=lon,
        hourly=hourly_items,
        daily=daily_items,
    )


@app.post("/advisor", response_model=AdvisorResponse, tags=["advisor"])
def get_advisor_recommendation(request: AdvisorRequest) -> AdvisorResponse:
    """
    Rooftop solar pre-installation advisor:
    - Calculates recommended system capacity (kWp) to offset ~85% consumption.
    - Applies roof area constraints if specified (10 m² / kWp).
    - Returns estimated annual generation, electricity bill savings, payback period,
      month-by-month generation, and 25-year cumulative financial trajectory.
    """
    # 1. Input Validation
    if request.monthly_bill_inr <= 0:
        raise HTTPException(
            status_code=400,
            detail="Monthly electricity bill must be greater than zero.",
        )

    if request.roof_area_m2 is not None and request.roof_area_m2 <= 0:
        raise HTTPException(
            status_code=400,
            detail="Roof area must be greater than zero.",
        )

    if request.roof_area_m2 is not None and request.roof_area_m2 > 100_000:
        raise HTTPException(
            status_code=400,
            detail="Roof area exceeds realistic rooftop limits (max 100,000 m²).",
        )

    has_place = bool(request.place_name and request.place_name.strip())
    has_coords = request.lat is not None and request.lon is not None

    if not has_place and not has_coords:
        raise HTTPException(
            status_code=400,
            detail="Either 'place_name' or '(lat, lon)' coordinates must be provided.",
        )

    # 2. Execution & Error Handling
    try:
        return calculate_advisor_recommendation(request)
    except PlaceNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(
            status_code=502, detail=f"Failed to generate solar advisor recommendation: {err}"
        ) from err


# ── Watchdog Endpoints ──────────────────────────────────────────────

@app.post("/sites", response_model=SiteRead, tags=["watchdog"])
def create_site(site: SiteCreate) -> SiteRead:
    """
    Register a rooftop solar installation for post-installation watchdog monitoring.
    """
    try:
        return register_site(site)
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Failed to register site: {err}") from err


@app.get("/sites", response_model=list[SiteRead], tags=["watchdog"])
def list_sites_endpoint() -> list[SiteRead]:
    """
    Retrieve all registered solar installation sites.
    """
    try:
        return list_sites()
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to list sites: {err}") from err


@app.post("/readings", tags=["watchdog"])
async def submit_readings(request: Request) -> dict[str, Any]:
    """
    Submit daily generation readings via JSON or CSV file upload.

    Supported formats:
    - JSON: {"site_id": 1, "readings": [{"date": "2024-01-01", "actual_kwh": 18.5}]}
    - Multipart Form: Form fields 'site_id' and 'file' (CSV with 'date,actual_kwh')
    - Raw CSV body with ?site_id=<id> query parameter
    """
    content_type = request.headers.get("content-type", "")

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            site_id_val = form.get("site_id")
            if not site_id_val:
                raise HTTPException(status_code=400, detail="Missing 'site_id' in form data.")
            file_obj = form.get("file")
            if not file_obj or not hasattr(file_obj, "read"):
                raise HTTPException(status_code=400, detail="Missing 'file' in upload form.")
            content_bytes = await file_obj.read()
            csv_text = content_bytes.decode("utf-8")
            count = ingest_readings_csv(int(site_id_val), csv_text)
            return {"status": "ok", "site_id": int(site_id_val), "readings_ingested": count}

        elif "text/csv" in content_type:
            site_id_param = request.query_params.get("site_id")
            if not site_id_param:
                detail_msg = "Query parameter 'site_id' is required for CSV upload."
                raise HTTPException(status_code=400, detail=detail_msg)
            body_bytes = await request.body()
            csv_text = body_bytes.decode("utf-8")
            count = ingest_readings_csv(int(site_id_param), csv_text)
            return {"status": "ok", "site_id": int(site_id_param), "readings_ingested": count}

        else:
            # Default to JSON payload
            json_body = await request.json()
            submission = ReadingsSubmission.model_validate(json_body)
            count = ingest_readings(submission.site_id, submission.readings)
            return {"status": "ok", "site_id": submission.site_id, "readings_ingested": count}

    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to ingest readings: {err}") from err


@app.post("/readings/import", response_model=ImportReportResponse, tags=["watchdog"])
async def import_readings_endpoint(
    request: Request,
    site_id: int | None = Query(None, description="Site ID to import readings into"),
) -> ImportReportResponse:
    """
    Import real-world solar generation CSV data with automatic column, format, and unit detection.

    Supports:
    - Daily kWh, Interval kWh (summed daily), and Interval kW (integrated to daily kWh).
    - Diverse date formats (ISO, DD/MM/YYYY), thousands commas, Wh/kWh/MWh units.
    - Idempotent upsert to database without duplicates.
    """
    content_type = request.headers.get("content-type", "")
    target_site_id = site_id

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            form_site_id = form.get("site_id")
            if form_site_id:
                try:
                    target_site_id = int(str(form_site_id))
                except ValueError as int_err:
                    raise HTTPException(
                        status_code=400, detail="Form field 'site_id' must be an integer."
                    ) from int_err

            if not target_site_id:
                raise HTTPException(
                    status_code=400, detail="Missing required 'site_id' parameter."
                )

            file_obj = form.get("file")
            if not file_obj or not hasattr(file_obj, "read"):
                raise HTTPException(
                    status_code=400, detail="Missing 'file' field in multipart form upload."
                )

            file_bytes = await file_obj.read()
            report_dict = import_readings_csv(
                site_id=target_site_id,
                content=file_bytes,
                filename=getattr(file_obj, "filename", ""),
            )
            return ImportReportResponse.model_validate(report_dict)

        else:
            # Handle raw CSV body (e.g. curl --data-binary @file.csv /readings/import?site_id=1)
            if not target_site_id:
                raise HTTPException(
                    status_code=400,
                    detail="Query parameter 'site_id' is required when uploading raw CSV data.",
                )

            body_bytes = await request.body()
            if not body_bytes:
                raise HTTPException(status_code=400, detail="Uploaded CSV request body is empty.")

            report_dict = import_readings_csv(
                site_id=target_site_id,
                content=body_bytes,
            )
            return ImportReportResponse.model_validate(report_dict)

    except HTTPException:
        raise
    except ValueError as err:
        err_msg = str(err)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=404, detail=err_msg) from err
        raise HTTPException(status_code=400, detail=err_msg) from err
    except Exception as err:
        logger.error("CSV import failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"CSV import failed: {err}") from err


@app.post("/sites/{site_id}/calibrate", response_model=CalibrationResponse, tags=["watchdog"])
def calibrate_site_endpoint(site_id: int) -> CalibrationResponse:
    """
    Empirically calibrate site Performance Ratio (PR) from clear-sky days.

    Calculates the median (actual / expected) on high-irradiance days and persists it
    to the site record. Subsequent watchdog checks will evaluate health against this baseline.
    """
    try:
        result = calibrate_site_ratio(site_id=site_id)
        return CalibrationResponse.model_validate(result)
    except ValueError as err:
        err_msg = str(err)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=404, detail=err_msg) from err
        raise HTTPException(status_code=400, detail=err_msg) from err
    except Exception as err:
        logger.error("Calibration failed for site %s: %s", site_id, err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Site calibration failed: {err}") from err


@app.get("/sites/{site_id}/health", response_model=SiteHealthResponse, tags=["watchdog"])
def get_site_health_endpoint(site_id: int, days: int = 30) -> SiteHealthResponse:
    """
    Get 30-day health status, expected vs actual generation, 7-day PR, and latest alerts.
    """
    try:
        return get_site_health(site_id=site_id, days=days)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to fetch site health: {err}") from err


@app.get("/sites/{site_id}/alerts", response_model=list[AlertRead], tags=["watchdog"])
def get_site_alerts_endpoint(site_id: int) -> list[AlertRead]:
    """
    Retrieve historical and active alerts diagnosed for a site.
    """
    try:
        return get_site_alerts(site_id)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to fetch alerts: {err}") from err


@app.post("/watchdog/run-check", tags=["watchdog"])
def run_watchdog_check_endpoint() -> dict[str, Any]:
    """
    Manually trigger watchdog health evaluation across all registered sites.
    """
    try:
        return run_all_sites_watchdog_check()
    except Exception as err:
        raise HTTPException(
            status_code=500, detail=f"Failed to execute global watchdog check: {err}"
        ) from err


@app.post("/sites/{site_id}/check", response_model=list[AlertRead], tags=["watchdog"])
def check_site_health_endpoint(site_id: int) -> list[AlertRead]:
    """
    Manually trigger watchdog evaluation for a single installation site.
    """
    try:
        site = get_site_by_id(site_id)
        alerts = evaluate_site_health(site_id)
        if alerts:
            dispatch_alerts(site["name"], alerts)
        return alerts
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(
            status_code=500, detail=f"Failed to execute health check for site {site_id}: {err}"
        ) from err


_watchdog_job_lock = threading.Lock()


@app.post("/jobs/run-watchdog", tags=["jobs"])
def run_cron_watchdog_endpoint(
    request: Request, background_tasks: BackgroundTasks
) -> JSONResponse:
    """
    Automated cron webhook endpoint to trigger watchdog evaluation across all sites.
    Validates X-Cron-Secret, checks concurrency lock, logs JobRun, and dispatches background task.
    Returns HTTP 202 immediately to prevent timeout on free-tier hosts.
    """
    cron_header = request.headers.get("X-Cron-Secret")
    if not cron_header or cron_header != config.CRON_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing or invalid X-Cron-Secret header",
        )

    # Concurrency check: prevent overlapping executions
    if not _watchdog_job_lock.acquire(blocking=False):
        logger.warning("Watchdog job trigger ignored: a previous run is already in progress.")
        return JSONResponse(status_code=202, content={"status": "already_running"})

    # Provision JobRun database record
    try:
        with get_session() as session:
            job_run = JobRun(status="running")
            session.add(job_run)
            session.flush()
            run_id_val = job_run.id
            run_id_str = str(run_id_val)
    except Exception as exc:
        _watchdog_job_lock.release()
        logger.error("Failed to initialize JobRun audit record: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Failed to initialize job run record: {exc}"
        ) from exc

    # Enqueue background task
    background_tasks.add_task(
        execute_background_watchdog_run, run_id_val, _watchdog_job_lock
    )

    return JSONResponse(
        status_code=202,
        content={"status": "started", "run_id": run_id_str},
    )


@app.get("/jobs/status", tags=["jobs"])
def get_job_status_endpoint(request: Request) -> dict[str, Any]:
    """
    Return status and diagnostic summary for the latest watchdog background run.
    Requires 'X-Cron-Secret' header matching CRON_SECRET environment variable.
    """
    cron_header = request.headers.get("X-Cron-Secret")
    if not cron_header or cron_header != config.CRON_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing or invalid X-Cron-Secret header",
        )

    with get_session() as session:
        latest = session.query(JobRun).order_by(desc(JobRun.id)).first()
        if not latest:
            return {"status": "no_runs_found"}

        return {
            "id": latest.id,
            "run_id": str(latest.id),
            "status": latest.status,
            "started_at": latest.started_at.isoformat() if latest.started_at else None,
            "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
            "sites_checked": latest.sites_checked,
            "alerts_created": latest.alerts_created,
            "error": latest.error,
        }
