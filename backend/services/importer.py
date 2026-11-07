"""
backend/services/importer.py
────────────────────────────
Flexible real-data CSV ingestion engine for rooftop solar installations:
- Automatically detects date/time and energy/power columns from diverse CSV naming conventions.
- Automatically detects data format:
    1. Daily kWh (one row per date)
    2. Interval kWh (sub-daily energy meter intervals aggregated to daily sums)
    3. Interval kW power (instantaneous power integrated over detected sampling interval to kWh)
- Robust parsing: handles day-first dates, ISO dates, thousands separators (commas),
  unit hints (Wh, kWh, MWh), missing days, duplicate timestamps, and negative night noise.
- Enforces strict safety limits (file size <= 10MB, row limit <= 100,000, site existence).
- Persists via idempotent DailyReading upsert and triggers Watchdog health evaluation.
- Returns comprehensive structured audit report with rows read, days created, and skip reasons.
"""

import io
import logging
from collections import defaultdict
from datetime import date
from typing import Any

import pandas as pd

from backend.db import DailyReading, get_session
from backend.services.watchdog import evaluate_site_health, get_site_by_id

logger = logging.getLogger("solarsense.importer")

MAX_FILE_BYTES: int = 10 * 1024 * 1024  # 10 MB
MAX_ROWS_LIMIT: int = 100_000

# Canonical candidate header names (lowercase, stripped)
DATE_COLUMN_CANDIDATES = [
    "date",
    "timestamp",
    "time",
    "datetime",
    "reading_date",
    "reading_time",
    "day",
    "period",
    "timestamp_utc",
    "local_time",
    "ts",
]

ENERGY_COLUMN_CANDIDATES = [
    "energy_kwh",
    "kwh",
    "daily_yield",
    "yield_kwh",
    "daily_yield_kwh",
    "energy",
    "generation",
    "generation_kwh",
    "production_kwh",
    "yield",
    "power_kw",
    "power",
    "kw",
    "active_power_kw",
    "power_w",
    "energy_wh",
    "yield_wh",
    "mwh",
    "energy_mwh",
]


def _detect_column(fieldnames: list[str], candidates: list[str]) -> str | None:
    """Find the best matching column name case-insensitively."""
    cleaned_fields = {f.strip().lower(): f for f in fieldnames if f}

    # 1. Exact match
    for cand in candidates:
        if cand in cleaned_fields:
            return cleaned_fields[cand]

    # 2. Substring match
    for cand in candidates:
        for clean_name, original in cleaned_fields.items():
            if cand in clean_name:
                return original

    return None


def _detect_unit_multiplier(column_name: str) -> tuple[float, str]:
    """Detect energy/power unit from column header name."""
    col_lower = column_name.lower()
    if "mwh" in col_lower:
        return 1000.0, "mwh"
    is_wh = (
        ("wh" in col_lower or "_w" in col_lower)
        and "kwh" not in col_lower
        and "mwh" not in col_lower
    )
    if is_wh:
        return 0.001, "wh"
    if "kw" in col_lower or "power" in col_lower:
        return 1.0, "kw"
    return 1.0, "kwh"


