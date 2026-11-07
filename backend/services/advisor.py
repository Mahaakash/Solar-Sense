"""
backend/services/advisor.py
───────────────────────────
Rooftop solar sizing and financial advisory service for Indian domestic/commercial consumers:
- Sizing based on monthly electricity bill (85% target offset in 0.5 kW steps).
- Physical roof-area capping (10 m² / kWp).
- 1-year historical specific yield modeling using the ML forecasting engine.
- 25-year financial lifecycle projections with panel degradation and tariff escalation.
"""

import calendar
from typing import Any

import numpy as np
import pandas as pd

from backend import config
from backend.models.forecast import predict_for_dates
from backend.schemas import (
    AdvisorRequest,
    AdvisorResponse,
    CumulativeSavingsItem,
    MonthlyGenerationItem,
)
from backend.services.weather import geocode

# In-memory cache for location specific yield: key=(round(lat,3), round(lon,3), tilt, azimuth)
_SPECIFIC_YIELD_CACHE: dict[tuple[float, float, float, float], tuple[float, list[float]]] = {}


def _get_specific_yield_and_monthly(
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
) -> tuple[float, list[float]]:
    """
    Compute specific yield (kWh / kWp / year) and monthly generation fractions for 1.0 kW system.

    Caches results in memory to avoid repetitive 8,760-hour inference for the same location.
    """
    cache_key = (round(lat, 3), round(lon, 3), round(tilt, 1), round(azimuth, 1))
    if cache_key in _SPECIFIC_YIELD_CACHE:
        return _SPECIFIC_YIELD_CACHE[cache_key]

    ref_year = config.ADVISOR_REFERENCE_YEAR
    hourly_df, _ = predict_for_dates(
        lat=lat,
        lon=lon,
        capacity_kw=1.0,
        tilt=tilt,
        azimuth=azimuth,
        start_date=f"{ref_year}-01-01",
        end_date=f"{ref_year}-12-31",
    )

    annual_specific_yield = float(hourly_df["predicted_power_kw"].sum())
    # Failsafe fallback if weather or model produces an anomalous zero
    if annual_specific_yield <= 0.0:
        annual_specific_yield = 1350.0  # Conservative typical Indian average kWh/kWp/year

    # Aggregate monthly yields (month index 1 to 12)
    dt_index = pd.DatetimeIndex(hourly_df.index)
    monthly_yields: list[float] = []
    for month in range(1, 13):
        m_mask = dt_index.month == month
        m_sum = float(hourly_df.loc[m_mask, "predicted_power_kw"].sum())
        monthly_yields.append(m_sum)

    result = (annual_specific_yield, monthly_yields)
    _SPECIFIC_YIELD_CACHE[cache_key] = result
    return result


