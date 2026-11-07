"""
scripts/evaluate_real_data.py
─────────────────────────────
Evaluate the accuracy of the SolarSense physics-informed ML model against real
generation readings recorded for a site:
- Computes weather-adjusted expected daily kWh using historical weather data.
- Filters out overcast days (< 0.5 kWh expected) and obvious grid/inverter outages.
- Reports MAE, RMSE, Mean Percentage Error (MPE), and Mean Performance Ratio (PR)
  both overall and broken down month-by-month.
- Generates timeseries (expected vs actual) and scatter (with y=x line) diagnostic plots
  in notebooks/.
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backend import config
from backend.db import DailyReading, get_session
from backend.models.forecast import predict_for_dates
from backend.services.watchdog import get_site_by_id


def evaluate_site_real_data(
    site_id: int = 1,
    timeseries_plot: str = "notebooks/real_data_evaluation_timeseries.png",
    scatter_plot: str = "notebooks/real_data_evaluation_scatter.png",
) -> dict[str, float]:
    """
    Evaluate actual generation vs weather-adjusted expected output and save visual plots.
    """
    site = get_site_by_id(site_id)
    site_name = site["name"]
    capacity_kw = float(site["capacity_kw"])
    lat = float(site["lat"])
    lon = float(site["lon"])
    tilt = float(site["tilt"])
    azimuth = float(site["azimuth"])

    print("=" * 75)
    print(f"SolarSense — Real Data Model Evaluation for Site #{site_id}: {site_name}")
    print(f"Capacity: {capacity_kw} kWp | Location: ({lat:.4f}°N, {lon:.4f}°E) | Tilt: {tilt}°")
    print("=" * 75)

    # 1. Fetch Readings
    with get_session() as session:
        readings = (
            session.query(DailyReading)
            .filter(DailyReading.site_id == site_id)
            .order_by(DailyReading.date.asc())
            .all()
        )
        if not readings:
            raise ValueError(f"No generation readings found in database for site ID {site_id}.")

        df = pd.DataFrame(
            [{"date": r.date, "actual_kwh": float(r.actual_kwh)} for r in readings]
        )

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").reset_index(drop=True)

    start_date = df["date"].min()
    end_date = df["date"].max()
    total_days = len(df)

    # 2. Compute Expected Output
    print(f"\nComputing weather-adjusted expected generation ({start_date} to {end_date})...")
    _, daily_exp = predict_for_dates(
        lat=lat,
        lon=lon,
        capacity_kw=capacity_kw,
        tilt=tilt,
        azimuth=azimuth,
        start_date=start_date,
        end_date=end_date,
    )

    exp_map = daily_exp["predicted_energy_kwh"].to_dict()
    df["expected_kwh"] = [
        float(exp_map.get(d.isoformat() if hasattr(d, "isoformat") else str(d), 0.0))
        for d in df["date"]
    ]

    # 3. Exclude Non-Representative Days (dark/overcast noise or obvious outages)
    clear_sky_thresh = capacity_kw * config.CLEAR_SKY_MIN_EXPECTED_KWH_PER_KW
    low_expected_mask = df["expected_kwh"] < config.MIN_EXPECTED_DAILY_KWH
    outage_mask = (df["expected_kwh"] >= clear_sky_thresh) & (
        df["actual_kwh"] < 0.05 * df["expected_kwh"]
    )

    excluded_low_exp = int(low_expected_mask.sum())
    excluded_outages = int(outage_mask.sum())
    total_excluded = int((low_expected_mask | outage_mask).sum())

    valid_mask = ~(low_expected_mask | outage_mask)
    eval_df = df[valid_mask].copy()

    if eval_df.empty:
        raise ValueError("All days were excluded due to low expected yield or outages.")

    # 4. Compute Metrics
    actual = eval_df["actual_kwh"]
    expected = eval_df["expected_kwh"]
    errors = actual - expected
    abs_errors = np.abs(errors)

    mae = float(abs_errors.mean())
    rmse = float(np.sqrt((errors ** 2).mean()))
    mpe = float((errors / expected).mean() * 100.0)
    mean_pr = float(actual.sum() / expected.sum()) if expected.sum() > 0 else 0.0

    print("\n" + "=" * 75)
    print("OVERALL MODEL ACCURACY METRICS")
    print("=" * 75)
    print(f"Total Reading Days:         {total_days}")
    excl_msg = (
        f"{total_excluded} (Overcast < {config.MIN_EXPECTED_DAILY_KWH} kWh: {excluded_low_exp}, "
        f"Clear-sky Outages: {excluded_outages})"
    )
    print(f"Excluded Days:              {excl_msg}")
    print(f"Evaluated Days:             {len(eval_df)}")
    print(f"Mean Absolute Error (MAE):  {mae:.2f} kWh/day")
    print(f"Root Mean Sq Error (RMSE):  {rmse:.2f} kWh/day")
    print(f"Mean Percentage Error:      {mpe:+.2f}%")
    print(f"Mean Performance Ratio:     {mean_pr:.3f}")

    # 5. Monthly Breakdown
    eval_df["month"] = pd.to_datetime(eval_df["date"]).dt.strftime("%Y-%m")
    monthly_rows: list[dict] = []

    for m_key, grp in eval_df.groupby("month"):
        m_actual = grp["actual_kwh"]
        m_exp = grp["expected_kwh"]
        m_err = m_actual - m_exp
        m_mae = float(np.abs(m_err).mean())
        m_rmse = float(np.sqrt((m_err ** 2).mean()))
        m_pr = float(m_actual.sum() / m_exp.sum()) if m_exp.sum() > 0 else 0.0

        monthly_rows.append(
            {
                "Month": m_key,
                "Days": len(grp),
                "Actual (kWh)": round(float(m_actual.sum()), 1),
                "Expected (kWh)": round(float(m_exp.sum()), 1),
                "MAE (kWh/d)": round(m_mae, 2),
                "RMSE (kWh/d)": round(m_rmse, 2),
                "Mean PR": round(m_pr, 3),
            }
        )

    monthly_table = pd.DataFrame(monthly_rows)
    print("\nMONTHLY BREAKDOWN:")
    print(monthly_table.to_string(index=False))

    # 6. Generate Timeseries Line Chart
    Path(timeseries_plot).parent.mkdir(parents=True, exist_ok=True)
    Path(scatter_plot).parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 5), dpi=150)
    ax.plot(
        pd.to_datetime(df["date"]),
        df["expected_kwh"],
        label="Weather-Adjusted Expected",
        color="#0284c7",
        linewidth=1.5,
        alpha=0.9,
    )
    ax.plot(
        pd.to_datetime(df["date"]),
        df["actual_kwh"],
        label="Actual Generation",
        color="#16a34a",
        linewidth=1.2,
        alpha=0.85,
    )

    # Highlight excluded outage points
    if outage_mask.any():
        outage_dates = pd.to_datetime(df.loc[outage_mask, "date"])
        outage_vals = df.loc[outage_mask, "actual_kwh"]
        ax.scatter(
            outage_dates, outage_vals, color="#dc2626", label="Excluded Outages", zorder=5, s=30
        )

    ax.set_ylabel("Daily Generation (kWh)", fontsize=11, fontweight="bold")
    ax.set_title(
        f"SolarSense Real Data Evaluation — Site #{site_id} ({site_name})",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax.legend(frameon=True, facecolor="#f8fafc", edgecolor="#cbd5e1")
    ax.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(timeseries_plot)
    plt.close(fig)
    print(f"\n[Saved] Timeseries comparison saved to: {timeseries_plot}")

    # 7. Generate Scatter Plot with y = x Reference
    fig2, ax2 = plt.subplots(figsize=(6.5, 6.5), dpi=150)
    ax2.scatter(
        eval_df["expected_kwh"],
        eval_df["actual_kwh"],
        alpha=0.6,
        color="#0284c7",
        edgecolors="none",
        s=25,
        label="Daily Readings",
    )

    max_val = max(eval_df["expected_kwh"].max(), eval_df["actual_kwh"].max()) * 1.08
    ax2.plot(
        [0, max_val],
        [0, max_val],
        color="#dc2626",
        linestyle="--",
        linewidth=1.5,
        label="Perfect Agreement (y = x)",
    )

    ax2.set_xlabel("Expected Generation (kWh/day)", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Actual Generation (kWh/day)", fontsize=11, fontweight="bold")
    ax2.set_title(
        f"Model Agreement — MAE: {mae:.2f} kWh | PR: {mean_pr:.2f}",
        fontsize=11,
        fontweight="bold",
        pad=12,
    )
    ax2.set_xlim(0, max_val)
    ax2.set_ylim(0, max_val)
    ax2.legend(frameon=True, facecolor="#f8fafc", edgecolor="#cbd5e1")
    ax2.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(scatter_plot)
    plt.close(fig2)
    print(f"[Saved] Scatter plot saved to: {scatter_plot}\n")

    return {
        "mae": mae,
        "rmse": rmse,
        "mpe": mpe,
        "mean_pr": mean_pr,
        "total_days": float(total_days),
        "evaluated_days": float(len(eval_df)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate SolarSense model predictions against real site generation."
    )
    parser.add_argument("--site-id", type=int, default=1, help="Site ID to evaluate (default: 1)")
    parser.add_argument(
        "--timeseries-plot",
        default="notebooks/real_data_evaluation_timeseries.png",
        help="Output path for timeseries plot",
    )
    parser.add_argument(
        "--scatter-plot",
        default="notebooks/real_data_evaluation_scatter.png",
        help="Output path for scatter plot",
    )
    args = parser.parse_args()

    evaluate_site_real_data(
        site_id=args.site_id,
        timeseries_plot=args.timeseries_plot,
        scatter_plot=args.scatter_plot,
    )
