"""
scripts/validate_advisor.py
───────────────────────────
Validate the SolarSense Advisor yield forecasting model against industry-standard
benchmarks (PVGIS SARAH2/ERA5 and NREL PVWatts).

Calculates yearly specific yield (kWh / kWp / year) for reference locations using identical
orientation (tilt, azimuth) and system loss assumptions.
Generates notebooks/advisor_validation.csv and notebooks/advisor_validation.png.
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
from backend.models.forecast import predict_for_dates


def validate_advisor(
    csv_path: str = "data/reference_yields.csv",
    output_csv: str = "notebooks/advisor_validation.csv",
    output_png: str = "notebooks/advisor_validation.png",
    reference_year: str = config.ADVISOR_REFERENCE_YEAR,
) -> pd.DataFrame:
    """
    Run benchmark comparison across reference cities and save diagnostic artifacts.
    """
    ref_file = Path(csv_path)
    if not ref_file.exists():
        raise FileNotFoundError(f"Reference yield file not found: {ref_file}")

    df_ref = pd.read_csv(ref_file)
    required_cols = {"city", "lat", "lon", "tilt", "azimuth"}
    if not required_cols.issubset(df_ref.columns):
        missing = required_cols - set(df_ref.columns)
        raise ValueError(f"Reference CSV missing required columns: {missing}")

    results: list[dict] = []

    print("=" * 75)
    print("SolarSense — Advisor Yield Validation vs PVGIS & PVWatts Benchmarks")
    print(f"Reference Year: {reference_year} | Model Base PR: {config.PERFORMANCE_RATIO:.2f}")
    print("=" * 75)

    for _, row in df_ref.iterrows():
        city = str(row["city"]).strip()
        lat = float(row["lat"])
        lon = float(row["lon"])
        tilt = float(row["tilt"])
        azimuth = float(row["azimuth"])

        # System loss from file or global config
        sys_loss = (
            float(row.get("system_loss", config.SYSTEM_LOSS_FRACTION))
            if pd.notnull(row.get("system_loss"))
            else config.SYSTEM_LOSS_FRACTION
        )

        # Reference tool values (safely parse float or None)
        has_pvgis = "pvgis" in row and pd.notnull(row["pvgis"]) and str(row["pvgis"]).strip() != ""
        pvgis_val = float(row["pvgis"]) if has_pvgis else None

        has_pvwatts = (
            "pvwatts" in row and pd.notnull(row["pvwatts"]) and str(row["pvwatts"]).strip() != ""
        )
        pvwatts_val = float(row["pvwatts"]) if has_pvwatts else None

        # Predict full reference year using 1.0 kW capacity
        start_date = f"{reference_year}-01-01"
        end_date = f"{reference_year}-12-31"

        hourly_df, _ = predict_for_dates(
            lat=lat,
            lon=lon,
            capacity_kw=1.0,
            tilt=tilt,
            azimuth=azimuth,
            start_date=start_date,
            end_date=end_date,
        )

        raw_annual_kwh = float(hourly_df["predicted_power_kw"].sum())

        # Scale by benchmark system loss:
        # Our model was trained with PERFORMANCE_RATIO (0.78, corresponding to 22% loss).
        # To match reference tool loss L (e.g. 14%), scale by (1 - L) / PERFORMANCE_RATIO.
        loss_scale = (1.0 - sys_loss) / config.PERFORMANCE_RATIO
        our_kwh_per_kw = round(raw_annual_kwh * loss_scale, 1)

        pct_diff_pvgis = (
            round(((our_kwh_per_kw - pvgis_val) / pvgis_val) * 100.0, 2)
            if pvgis_val is not None
            else None
        )
        pct_diff_pvwatts = (
            round(((our_kwh_per_kw - pvwatts_val) / pvwatts_val) * 100.0, 2)
            if pvwatts_val is not None
            else None
        )

        results.append(
            {
                "city": city,
                "our_kwh_per_kw": our_kwh_per_kw,
                "pvgis": pvgis_val,
                "pvwatts": pvwatts_val,
                "pct_diff_vs_pvgis": pct_diff_pvgis,
                "pct_diff_vs_pvwatts": pct_diff_pvwatts,
            }
        )

        pvgis_str = f"{pvgis_val:.1f}" if pvgis_val is not None else "N/A"
        pvwatts_str = f"{pvwatts_val:.1f}" if pvwatts_val is not None else "N/A"
        diff_pg_str = f"{pct_diff_pvgis:+.2f}%" if pct_diff_pvgis is not None else "N/A"
        diff_pw_str = f"{pct_diff_pvwatts:+.2f}%" if pct_diff_pvwatts is not None else "N/A"

        print(
            f"  {city:12} | Our: {our_kwh_per_kw:6.1f} | PVGIS: {pvgis_str:6} ({diff_pg_str:>7}) | "
            f"PVWatts: {pvwatts_str:6} ({diff_pw_str:>7})"
        )

    res_df = pd.DataFrame(results)

    # Ensure output directories exist
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    Path(output_png).parent.mkdir(parents=True, exist_ok=True)

    # Save CSV
    res_df.to_csv(output_csv, index=False)
    print(f"\n[Saved] Detailed validation data saved to: {output_csv}")

    # Summary Statistics (skipping empty reference cells cleanly)
    print("\n" + "=" * 75)
    print("SUMMARY BENCHMARK ACCURACY STATISTICS")
    print("=" * 75)

    valid_pvgis = res_df.dropna(subset=["pct_diff_vs_pvgis"])
    if not valid_pvgis.empty:
        mapd_pvgis = float(valid_pvgis["pct_diff_vs_pvgis"].abs().mean())
        bias_pvgis = float((valid_pvgis["our_kwh_per_kw"] - valid_pvgis["pvgis"]).mean())
        worst_pvgis_idx = valid_pvgis["pct_diff_vs_pvgis"].abs().idxmax()
        worst_pvgis_city = valid_pvgis.loc[worst_pvgis_idx, "city"]
        worst_pvgis_diff = valid_pvgis.loc[worst_pvgis_idx, "pct_diff_vs_pvgis"]
        print(f"VS PVGIS ({len(valid_pvgis)} cities):")
        print(f"  • Mean Absolute Percentage Difference (MAPD): {mapd_pvgis:.2f}%")
        print(f"  • Mean Bias: {bias_pvgis:+.1f} kWh/kWp/year")
        print(f"  • Worst City: {worst_pvgis_city} ({worst_pvgis_diff:+.2f}%)")

    valid_pvwatts = res_df.dropna(subset=["pct_diff_vs_pvwatts"])
    if not valid_pvwatts.empty:
        mapd_pvwatts = float(valid_pvwatts["pct_diff_vs_pvwatts"].abs().mean())
        bias_pvwatts = float((valid_pvwatts["our_kwh_per_kw"] - valid_pvwatts["pvwatts"]).mean())
        worst_pvwatts_idx = valid_pvwatts["pct_diff_vs_pvwatts"].abs().idxmax()
        worst_pvwatts_city = valid_pvwatts.loc[worst_pvwatts_idx, "city"]
        worst_pvwatts_diff = valid_pvwatts.loc[worst_pvwatts_idx, "pct_diff_vs_pvwatts"]
        print(f"\nVS PVWatts ({len(valid_pvwatts)} cities):")
        print(f"  • Mean Absolute Percentage Difference (MAPD): {mapd_pvwatts:.2f}%")
        print(f"  • Mean Bias: {bias_pvwatts:+.1f} kWh/kWp/year")
        print(f"  • Worst City: {worst_pvwatts_city} ({worst_pvwatts_diff:+.2f}%)")

    # Generate Comparison Bar Chart
    _generate_comparison_plot(res_df, output_png)
    print(f"[Saved] Comparison chart saved to: {output_png}\n")

    return res_df


def _generate_comparison_plot(df: pd.DataFrame, output_path: str) -> None:
    """Generate side-by-side bar chart of SolarSense vs reference yields."""
    cities = df["city"].tolist()
    x = np.arange(len(cities))
    width = 0.26

    fig, ax = plt.subplots(figsize=(11, 6), dpi=150)

    # Plot bars
    ax.bar(x - width, df["our_kwh_per_kw"], width, label="SolarSense Model", color="#0284c7")

    # Plot PVGIS if available
    pvgis_vals = [v if pd.notnull(v) else 0.0 for v in df["pvgis"]]
    ax.bar(x, pvgis_vals, width, label="PVGIS (EU-JRC)", color="#16a34a", alpha=0.85)

    # Plot PVWatts if available
    pvwatts_vals = [v if pd.notnull(v) else 0.0 for v in df["pvwatts"]]
    ax.bar(x + width, pvwatts_vals, width, label="PVWatts (NREL)", color="#ea580c", alpha=0.85)

    ax.set_ylabel("Specific Yield (kWh / kWp / year)", fontsize=11, fontweight="bold")
    ax.set_title(
        "SolarSense Advisor vs Industry Reference Benchmarks (14% System Loss)",
        fontsize=13,
        fontweight="bold",
        pad=15,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(cities, rotation=25, ha="right", fontsize=10)
    ax.legend(frameon=True, facecolor="#f8fafc", edgecolor="#cbd5e1")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_ylim(bottom=1000)

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate SolarSense Advisor model against reference benchmarks."
    )
    parser.add_argument(
        "--csv-path", default="data/reference_yields.csv", help="Path to reference yields CSV"
    )
    parser.add_argument(
        "--output-csv", default="notebooks/advisor_validation.csv", help="Output validation CSV"
    )
    parser.add_argument(
        "--output-png", default="notebooks/advisor_validation.png", help="Output comparison chart"
    )
    args = parser.parse_args()

    validate_advisor(
        csv_path=args.csv_path, output_csv=args.output_csv, output_png=args.output_png
    )
