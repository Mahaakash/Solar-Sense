"""
scripts/calibrate_site.py
─────────────────────────
Command-line tool to perform empirical clear-sky performance ratio calibration
for a SolarSense monitored site.

Calculates the median (actual / expected) ratio across clear-sky days and stores
it as calibrated_performance_ratio on the site record.
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config
from backend.services.calibration import calibrate_site_ratio


def main() -> None:
    parser = argparse.ArgumentParser(description="Empirically calibrate site performance ratio.")
    parser.add_argument("--site-id", type=int, default=1, help="Site ID to calibrate (default: 1)")
    args = parser.parse_args()

    print("=" * 65)
    print(f"SolarSense — Empirical Clear-Sky Calibration for Site ID {args.site_id}")
    print("=" * 65)

    try:
        result = calibrate_site_ratio(args.site_id)
        pr_val = result["calibrated_performance_ratio"]
        clear_days = result["clear_sky_days_used"]
        total_days = result["total_days_evaluated"]

        print("\nCalibration Results:")
        print(f"  • Status:                      {result['status'].upper()}")
        print(f"  • Site ID:                     {args.site_id}")
        print(f"  • Calibrated Performance Ratio: {pr_val:.3f}")
        print(f"  • Global Default Baseline:     {config.PERFORMANCE_RATIO:.3f}")
        diff_pct = ((pr_val - config.PERFORMANCE_RATIO) / config.PERFORMANCE_RATIO) * 100.0
        print(f"  • Offset vs Default Baseline:  {diff_pct:+.1f}%")
        print(f"  • Clear-Sky Days Sampled:      {clear_days}")
        print(f"  • Total Reading Days Evaluated: {total_days}")
        print("\nWatchdog will now evaluate this site using this empirical baseline.")
        print("=" * 65)
    except Exception as err:
        print(f"\n[Error] Calibration failed for site {args.site_id}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()

