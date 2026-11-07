"""
backend/schemas.py
──────────────────
Pydantic v2 models for request / response validation.
Placeholder — fields will grow as we add endpoints.
"""

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Site schemas ────────────────────────────────────────────────────

class SiteBase(BaseModel):
    """Fields shared by create and read operations."""
    name: str = Field(..., description="Human-readable site name")
    lat: float = Field(..., ge=-90, le=90, description="Latitude (decimal degrees)")
    lon: float = Field(..., ge=-180, le=180, description="Longitude (decimal degrees)")
    capacity_kw: float = Field(..., gt=0, description="Installed capacity in kWp")
    tilt: float = Field(0.0, ge=0, le=90, description="Panel tilt angle (degrees)")
    azimuth: float = Field(180.0, ge=0, le=360, description="Panel azimuth (degrees, 180=south)")
    installed_on: dt.date = Field(..., description="Date the system was installed")


class SiteCreate(SiteBase):
    """Payload for creating a new site."""
    user_id: int = Field(1, description="Owner user ID (defaults to 1 for demo user)")


class SiteRead(SiteBase):
    """Site record as returned by the API."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    calibrated_performance_ratio: float | None = None


# ── Ingestion & Calibration schemas ─────────────────────────────────

class ImportReportResponse(BaseModel):
    """Structured report returned after importing real generation CSV data."""
    status: str = Field("ok", description="Import outcome status")
    site_id: int = Field(..., description="Target site ID")
    detected_format: str = Field(
        ..., description="Detected format: daily_kwh, interval_kwh, or interval_kw"
    )
    energy_column: str = Field(..., description="Matched CSV column for energy/power")
    energy_unit: str = Field(..., description="Interpreted energy/power unit")
    rows_read: int = Field(..., description="Total CSV rows processed")
    days_created: int = Field(..., description="Number of daily readings created or updated")
    rows_skipped: int = Field(0, description="Number of invalid rows skipped")
    skip_reasons: dict[str, int] = Field(
        default_factory=dict, description="Count of skipped rows by reason"
    )
    date_range: dict[str, str | None] = Field(
        default_factory=lambda: {"start": None, "end": None},
        description="First and last dates ingested",
    )


class CalibrationResponse(BaseModel):
    """Result of empirical clear-sky performance ratio calibration."""
    status: str = Field("calibrated", description="Calibration outcome")
    site_id: int = Field(..., description="Site ID")
    calibrated_performance_ratio: float = Field(
        ..., description="Empirical performance ratio estimate (median of clear-sky days)"
    )
    clear_sky_days_used: int = Field(..., description="Number of clear-sky days used for median")
    total_days_evaluated: int = Field(
        ..., description="Total days evaluated from available readings"
    )


# ── Reading schemas ─────────────────────────────────────────────────

class ReadingBase(BaseModel):
    """Fields shared by create and read operations."""
    site_id: int = Field(..., description="Associated site ID")
    date: dt.date = Field(..., description="Date of the reading")
    actual_kwh: float = Field(..., ge=0, description="Measured generation (kWh)")


class ReadingCreate(ReadingBase):
    """Payload for logging a new daily reading."""
    pass


class ReadingInputItem(BaseModel):
    """Individual daily reading item without site_id (for batch submissions)."""
    date: dt.date = Field(..., description="Date of generation")
    actual_kwh: float = Field(..., ge=0, description="Actual generation in kWh")


class ReadingsSubmission(BaseModel):
    """Batch submission payload for daily readings."""
    site_id: int = Field(..., description="Associated site ID")
    readings: list[ReadingInputItem] = Field(..., description="List of daily generation readings")


class ReadingRead(ReadingBase):
    """Reading record as returned by the API."""
    model_config = ConfigDict(from_attributes=True)

    id: int


# ── Watchdog & Health schemas ───────────────────────────────────────

class DailyHealthItem(BaseModel):
    """Daily expected vs actual generation comparison."""
    date: str = Field(..., description="Date (YYYY-MM-DD)")
    actual_kwh: float = Field(..., ge=0, description="Actual recorded generation (kWh)")
    expected_kwh: float = Field(..., ge=0, description="Weather-adjusted expected generation (kWh)")
    performance_ratio: float | None = Field(
        None, description="Actual / Expected ratio (None if expected < 0.5 kWh)"
    )


class AlertRead(BaseModel):
    """Diagnosed watchdog alert."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    date: str
    severity: str
    cause: str
    message: str
    created_at: str


