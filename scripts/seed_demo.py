"""
scripts/seed_demo.py
────────────────────
Multi-metro demonstration seeding script for SolarSense Watchdog:
Populates solar installations and realistic telemetry across major Indian metropolitan cities.
"""

import sys
from pathlib import Path

# Ensure backend package is in Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import init_db
from backend.services.seed import METRO_SEED_SPECS, seed_all_demo_sites


def main() -> None:
    print("=" * 70)
    print("SolarSense — Pan-India Metropolitan Telemetry Demo Seeder")
    print("=" * 70)

    init_db()
    print(f"\nSeeding {len(METRO_SEED_SPECS)} solar installations across major Indian metros...")
    results = seed_all_demo_sites()

    for r in results:
        pr_disp = f"{r['current_pr']:.1%}" if r["current_pr"] is not None else "N/A"
        print(
            f"   Site #{r['site_id']}: {r['name']} ({r['capacity_kw']} kWp) | "
            f"PR: {pr_disp} | Alerts: {r['alert_count']}"
        )

    print("\n" + "=" * 70)
    print("All metropolitan installations successfully seeded & diagnosed.")
    print("=" * 70)


if __name__ == "__main__":
    main()
