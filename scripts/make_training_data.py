"""
scripts/make_training_data.py
─────────────────────────────
Pipeline script to download historical weather across all major Indian metropolitan cities
(Delhi NCR, Mumbai, Kolkata, Chennai, Bengaluru, Hyderabad, Ahmedabad, Pune),
engineer meteorological features, synthesize physically consistent PV targets,
and save the unified pan-India training dataset.
"""

import sys
from pathlib import Path

# Ensure backend package is in Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend import config
from backend.services.features import build_training_dataset
from backend.services.weather import get_historical_weather


def main() -> None:
    print("=" * 70)
    print("SolarSense — Pan-India Metropolitan Training Data Pipeline")
    print("=" * 70)

    start_date = "2021-01-01"
    end_date = "2023-12-31"
    cities = config.METROPOLITAN_CITIES

    print(f"\n1. Ingesting 3-year historical weather ({start_date} to {end_date})")
    print(f"   Target: {len(cities)} Metropolitan Cities across India's bioclimatic zones\n")

    city_dfs: list[pd.DataFrame] = []

    for idx, (city_key, info) in enumerate(cities.items(), 1):
        city_name = info["name"]
        lat = float(info["lat"])
        lon = float(info["lon"])
        zone = info["climate_zone"]
        tilt = float(info.get("optimal_tilt", config.DEFAULT_TILT))

        print(f"   [{idx}/{len(cities)}] {city_name:16} ({zone:18}) @ {lat:.4f}°N, {lon:.4f}°E...")

        # 1. Fetch multi-year weather with disk cache in data/raw/
        weather_df = get_historical_weather(
            lat=lat,
            lon=lon,
            start_date=start_date,
            end_date=end_date,
            tilt=tilt,
            azimuth=config.DEFAULT_AZIMUTH,
        )

        # 2. Engineer features and physically consistent power output
        X, y, feature_names = build_training_dataset(
            weather_df, capacity_kw=config.REFERENCE_PLANT_CAPACITY_KW
        )

        city_df = X.copy()
        city_df["power_kw"] = y
        city_df["city"] = city_key
        city_dfs.append(city_df)
        print(f"       -> Generated {len(city_df):,} hourly records.")

    # 3. Concatenate into a unified Pan-India training dataset
    print(f"\n2. Combining {len(city_dfs)} metropolitan datasets into unified training matrix...")
    combined_df = pd.concat(city_dfs)
    # Drop city column before saving model training features so features match input schemas
    feature_matrix_df = combined_df.drop(columns=["city"])

    # 4. Save to Disk
    output_dir = Path(config.PROCESSED_DATA_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = Path(config.TRAINING_DATA_PATH)

    print(f"\n3. Saving pan-India dataset to {parquet_path}...")
    try:
        feature_matrix_df.to_parquet(parquet_path, index=True)
        file_size_mb = parquet_path.stat().st_size / (1024 * 1024)
        print(f"   Successfully wrote Parquet file ({file_size_mb:.2f} MB).")
    except Exception as exc:
        csv_path = output_dir / "training.csv"
        print(f"   Parquet write encountered: {exc}. Falling back to CSV: {csv_path}")
        feature_matrix_df.to_csv(csv_path, index=True)
        file_size_mb = csv_path.stat().st_size / (1024 * 1024)
        print(f"   Successfully wrote CSV file ({file_size_mb:.2f} MB).")

    # 5. Dataset Summary & Verification
    print("\n4. Pan-India Dataset Verification & Statistics:")
    print(f"   Total hourly observations: {len(feature_matrix_df):,}")
    print(f"   Total features:            {len(feature_names)} ({', '.join(feature_names)})")
    print(f"   Missing values (NaNs):     {feature_matrix_df.isnull().sum().sum()}")
    print("\n   Target 'power_kw' statistics across all Indian metros:")
    print(feature_matrix_df["power_kw"].describe().round(3).to_string())

    daytime = feature_matrix_df.loc[feature_matrix_df["irradiance"] > 0, "power_kw"]
    print("\n   Target 'power_kw' (Daylight hours only):")
    print(daytime.describe().round(3).to_string())

    print("\n" + "=" * 70)
    print("Pan-India training data generation completed successfully.")
    print("=" * 70)


if __name__ == "__main__":
    main()
