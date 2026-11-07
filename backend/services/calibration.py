"""
backend/services/calibration.py
───────────────────────────────
Empirical clear-sky performance ratio calibration service:
- Estimates site-specific Performance Ratio (PR) from high-irradiance / clear-sky days.
- Uses the MEDIAN of (actual_kwh / expected_kwh) rather than the mean, conferring mathematical
  robustness against inverter trips, grid outages, or localized cloud shadows.
- Persists the calibrated ratio to the Site record in the database.
- Watchdog automatically consumes this calibrated baseline to prevent false alarms caused
  by permanent localized rooftop conditions (e.g. slight horizon shading, higher cable losses).
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

from backend import config
from backend.db import DailyReading, Site, get_session
from backend.models.forecast import predict_for_dates
from backend.services.watchdog import evaluate_site_health, get_site_by_id

logger = logging.getLogger("solarsense.calibration")


def calibrate_site_ratio(site_id: int) -> dict[str, Any]:
    """
    Compute and store empirical performance ratio for a site using the median
    of actual/expected on clear-sky days.
    """
    site = get_site_by_id(site_id)
    capacity_kw = float(site["capacity_kw"])
    lat = float(site["lat"])
    lon = float(site["lon"])
    tilt = float(site["tilt"])
    azimuth = float(site["azimuth"])

    # 1. Fetch readings from DB
    with get_session() as session:
        readings = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == site_id)
            .order_by(DailyReading.date.asc())
            .all()
        )
        if not readings:
            raise ValueError(
                f"No generation readings found for site ID {site_id}. Please import data first."
            )

        if len(readings) < 3:
            raise ValueError(
                f"Site {site_id} has only {len(readings)} readings. "
                "At least 3 readings are required for calibration."
            )

        df = pd.DataFrame(
            [{"date": r.date, "actual_kwh": float(r.actual_kwh)} for r in readings]
        )

    start_date = df["date"].min()
    end_date = df["date"].max()

    # 2. Compute expected generation from weather model
    _, daily_expected_df = predict_for_dates(
        lat=lat,
        lon=lon,
        capacity_kw=capacity_kw,
        tilt=tilt,
        azimuth=azimuth,
        start_date=start_date,
        end_date=end_date,
    )

    exp_map = daily_expected_df["predicted_energy_kwh"].to_dict()
    df["expected_kwh"] = [
        float(exp_map.get(d.isoformat() if hasattr(d, "isoformat") else str(d), 0.0))
        for d in df["date"]
    ]

    # 3. Filter for clear-sky / high-irradiance days
    clear_sky_threshold = capacity_kw * config.CLEAR_SKY_MIN_EXPECTED_KWH_PER_KW
    # Also exclude near-zero generation days (grid outages, inverter trips)
    clear_sky_mask = (df["expected_kwh"] >= clear_sky_threshold) & (
        df["actual_kwh"] >= 0.05 * df["expected_kwh"]
    )
    clear_sky_df = df[clear_sky_mask].copy()

    if clear_sky_df.empty:
        raise ValueError(
            f"No clear-sky days (expected yield >= {clear_sky_threshold:.1f} kWh) found "
            f"in {len(df)} readings for site {site_id}. Cannot compute empirical calibration."
        )

    # 4. Calculate daily ratios and take MEDIAN
    clear_sky_df["ratio"] = clear_sky_df["actual_kwh"] / clear_sky_df["expected_kwh"]
    calibrated_pr = round(float(np.median(clear_sky_df["ratio"])), 3)

    # Ensure result is physically plausible [0.20, 1.20]
    calibrated_pr = float(np.clip(calibrated_pr, 0.20, 1.20))

    # 5. Persist calibrated ratio to Site record in database
    with get_session() as session:
        site_record = session.query(Site).filter(Site.id == site_id).first()
        if site_record:
            site_record.calibrated_performance_ratio = calibrated_pr
        session.flush()

    # 6. Re-evaluate site health with the newly calibrated baseline
    try:
        evaluate_site_health(site_id)
    except Exception as eval_err:
        logger.warning(
            "Post-calibration watchdog evaluation for site %s had error: %s", site_id, eval_err
        )

    logger.info(
        "Calibrated site %s: PR=%.3f using %d clear-sky days (total evaluated: %d)",
        site_id,
        calibrated_pr,
        len(clear_sky_df),
        len(df),
    )

    return {
        "status": "calibrated",
        "site_id": site_id,
        "calibrated_performance_ratio": calibrated_pr,
        "clear_sky_days_used": len(clear_sky_df),
        "total_days_evaluated": len(df),
    }
