"""
backend/services/watchdog.py
────────────────────────────
SolarSense Watchdog diagnostic and monitoring service:
- Site registration and daily reading ingestion (JSON and CSV).
- Expected output computation using the weather-adjusted ML forecasting model.
- Performance Ratio (PR) tracking and 7-day rolling evaluation.
- Plain-language diagnostic alerts for Sudden Fault, Dust/Soiling (with rain forecast),
  Ageing, and Insufficient Data, quantifying energy (kWh) and monetary (INR) loss.
- Alert deduplication to prevent alerting fatigue.
"""

import csv
import io
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc

from backend import config
from backend.db import Alert, DailyReading, Site, User, get_session
from backend.models.forecast import predict_for_dates
from backend.schemas import (
    AlertRead,
    DailyHealthItem,
    ReadingInputItem,
    SiteCreate,
    SiteHealthResponse,
    SiteRead,
)
from backend.services.weather import get_forecast_weather, get_historical_weather

# ── Database Helpers ────────────────────────────────────────────────


def _ensure_default_user_exists(session, user_id: int = 1) -> None:
    """Ensure a default user exists so site foreign keys are always satisfied."""
    existing = session.query(User).filter(User.id == user_id).first()
    if existing is None:
        session.add(User(id=user_id, name="Demo Owner", email="owner@solarsense.in"))
        session.flush()


def register_site(site_data: SiteCreate) -> SiteRead:
    """Insert a new site and return SiteRead."""
    with get_session() as session:
        _ensure_default_user_exists(session, site_data.user_id)
        installed_d = (
            site_data.installed_on
            if isinstance(site_data.installed_on, date)
            else date.fromisoformat(str(site_data.installed_on))
        )
        site = Site(
            user_id=site_data.user_id,
            name=site_data.name,
            lat=site_data.lat,
            lon=site_data.lon,
            capacity_kw=site_data.capacity_kw,
            tilt=site_data.tilt,
            azimuth=site_data.azimuth,
            installed_on=installed_d,
        )
        session.add(site)
        session.flush()
        return SiteRead(
            id=site.id,
            user_id=site.user_id,
            name=site.name,
            lat=site.lat,
            lon=site.lon,
            capacity_kw=site.capacity_kw,
            tilt=site.tilt,
            azimuth=site.azimuth,
            installed_on=installed_d,
            calibrated_performance_ratio=site.calibrated_performance_ratio,
        )


def get_site_by_id(site_id: int) -> dict[str, Any]:
    """Retrieve site record as a dictionary or raise ValueError."""
    with get_session() as session:
        site = session.query(Site).filter(Site.id == site_id).first()
        if site is None:
            msg = f"Site with ID {site_id} not found."
            raise ValueError(msg)
        inst_str = (
            site.installed_on.isoformat()
            if hasattr(site.installed_on, "isoformat")
            else str(site.installed_on)
        )
        return {
            "id": site.id,
            "user_id": site.user_id,
            "name": site.name,
            "lat": site.lat,
            "lon": site.lon,
            "capacity_kw": site.capacity_kw,
            "tilt": site.tilt,
            "azimuth": site.azimuth,
            "installed_on": inst_str,
            "calibrated_performance_ratio": site.calibrated_performance_ratio,
        }


def list_sites() -> list[SiteRead]:
    """Retrieve all registered sites ordered by ID descending."""
    with get_session() as session:
        rows = session.query(Site).order_by(desc(Site.id)).all()
        return [
            SiteRead(
                id=int(r.id),
                user_id=int(r.user_id),
                name=str(r.name),
                lat=float(r.lat),
                lon=float(r.lon),
                capacity_kw=float(r.capacity_kw),
                tilt=float(r.tilt),
                azimuth=float(r.azimuth),
                installed_on=pd.to_datetime(r.installed_on).date(),
                calibrated_performance_ratio=r.calibrated_performance_ratio,
            )
            for r in rows
        ]


# ── Reading Ingestion ───────────────────────────────────────────────