class SiteHealthResponse(BaseModel):
    """Complete 30-day site health and diagnostic status."""
    site_id: int = Field(..., description="Site ID")
    site_name: str = Field(..., description="Site name")
    capacity_kw: float = Field(..., description="Installed system capacity (kWp)")
    current_pr: float | None = Field(
        None, description="Current 7-day average performance ratio"
    )
    last_30_days: list[DailyHealthItem] = Field(
        ..., description="Daily comparison time-series for the past 30 days"
    )
    latest_alerts: list[AlertRead] = Field(
        ..., description="Active and historical alerts diagnosed by Watchdog"
    )


# ── Forecast schemas ────────────────────────────────────────────────

class HourlyForecastItem(BaseModel):
    """Hourly power generation prediction and meteorological context."""
    timestamp: str = Field(..., description="ISO 8601 timestamp with timezone")
    predicted_power_kw: float = Field(..., ge=0, description="Predicted power output (kW)")
    irradiance: float = Field(..., ge=0, description="Plane-of-array irradiance (W/m²)")
    temperature_2m: float = Field(..., description="Ambient temperature (°C)")


class DailyForecastItem(BaseModel):
    """Aggregated daily forecast summary."""
    date: str = Field(..., description="Forecast date (YYYY-MM-DD)")
    predicted_energy_kwh: float = Field(..., ge=0, description="Total daily energy yield (kWh)")
    peak_power_kw: float = Field(..., ge=0, description="Peak hourly power output (kW)")


class ForecastResponse(BaseModel):
    """Complete forecast API response."""
    site_capacity_kw: float = Field(..., description="Capacity used for scaling (kWp)")
    latitude: float = Field(..., description="Site latitude")
    longitude: float = Field(..., description="Site longitude")
    hourly: list[HourlyForecastItem] = Field(..., description="Hourly forecast time-series")
    daily: list[DailyForecastItem] = Field(..., description="Daily summarized energy output")


# ── Advisor schemas ─────────────────────────────────────────────────

class AdvisorRequest(BaseModel):
    """Input payload for pre-installation rooftop solar sizing & financial analysis."""
    place_name: str | None = Field(None, description="City, town, or address in India")
    lat: float | None = Field(None, ge=-90.0, le=90.0, description="Latitude (optional)")
    lon: float | None = Field(None, ge=-180.0, le=180.0, description="Longitude (optional)")
    monthly_bill_inr: float = Field(..., description="Average monthly electricity bill (INR)")
    roof_area_m2: float | None = Field(None, description="Available shadow-free roof area (m²)")
    tilt: float | None = Field(None, ge=0.0, le=90.0, description="Panel tilt angle (degrees)")
    azimuth: float | None = Field(None, ge=0.0, le=360.0, description="Panel azimuth (degrees)")


class MonthlyGenerationItem(BaseModel):
    """Monthly generation breakdown."""
    month: int = Field(..., ge=1, le=12, description="Month number (1=Jan, 12=Dec)")
    month_name: str = Field(..., description="Abbreviated month name (e.g. Jan)")
    generation_kwh: float = Field(..., ge=0, description="Estimated monthly energy yield (kWh)")


class CumulativeSavingsItem(BaseModel):
    """Year-by-year cumulative financial savings."""
    year: int = Field(..., ge=1, le=25, description="Year of system operation (1 to 25)")
    cumulative_savings_inr: float = Field(
        ..., description="Cumulative net savings after initial investment (INR)"
    )


class AdvisorResponse(BaseModel):
    """Output results from the SolarSense rooftop advisor."""
    location: str = Field(..., description="Resolved location name or coordinates")
    latitude: float = Field(..., description="Latitude used for modeling")
    longitude: float = Field(..., description="Longitude used for modeling")
    system_size_kw: float = Field(..., description="Recommended system capacity (kWp)")
    estimated_monthly_consumption_kwh: float = Field(
        ..., description="Estimated monthly consumption based on tariff (kWh)"
    )
    estimated_annual_consumption_kwh: float = Field(
        ..., description="Estimated annual consumption (kWh)"
    )
    yearly_generation_kwh: float = Field(..., description="First-year solar generation (kWh)")
    yearly_savings_inr: float = Field(..., description="First-year electricity bill savings (INR)")
    system_cost_inr: float = Field(..., description="Estimated turnkey installed cost (INR)")
    payback_period_years: float = Field(..., description="Simple payback period (years)")
    net_25yr_savings_inr: float = Field(
        ..., description="25-year cumulative net savings considering degradation and tariff rise"
    )
    roof_area_capped: bool = Field(
        ..., description="True if system size was limited by available roof area"
    )
    monthly_generation: list[MonthlyGenerationItem] = Field(
        ..., description="12-month expected generation breakdown"
    )
    cumulative_savings_25yr: list[CumulativeSavingsItem] = Field(
        ..., description="25-year year-by-year cumulative net savings projection"
    )
    assumptions: dict[str, Any] = Field(
        ..., description="Dictionary of all financial and technical assumptions used"
    )


