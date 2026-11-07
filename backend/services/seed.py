"""
backend/services/seed.py
────────────────────────
Demonstration seeding service for SolarSense:
Populates solar installations and realistic telemetry across major Indian metropolitan cities.
"""

from datetime import date, timedelta
from typing import Any

import numpy as np

from backend import config
from backend.models.forecast import predict_for_dates
from backend.schemas import ReadingInputItem, SiteCreate
from backend.services.watchdog import (
    get_site_alerts,
    get_site_health,
    ingest_readings,
    register_site,
)

METRO_SEED_SPECS: list[dict[str, Any]] = [
    {
        "city_key": "Kolkata",
        "name": "Kolkata Rooftop Demo",
        "capacity_kw": 5.0,
        "tilt": 20.0,
        "azimuth": 180.0,
        "installed_on": date(2022, 1, 1),
        "days": 90,
        "scenario": "dust_and_fault",
    },
    {
        "city_key": "Delhi",
        "name": "Delhi NCR Commercial Solar",
        "capacity_kw": 10.0,
        "tilt": 28.0,
        "azimuth": 180.0,
        "installed_on": date(2022, 6, 1),
        "days": 60,
        "scenario": "dust_soiling",
    },
    {
        "city_key": "Mumbai",
        "name": "Mumbai Coastal Rooftop",
        "capacity_kw": 6.0,
        "tilt": 19.0,
        "azimuth": 180.0,
        "installed_on": date(2023, 1, 1),
        "days": 60,
        "scenario": "healthy",
    },
    {
        "city_key": "Bengaluru",
        "name": "Bengaluru Tech Park Solar",
        "capacity_kw": 15.0,
        "tilt": 13.0,
        "azimuth": 180.0,
        "installed_on": date(2022, 1, 1),
        "days": 60,
        "scenario": "healthy",
    },
    {
        "city_key": "Chennai",
        "name": "Chennai Industrial Rooftop",
        "capacity_kw": 8.0,
        "tilt": 13.0,
        "azimuth": 180.0,
        "installed_on": date(2019, 1, 1),
        "days": 60,
        "scenario": "ageing",
    },
    {
        "city_key": "Hyderabad",
        "name": "Hyderabad Rooftop PV",
        "capacity_kw": 7.0,
        "tilt": 17.0,
        "azimuth": 180.0,
        "installed_on": date(2022, 8, 1),
        "days": 60,
        "scenario": "healthy",
    },
    {
        "city_key": "Ahmedabad",
        "name": "Ahmedabad Solar Facility",
        "capacity_kw": 12.0,
        "tilt": 23.0,
        "azimuth": 180.0,
        "installed_on": date(2022, 1, 1),
        "days": 60,
        "scenario": "healthy",
    },
    {
        "city_key": "Pune",
        "name": "Pune Residential Solar",
        "capacity_kw": 5.0,
        "tilt": 18.0,
        "azimuth": 180.0,
        "installed_on": date(2023, 1, 1),
        "days": 60,
        "scenario": "healthy",
    },
]


def seed_site(spec: dict[str, Any], rng: np.random.Generator) -> dict[str, Any]:
    """Register and simulate telemetry for a single solar installation."""
    city_key = spec["city_key"]
    city_info = config.METROPOLITAN_CITIES[city_key]
    lat = float(city_info["lat"])
    lon = float(city_info["lon"])

    # 1. Register Site
    site_create = SiteCreate(
        user_id=1,
        name=spec["name"],
        lat=lat,
        lon=lon,
        capacity_kw=float(spec["capacity_kw"]),
        tilt=float(spec["tilt"]),
        azimuth=float(spec["azimuth"]),
        installed_on=spec["installed_on"],
    )
    site = register_site(site_create)

    # 2. Reference Time Horizon (2023 winter/spring)
    start_date = date(2023, 1, 1)
    end_date = start_date + timedelta(days=spec["days"] - 1)

    # 3. Predict Weather-Adjusted Generation
    _, daily_expected_df = predict_for_dates(
        lat=site.lat,
        lon=site.lon,
        capacity_kw=site.capacity_kw,
        tilt=site.tilt,
        azimuth=site.azimuth,
        start_date=start_date,
        end_date=end_date,
    )

    readings: list[ReadingInputItem] = []
    dates_list = list(daily_expected_df.index)
    scenario = spec["scenario"]

    for idx, d_str in enumerate(dates_list):
        day_num = idx + 1
        expected_kwh = float(daily_expected_df.loc[d_str, "predicted_energy_kwh"])
        d_val = date.fromisoformat(d_str)

        if scenario == "healthy":
            noise = float(rng.normal(0.0, 0.03))
            actual_kwh = expected_kwh * max(0.0, 0.95 + noise)
        elif scenario == "dust_soiling":
            # Days 1-30 healthy, Days 31-60 dust accumulation
            if day_num < 30:
                noise = float(rng.normal(0.0, 0.03))
                actual_kwh = expected_kwh * max(0.0, 0.95 + noise)
            else:
                progress = (day_num - 30) / 29.0
                dust_factor = 0.95 - (0.50 * progress)
                noise = float(rng.normal(0.0, 0.02))
                actual_kwh = expected_kwh * max(0.0, dust_factor + noise)
        elif scenario == "ageing":
            # Consistent shortfall around 68% PR
            noise = float(rng.normal(0.0, 0.02))
            actual_kwh = expected_kwh * max(0.0, 0.68 + noise)
        elif scenario == "dust_and_fault":
            # Kolkata signature 3-phase progression
            if day_num < 40:
                noise = float(rng.normal(0.0, 0.03))
                actual_kwh = expected_kwh * max(0.0, 0.96 + noise)
            elif day_num < 75:
                progress = (day_num - 40) / 34.0
                dust_factor = 0.95 - (0.50 * progress)
                noise = float(rng.normal(0.0, 0.02))
                actual_kwh = expected_kwh * max(0.0, dust_factor + noise)
            else:
                noise = float(rng.normal(0.0, 0.02))
                actual_kwh = expected_kwh * max(0.0, 0.18 + noise)

        readings.append(ReadingInputItem(date=d_val, actual_kwh=round(actual_kwh, 2)))

    # Ingest telemetry
    if scenario == "dust_and_fault":
        ingest_readings(site.id, readings[:74])
        ingest_readings(site.id, readings[74:])
    else:
        ingest_readings(site.id, readings)

    health = get_site_health(site.id, days=30)
    alerts = get_site_alerts(site.id)

    return {
        "site_id": site.id,
        "name": site.name,
        "capacity_kw": site.capacity_kw,
        "days": len(readings),
        "current_pr": health.current_pr,
        "alert_count": len(alerts),
    }


def seed_all_demo_sites() -> list[dict[str, Any]]:
    """Seed all 8 metropolitan installations and telemetry."""
    rng = np.random.default_rng(42)
    results = []
    for spec in METRO_SEED_SPECS:
        res = seed_site(spec, rng)
        results.append(res)
    return results