def ingest_readings(site_id: int, readings: list[ReadingInputItem]) -> int:
    """
    Upsert daily readings and trigger watchdog health evaluation.
    Uses select-then-update pattern for cross-dialect compatibility.
    """
    get_site_by_id(site_id)  # Validate site exists
    if not readings:
        return 0

    with get_session() as session:
        for r in readings:
            d_val = r.date if isinstance(r.date, date) else date.fromisoformat(str(r.date))
            existing = (
                session.query(DailyReading)
                .filter(DailyReading.site_id == site_id, DailyReading.date == d_val)
                .first()
            )
            if existing:
                existing.actual_kwh = float(r.actual_kwh)
            else:
                session.add(
                    DailyReading(
                        site_id=site_id,
                        date=d_val,
                        actual_kwh=float(r.actual_kwh),
                    )
                )
        session.flush()

    # Trigger diagnostic evaluation after new readings are stored
    evaluate_site_health(site_id)
    return len(readings)


def ingest_readings_csv(site_id: int, csv_content: str) -> int:
    """
    Parse a CSV string containing columns 'date' and 'actual_kwh' and store readings.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "date" not in fieldnames or "actual_kwh" not in fieldnames:
        msg = "CSV must contain 'date' and 'actual_kwh' columns."
        raise ValueError(msg)

    items: list[ReadingInputItem] = []
    for row in reader:
        # Standardize keys
        clean_row = {k.strip().lower(): v for k, v in row.items() if k}
        d_val = pd.to_datetime(clean_row["date"]).date()
        kwh_val = float(clean_row["actual_kwh"])
        items.append(ReadingInputItem(date=d_val, actual_kwh=kwh_val))

    return ingest_readings(site_id, items)


# ── Alert Deduplication & Persistence ───────────────────────────────

def _insert_alert_if_not_duplicate(
    session,
    site_id: int,
    alert_date: str | date,
    severity: str,
    cause: str,
    message: str,
) -> bool:
    """
    Insert alert unless an identical cause was logged within deduplication window.
    """
    d_val = alert_date if isinstance(alert_date, date) else date.fromisoformat(str(alert_date))
    latest = (
        session.query(Alert)
        .filter(Alert.site_id == site_id, Alert.cause == cause)
        .order_by(desc(Alert.id))
        .first()
    )
    if latest is not None:
        latest_date = pd.to_datetime(latest.date).date()
        days_diff = (d_val - latest_date).days
        if 0 <= days_diff < config.ALERT_DEDUPLICATION_DAYS:
            # Active ongoing alert exists within deduplication window
            return False

    session.add(
        Alert(
            site_id=site_id,
            date=d_val,
            severity=severity,
            cause=cause,
            message=message,
        )
    )
    session.flush()
    return True


# ── Watchdog Diagnostic Engine ──────────────────────────────────────

def evaluate_site_health(
    site_id: int, days: int | None = None
) -> list[AlertRead]:
    """
    Run diagnostic rules on recent site readings against weather-adjusted expected yield.
    Limits evaluation to the most recent `days` (defaults to config.WATCHDOG_EVALUATION_DAYS).
    """
    eval_days = config.WATCHDOG_EVALUATION_DAYS if days is None else days
    site = get_site_by_id(site_id)
    capacity_kw = float(site["capacity_kw"])
    tilt = float(site["tilt"])
    azimuth = float(site["azimuth"])
    lat = float(site["lat"])
    lon = float(site["lon"])
    installed_on = pd.to_datetime(site["installed_on"]).date()

    with get_session() as session:
        query = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == site_id)
            .order_by(desc(DailyReading.date))
        )
        if eval_days and eval_days > 0:
            query = query.limit(eval_days)
        rows = query.all()
        if not rows:
            return []

        rows = list(reversed(rows))

        readings_df = pd.DataFrame(
            [{"date": r.date, "actual_kwh": r.actual_kwh} for r in rows]
        )
        readings_df["date"] = pd.to_datetime(readings_df["date"]).dt.date
        readings_df = readings_df.sort_values("date").reset_index(drop=True)

        start_date = readings_df["date"].min()
        end_date = readings_df["date"].max()

        # 1. Compute expected generation for each day using model
        _, daily_expected_df = predict_for_dates(
            lat=lat,
            lon=lon,
            capacity_kw=capacity_kw,
            tilt=tilt,
            azimuth=azimuth,
            start_date=start_date,
            end_date=end_date,
        )

        expected_map = daily_expected_df["predicted_energy_kwh"].to_dict()

        readings_df["expected_kwh"] = [
            float(expected_map.get(d.isoformat(), 0.0)) for d in readings_df["date"]
        ]

        # Calculate daily Performance Ratio (actual / expected)
        # Skip days with very low expected generation to eliminate overcast noise
        readings_df["pr"] = np.where(
            readings_df["expected_kwh"] >= config.MIN_EXPECTED_DAILY_KWH,
            readings_df["actual_kwh"] / readings_df["expected_kwh"],
            np.nan,
        )

        n_records = len(readings_df)
        latest_date_str = readings_df["date"].iloc[-1].isoformat()

        # ── Rule 0: Insufficient Data Check ─────────────────────────
        valid_pr_count = readings_df["pr"].notnull().sum()
        if valid_pr_count < 7:
            _insert_alert_if_not_duplicate(
                session=session,
                site_id=site_id,
                alert_date=latest_date_str,
                severity="info",
                cause="insufficient_data",
                message=(
                    f"Collecting baseline generation telemetry ({valid_pr_count}/7 days recorded). "
                    "At least 7 days of readings are required for watchdog performance analysis."
                ),
            )
            return _get_site_alerts_from_session(session, site_id)

        # ── Rule 1: Sudden Fault Diagnosis (Critical) ───────────────
        # Single-day drop >= 50% on clear-sky days (inverter trip, blown fuse, string disconnect)
        clear_sky_min = capacity_kw * config.CLEAR_SKY_MIN_EXPECTED_KWH_PER_KW
        fault_detected = False

        if len(readings_df) >= 2:
            # Check for a sudden drop between consecutive days in the recent 30-day window
            start_idx = max(1, len(readings_df) - 30)
            for i in range(start_idx, len(readings_df)):
                prev_row = readings_df.iloc[i - 1]
                curr_row = readings_df.iloc[i]
                prev_pr = prev_row["pr"]
                curr_pr = curr_row["pr"]
                curr_exp = curr_row["expected_kwh"]

                if (
                    curr_exp >= clear_sky_min
                    and prev_pr is not None
                    and curr_pr is not None
                    and prev_pr >= 0.40
                ):
                    single_day_drop = (prev_pr - curr_pr) / prev_pr
                    if single_day_drop >= config.SUDDEN_DROP_PCT:
                        fault_date_str = curr_row["date"].isoformat()
                        last_7 = readings_df.tail(7)
                        diff_7 = np.maximum(0.0, last_7["expected_kwh"] - last_7["actual_kwh"])
                        loss_kwh = float(diff_7.sum())
                        loss_inr = loss_kwh * config.TARIFF_INR_PER_KWH
                        drop_pct_display = single_day_drop * 100.0
                        msg = (
                            f"Sudden generation drop of {drop_pct_display:.0f}% detected on "
                            f"a clear day ({fault_date_str}). Inspect inverter and string fuses "
                            f"immediately. Estimated loss: {loss_kwh:.1f} kWh (~₹{loss_inr:,.2f})."
                        )
                        _insert_alert_if_not_duplicate(
                            session=session,
                            site_id=site_id,
                            alert_date=fault_date_str,
                            severity="critical",
                            cause="fault",
                            message=msg,
                        )
                        fault_detected = True
                        break

        if fault_detected:
            return _get_site_alerts_from_session(session, site_id)

        # Determine baseline Performance Ratio:
        # Prefer site's calibrated ratio if present, else fallback to config.PERFORMANCE_RATIO
        calibrated_pr = site.get("calibrated_performance_ratio")
        base_pr = float(calibrated_pr) if calibrated_pr is not None else config.PERFORMANCE_RATIO
        pr_scale = base_pr / config.PERFORMANCE_RATIO
        effective_pr_alert_level = config.PR_ALERT_LEVEL * pr_scale

        # ── Rule 2: 7-Day Underperformance & Dust/Soiling ───────────
        recent_7d = readings_df.tail(7)
        avg_pr_7d = recent_7d["pr"].mean()

        if avg_pr_7d < effective_pr_alert_level:
            # Underperformance detected. Check if caused by gradual dust accumulation over 2+ weeks
            dust_window_days = config.DUST_DECLINE_WINDOW_DAYS
            dust_subset = readings_df.tail(dust_window_days)

            # Check rainfall history over the dust window
            dust_start = dust_subset["date"].min()
            dust_end = dust_subset["date"].max()
            weather_hist = get_historical_weather(
                lat, lon, start_date=dust_start, end_date=dust_end, tilt=tilt, azimuth=azimuth
            )
            total_rain_mm = float(weather_hist["precipitation"].sum())

            # Check if trend is declining (first half PR significantly higher than second half PR)
            half = len(dust_subset) // 2
            first_half_pr = dust_subset["pr"].iloc[:half].mean()
            second_half_pr = dust_subset["pr"].iloc[half:].mean()
            is_gradual_decline = (first_half_pr - second_half_pr) >= 0.08

            if total_rain_mm <= config.DUST_MAX_RAIN_MM and is_gradual_decline:
                # Query upcoming 2-day forecast to check for natural rain cleaning
                try:
                    fc_df = get_forecast_weather(
                        lat=lat,
                        lon=lon,
                        days=config.RAIN_FORECAST_WINDOW_DAYS,
                        tilt=tilt,
                        azimuth=azimuth,
                    )
                    forecast_rain_mm = float(fc_df["precipitation"].sum())
                except Exception:
                    forecast_rain_mm = 0.0

                rain_note = (
                    " Rain is expected soon, so cleaning may not be needed."
                    if forecast_rain_mm >= config.RAIN_FORECAST_THRESHOLD_MM
                    else ""
                )

                diff_dust = np.maximum(
                    0.0, dust_subset["expected_kwh"] - dust_subset["actual_kwh"]
                )
                loss_kwh = float(diff_dust.sum())
                loss_inr = loss_kwh * config.TARIFF_INR_PER_KWH
                msg = (
                    f"Gradual generation decline detected over past 2+ weeks with minimal rain "
                    f"({total_rain_mm:.1f} mm). Panel washing recommended to recover "
                    f"~{loss_kwh:.1f} kWh (~₹{loss_inr:,.2f}) in lost generation.{rain_note}"
                )
                _insert_alert_if_not_duplicate(
                    session=session,
                    site_id=site_id,
                    alert_date=latest_date_str,
                    severity="warning",
                    cause="dust",
                    message=msg,
                )
                return _get_site_alerts_from_session(session, site_id)

        # ── Rule 3: Ageing Diagnosis (Year-on-Year Slow Degradation) ──
        latest_reading_date = readings_df["date"].iloc[-1]
        system_age_years = (latest_reading_date - installed_on).days / 365.25

        if system_age_years >= 1.0 and n_records >= 30:
            # Expected PR considering annual degradation from baseline (calibrated or global)
            expected_pr = base_pr * (
                (1.0 - config.ANNUAL_DEGRADATION_RATE) ** system_age_years
            )
            overall_pr = readings_df["pr"].mean()
            if overall_pr < (expected_pr - config.AGEING_EXTRA_SHORTFALL):
                shortfall_pct = (expected_pr - overall_pr) * 100
                diff_age = np.maximum(
                    0.0, readings_df["expected_kwh"] - readings_df["actual_kwh"]
                )
                loss_kwh = float(diff_age.sum())
                loss_inr = loss_kwh * config.TARIFF_INR_PER_KWH
                msg = (
                    f"System output is underperforming its normal degradation curve by "
                    f"{shortfall_pct:.1f}% after {system_age_years:.1f} years of operation. "
                    f"Estimated cumulative loss: {loss_kwh:.1f} kWh (~₹{loss_inr:,.2f}). "
                    "Check manufacturer module warranty."
                )
                _insert_alert_if_not_duplicate(
                    session=session,
                    site_id=site_id,
                    alert_date=latest_date_str,
                    severity="warning",
                    cause="ageing",
                    message=msg,
                )

        return _get_site_alerts_from_session(session, site_id)


# ── Site Health & Alert Query Services ──────────────────────────────

def _get_site_alerts_from_session(session, site_id: int) -> list[AlertRead]:
    """Retrieve all alerts for a site from an existing session (avoids nested get_session)."""
    rows = (
        session.query(Alert)
        .filter(Alert.site_id == site_id)
        .order_by(desc(Alert.id))
        .all()
    )
    return [
        AlertRead(
            id=r.id,
            site_id=r.site_id,
            date=r.date.isoformat() if hasattr(r.date, "isoformat") else str(r.date),
            severity=r.severity,
            cause=r.cause,
            message=r.message,
            created_at=r.created_at.isoformat(sep=" ", timespec="seconds")
            if hasattr(r.created_at, "isoformat")
            else str(r.created_at),
        )
        for r in rows
    ]


def get_site_alerts(site_id: int) -> list[AlertRead]:
    """Retrieve all alerts for a site ordered by date descending."""
    with get_session() as session:
        return _get_site_alerts_from_session(session, site_id)


def get_site_health(site_id: int, days: int = 30) -> SiteHealthResponse:
    """
    Get 30-day health summary: expected vs actual time-series, current PR, and active alerts.
    """
    site = get_site_by_id(site_id)
    capacity_kw = float(site["capacity_kw"])
    tilt = float(site["tilt"])
    azimuth = float(site["azimuth"])
    lat = float(site["lat"])
    lon = float(site["lon"])

    with get_session() as session:
        rows = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == site_id)
            .order_by(desc(DailyReading.date))
            .limit(days)
            .all()
        )
        if not rows:
            return SiteHealthResponse(
                site_id=site_id,
                site_name=site["name"],
                capacity_kw=capacity_kw,
                current_pr=None,
                last_30_days=[],
                latest_alerts=get_site_alerts(site_id),
            )

        # Reverse rows to chronological order
        recent_rows = list(reversed(rows))
        start_date = recent_rows[0].date
        end_date = recent_rows[-1].date

        # Fetch expected generation for the date window
        _, daily_expected_df = predict_for_dates(
            lat=lat,
            lon=lon,
            capacity_kw=capacity_kw,
            tilt=tilt,
            azimuth=azimuth,
            start_date=start_date,
            end_date=end_date,
        )

        expected_map = daily_expected_df["predicted_energy_kwh"].to_dict()

        daily_items: list[DailyHealthItem] = []
        valid_prs: list[float] = []

        for r in recent_rows:
            d_str = r.date.isoformat() if hasattr(r.date, "isoformat") else str(r.date)
            act = float(r.actual_kwh)
            exp = float(expected_map.get(d_str, 0.0))
            if exp >= config.MIN_EXPECTED_DAILY_KWH:
                pr = round(act / exp, 3)
                valid_prs.append(pr)
            else:
                pr = None

            daily_items.append(
                DailyHealthItem(
                    date=d_str,
                    actual_kwh=act,
                    expected_kwh=round(exp, 2),
                    performance_ratio=pr,
                )
            )

        # Calculate current 7-day average PR
        last_7_prs = valid_prs[-7:] if len(valid_prs) >= 7 else valid_prs
        current_pr = round(float(np.mean(last_7_prs)), 3) if last_7_prs else None

        return SiteHealthResponse(
            site_id=site_id,
            site_name=site["name"],
            capacity_kw=capacity_kw,
            current_pr=current_pr,
            last_30_days=daily_items,
            latest_alerts=get_site_alerts(site_id),
        )