def calculate_advisor_recommendation(request: AdvisorRequest) -> AdvisorResponse:
    """
    Run pre-installation rooftop solar sizing and financial analysis.
    """
    # 1. Location Resolution
    if request.place_name and request.place_name.strip():
        lat, lon, location_display = geocode(request.place_name)
    elif request.lat is not None and request.lon is not None:
        lat, lon = request.lat, request.lon
        location_display = f"{lat:.4f}°N, {lon:.4f}°E"
    else:
        msg = "Either 'place_name' or '(lat, lon)' coordinates must be provided."
        raise ValueError(msg)

    tilt = request.tilt if request.tilt is not None else config.DEFAULT_TILT
    azimuth = request.azimuth if request.azimuth is not None else config.DEFAULT_AZIMUTH

    # 2. Specific Yield from ML Engine
    annual_specific_yield, monthly_specific_yields = _get_specific_yield_and_monthly(
        lat=lat, lon=lon, tilt=tilt, azimuth=azimuth
    )

    # 3. Energy Consumption from Monthly Bill
    monthly_bill = request.monthly_bill_inr
    monthly_consumption_kwh = monthly_bill / config.TARIFF_INR_PER_KWH
    annual_consumption_kwh = monthly_consumption_kwh * 12.0

    # 4. Sizing System (85% Target Offset in 0.5 kW Increments)
    target_annual_generation = annual_consumption_kwh * config.ADVISOR_TARGET_OFFSET_FRACTION
    raw_capacity_kw = target_annual_generation / annual_specific_yield
    sized_kw = max(config.MIN_SYSTEM_SIZE_KW, round(raw_capacity_kw * 2.0) / 2.0)

    # 5. Roof Area Constraint
    roof_area_capped = False
    if request.roof_area_m2 is not None:
        max_roof_capacity_kw = request.roof_area_m2 / config.ROOF_AREA_PER_KW_M2
        max_roof_rounded = max(
            config.MIN_SYSTEM_SIZE_KW, np.floor(max_roof_capacity_kw * 2.0) / 2.0
        )
        if sized_kw > max_roof_rounded:
            sized_kw = max_roof_rounded
            roof_area_capped = True

    # 6. Generation & Financial Metrics
    yearly_generation_kwh = sized_kw * annual_specific_yield
    effective_offset_kwh = min(yearly_generation_kwh, annual_consumption_kwh)
    yearly_savings_inr = effective_offset_kwh * config.TARIFF_INR_PER_KWH
    system_cost_inr = sized_kw * config.SYSTEM_COST_INR_PER_KW

    if yearly_savings_inr > 0.0:
        payback_period_years = round(system_cost_inr / yearly_savings_inr, 2)
    else:
        payback_period_years = 99.0

    # 7. 25-Year Lifecycle Projection (with Annual Degradation & Tariff Escalation)
    cumulative_savings_list: list[CumulativeSavingsItem] = []
    running_cumulative_savings = 0.0

    for year in range(1, config.SYSTEM_LIFETIME_YEARS + 1):
        degradation_factor = (1.0 - config.ANNUAL_DEGRADATION_RATE) ** (year - 1)
        tariff_escalation = (1.0 + config.TARIFF_ESCALATION_RATE) ** (year - 1)

        year_gen = yearly_generation_kwh * degradation_factor
        year_tariff = config.TARIFF_INR_PER_KWH * tariff_escalation
        year_om_cost = system_cost_inr * config.OM_COST_FRACTION

        year_savings = (min(year_gen, annual_consumption_kwh) * year_tariff) - year_om_cost
        running_cumulative_savings += year_savings

        net_cumulative = running_cumulative_savings - system_cost_inr
        cumulative_savings_list.append(
            CumulativeSavingsItem(year=year, cumulative_savings_inr=round(net_cumulative, 2))
        )

    net_25yr_savings_inr = round(running_cumulative_savings - system_cost_inr, 2)

    # 8. Monthly Generation Breakdown
    monthly_generation_list: list[MonthlyGenerationItem] = []
    for month in range(1, 13):
        m_gen = sized_kw * monthly_specific_yields[month - 1]
        monthly_generation_list.append(
            MonthlyGenerationItem(
                month=month,
                month_name=calendar.month_abbr[month],
                generation_kwh=round(m_gen, 2),
            )
        )

    # 9. Assumptions Object
    assumptions: dict[str, Any] = {
        "tariff_inr_per_kwh": config.TARIFF_INR_PER_KWH,
        "tariff_escalation_rate": config.TARIFF_ESCALATION_RATE,
        "system_cost_per_kw": config.SYSTEM_COST_INR_PER_KW,
        "om_cost_fraction": config.OM_COST_FRACTION,
        "performance_ratio": config.PERFORMANCE_RATIO,
        "annual_degradation_rate": config.ANNUAL_DEGRADATION_RATE,
        "roof_area_per_kw_m2": config.ROOF_AREA_PER_KW_M2,
        "target_offset_fraction": config.ADVISOR_TARGET_OFFSET_FRACTION,
        "system_lifetime_years": config.SYSTEM_LIFETIME_YEARS,
        "specific_yield_kwh_per_kwp": round(annual_specific_yield, 1),
        "default_tilt": tilt,
        "default_azimuth": azimuth,
        "currency": config.CURRENCY_CODE,
    }

    return AdvisorResponse(
        location=location_display,
        latitude=round(lat, 4),
        longitude=round(lon, 4),
        system_size_kw=sized_kw,
        estimated_monthly_consumption_kwh=round(monthly_consumption_kwh, 2),
        estimated_annual_consumption_kwh=round(annual_consumption_kwh, 2),
        yearly_generation_kwh=round(yearly_generation_kwh, 2),
        yearly_savings_inr=round(yearly_savings_inr, 2),
        system_cost_inr=round(system_cost_inr, 2),
        payback_period_years=payback_period_years,
        net_25yr_savings_inr=net_25yr_savings_inr,
        roof_area_capped=roof_area_capped,
        monthly_generation=monthly_generation_list,
        cumulative_savings_25yr=cumulative_savings_list,
        assumptions=assumptions,
    )