def import_readings_csv(
    site_id: int,
    content: str | bytes,
    filename: str = "",
) -> dict[str, Any]:
    """
    Parse uploaded CSV generation readings, aggregate to daily totals, upsert to database,
    and return detailed execution report.
    """
    # 1. Validate site exists
    get_site_by_id(site_id)

    # 2. Decode content and check size
    if isinstance(content, bytes):
        if len(content) > MAX_FILE_BYTES:
            size_mb = len(content) / (1024 * 1024)
            msg = f"Uploaded file size ({size_mb:.2f} MB) exceeds maximum allowed limit of 10 MB."
            raise ValueError(msg)
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                text_content = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text_content = content.decode("utf-8", errors="replace")
    else:
        text_content = content
        if len(text_content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Uploaded file exceeds 10 MB limit.")

    # 3. Read CSV into DataFrame
    try:
        df = pd.read_csv(io.StringIO(text_content), sep=None, engine="python")
    except Exception as read_err:
        raise ValueError(f"Failed to parse CSV file: {read_err}") from read_err

    if df.empty:
        raise ValueError("Uploaded CSV file is empty.")

    total_rows = len(df)
    if total_rows > MAX_ROWS_LIMIT:
        raise ValueError(
            f"CSV contains {total_rows:,} rows, exceeding maximum limit of {MAX_ROWS_LIMIT:,}."
        )

    # 4. Column Detection
    date_col = _detect_column(list(df.columns), DATE_COLUMN_CANDIDATES)
    energy_col = _detect_column(list(df.columns), ENERGY_COLUMN_CANDIDATES)

    if not date_col:
        raise ValueError(
            f"Could not identify a date or timestamp column in CSV headers: {list(df.columns)}. "
            "Please provide a column named 'date', 'timestamp', or 'time'."
        )

    if not energy_col:
        raise ValueError(
            f"Could not identify an energy or power column in CSV headers: {list(df.columns)}. "
            "Please provide a column named 'energy_kwh', 'kWh', 'daily_yield', or 'power_kw'."
        )

    unit_multiplier, unit_name = _detect_unit_multiplier(energy_col)
    skip_reasons: dict[str, int] = defaultdict(int)

    # 5. Parse Timestamps
    # If date strings start with a 4-digit year (YYYY-MM-DD), use ISO dayfirst=False.
    # Otherwise (e.g. DD/MM/YYYY), attempt dayfirst=True with dayfirst=False fallback.
    non_null_dates = df[date_col].dropna().astype(str).str.strip()
    first_val = non_null_dates.iloc[0] if not non_null_dates.empty else ""
    is_iso = len(first_val) >= 4 and first_val[:4].isdigit() and (first_val[4:5] in ("-", "/"))

    if is_iso:
        dt_series = pd.to_datetime(df[date_col], dayfirst=False, errors="coerce")
    else:
        dt_series = pd.to_datetime(df[date_col], dayfirst=True, errors="coerce")
        invalid_dates = dt_series.isna()
        if invalid_dates.any():
            retry_dt = pd.to_datetime(
                df.loc[invalid_dates, date_col], dayfirst=False, errors="coerce"
            )
            dt_series.loc[invalid_dates] = retry_dt

    # 6. Parse Energy / Power values
    # Clean thousands separators (commas), whitespace, quotes
    raw_vals = df[energy_col].astype(str).str.replace(",", "", regex=False).str.strip()
    num_series = pd.to_numeric(raw_vals, errors="coerce")

    # Filter invalid rows and record reasons
    valid_mask = dt_series.notna() & num_series.notna()

    unparseable_dates_cnt = int(dt_series.isna().sum())
    if unparseable_dates_cnt > 0:
        skip_reasons["unparseable_date"] = unparseable_dates_cnt

    unparseable_nums_cnt = int(num_series.isna().sum())
    if unparseable_nums_cnt > 0:
        skip_reasons["unparseable_numeric_value"] = unparseable_nums_cnt

    clean_df = pd.DataFrame(
        {
            "timestamp": dt_series[valid_mask],
            "raw_val": num_series[valid_mask],
            "orig_idx": list(range(int(valid_mask.sum()))),
        }
    ).sort_values(by=["timestamp", "orig_idx"], kind="stable")

    if clean_df.empty:
        raise ValueError("No valid data rows could be parsed from the uploaded CSV.")

    # 7. Format Detection & Energy Computation
    # Check for negative values (inverter night draw or noise)
    negative_mask = clean_df["raw_val"] < 0.0
    neg_cnt = int(negative_mask.sum())
    if neg_cnt > 0:
        skip_reasons["negative_value_clipped_to_zero"] = neg_cnt
        clean_df.loc[negative_mask, "raw_val"] = 0.0

    clean_df["date"] = clean_df["timestamp"].dt.date
    rows_clean = len(clean_df)
    dates_unique = clean_df["date"].nunique()
    timestamps_unique = clean_df["timestamp"].nunique()
    has_subdaily_times = (clean_df["timestamp"].dt.time.astype(str) != "00:00:00").any()
    is_subdaily = (timestamps_unique > dates_unique) or has_subdaily_times
    is_power_col = unit_name == "kw" or "power" in energy_col.lower()

    if is_power_col and is_subdaily:
        detected_format = "interval_kw"
        # Compute time interval between successive readings to integrate power (kW) -> energy (kWh)
        # Group by date to prevent midnight-to-morning boundary gaps distorting intervals
        daily_kwh_map: dict[date, float] = defaultdict(float)

        for d_key, grp in clean_df.groupby("date"):
            if len(grp) == 1:
                # Default assume 1 hour if only 1 reading
                daily_kwh_map[d_key] += float(grp["raw_val"].iloc[0] * unit_multiplier * 1.0)
                continue

            grp = grp.sort_values("timestamp")
            # Calculate interval deltas in hours
            deltas = grp["timestamp"].diff().dt.total_seconds() / 3600.0
            # For the first row of each day, use the median delta of that day
            valid_deltas = deltas.dropna()
            has_positive = not valid_deltas.empty and valid_deltas.median() > 0
            med_delta = valid_deltas.median() if has_positive else 1.0
            # Cap realistic intervals to max 2 hours to avoid overnight gaps
            med_delta = min(med_delta, 2.0)
            deltas.iloc[0] = med_delta

            interval_kwh = (grp["raw_val"] * unit_multiplier) * deltas.clip(lower=0.0, upper=2.0)
            daily_kwh_map[d_key] = float(interval_kwh.sum())

    elif is_subdaily:
        detected_format = "interval_kwh"
        # Sub-daily readings already represent energy (kWh) for that interval -> sum per day
        daily_kwh_map = clean_df.groupby("date").apply(
            lambda g: float((g["raw_val"] * unit_multiplier).sum())
        ).to_dict()

    else:
        detected_format = "daily_kwh"
        # 1 row per date; later rows in file cleanly update earlier duplicate dates
        daily_kwh_map = {}
        for _, row in clean_df.iterrows():
            daily_kwh_map[row["date"]] = float(row["raw_val"] * unit_multiplier)

    # 8. Upsert daily readings to database
    with get_session() as session:
        for d_val, kwh_val in sorted(daily_kwh_map.items()):
            rounded_kwh = round(float(kwh_val), 3)
            existing = (
                session.query(DailyReading)
                .filter(DailyReading.site_id == site_id, DailyReading.date == d_val)
                .first()
            )
            if existing:
                existing.actual_kwh = rounded_kwh
            else:
                session.add(
                    DailyReading(
                        site_id=site_id,
                        date=d_val,
                        actual_kwh=rounded_kwh,
                    )
                )
        session.flush()

    # 9. Trigger Watchdog Health Evaluation
    try:
        evaluate_site_health(site_id)
    except Exception as eval_err:
        logger.warning(
            "Watchdog evaluation after import for site %s had error: %s", site_id, eval_err
        )

    sorted_dates = sorted(daily_kwh_map.keys())
    start_date_str = sorted_dates[0].isoformat() if sorted_dates else None
    end_date_str = sorted_dates[-1].isoformat() if sorted_dates else None

    total_skipped = total_rows - rows_clean

    report = {
        "status": "ok",
        "site_id": site_id,
        "detected_format": detected_format,
        "energy_column": energy_col,
        "energy_unit": unit_name,
        "rows_read": total_rows,
        "days_created": len(daily_kwh_map),
        "rows_skipped": total_skipped,
        "skip_reasons": dict(skip_reasons),
        "date_range": {
            "start": start_date_str,
            "end": end_date_str,
        },
    }

    logger.info(
        "Successfully imported %d days of data for site %s (format: %s, skipped rows: %d)",
        len(daily_kwh_map),
        site_id,
        detected_format,
        total_skipped,
    )
    return report
