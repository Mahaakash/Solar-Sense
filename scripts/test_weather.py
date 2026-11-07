"""
scripts/test_weather.py
───────────────────────
Live integration test for Open-Meteo weather service:
1. Geocodes 'Kolkata'.
2. Fetches 1 year of hourly historical weather data.
3. Prints row count, missing values per column, and summary statistics.
4. Fetches a 3-day hourly forecast and prints the head.
"""

import sys
from pathlib import Path

# Add project root to sys.path so backend imports cleanly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.weather import (
    geocode,
    get_forecast_weather,
    get_historical_weather,
)


def main() -> None:
    print("=" * 60)
    print("SolarSense — Weather Service Test (Kolkata)")
    print("=" * 60)

    # 1. Geocode
    place = "Kolkata"
    print(f"\n1. Geocoding '{place}'...")
    lat, lon, display_name = geocode(place)
    print(f"   Found: {display_name}")
    print(f"   Coordinates: lat={lat:.4f}, lon={lon:.4f}")

    # 2. Historical Weather (1 Year)
    start_date = "2023-01-01"
    end_date = "2023-12-31"
    print(f"\n2. Fetching 1-year historical weather ({start_date} to {end_date})...")
    df_hist = get_historical_weather(lat, lon, start_date=start_date, end_date=end_date)

    print(f"   Row count: {len(df_hist):,} rows (expected 8,760 for non-leap year)")
    print(f"   DatetimeIndex Timezone: {df_hist.index.tz}")
    print("\n   Missing values per column:")
    for col, null_count in df_hist.isnull().sum().items():
        print(f"     - {col}: {null_count}")

    print("\n   Key Summary Statistics:")
    summary_cols = [
        "temperature_2m",
        "shortwave_radiation",
        "global_tilted_irradiance",
        "cloud_cover",
        "precipitation",
    ]
    avail_cols = [c for c in summary_cols if c in df_hist.columns]
    print(df_hist[avail_cols].describe().round(2).to_string())

    # 3. Forecast Weather (3 Days)
    print("\n3. Fetching 3-day hourly forecast...")
    df_fc = get_forecast_weather(lat, lon, days=3)
    print(f"   Forecast rows: {len(df_fc)} (expected ~72 hours)")
    print("\n   Forecast preview (first 5 hours):")
    preview_cols = [
        "temperature_2m",
        "shortwave_radiation",
        "global_tilted_irradiance",
        "precipitation",
    ]
    avail_preview = [c for c in preview_cols if c in df_fc.columns]
    print(df_fc[avail_preview].head().round(2).to_string())

    print("\n" + "=" * 60)
    print("Weather service test completed successfully.")
    print("=" * 60)


if __name__ == "__main__":
    main()
