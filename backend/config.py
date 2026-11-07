"""
backend/config.py
─────────────────
Single source of truth for every tuneable assumption in SolarSense.
All monetary values are in INR.  All power values are in kW / kWh.
"""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load environment variables from .env file at project root if present
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Electricity tariff ──────────────────────────────────────────────
TARIFF_INR_PER_KWH: float = 8.0          # Average Indian domestic tariff (₹/kWh)

# ── Solar system economics ──────────────────────────────────────────
SYSTEM_COST_INR_PER_KW: float = 55_000.0  # Installed cost per kWp (panels, inverter, BoS, labour)

# ── Solar performance parameters ────────────────────────────────────
PERFORMANCE_RATIO: float = 0.78           # Fraction of theoretical output realised in practice
ANNUAL_DEGRADATION_RATE: float = 0.005    # 0.5 % per year panel output degradation
TEMPERATURE_COEFFICIENT: float = -0.004   # Power change per °C above STC 25 °C (fraction/°C)
ROOF_AREA_PER_KW_M2: float = 10.0        # Approx roof area needed per kWp installed (m²)
TILT_FACTOR: float = 1.0                 # Multiplier for non-optimal tilt (1.0 = latitude-optimal)

# ── Watchdog thresholds ─────────────────────────────────────────────
PR_ALERT_LEVEL: float = 0.60             # 7-day avg performance ratio below this triggers alert
SUDDEN_DROP_PCT: float = 0.50            # Single-day drop ≥ 50 % flags a sudden fault
DUST_DECLINE_WINDOW_DAYS: int = 14       # 2+ weeks sustained under-performance for dust/soiling
DUST_MAX_RAIN_MM: float = 2.0            # Max rainfall during dust decline window (mm)
MIN_EXPECTED_DAILY_KWH: float = 0.5      # Skip PR calculation on dark/overcast days (< 0.5 kWh)
CLEAR_SKY_MIN_EXPECTED_KWH_PER_KW: float = 2.5  # Clear-sky yield threshold (kWh/kWp)
AGEING_EXTRA_SHORTFALL: float = 0.05     # 5 % shortfall beyond normal degradation curve
RAIN_FORECAST_WINDOW_DAYS: int = 2       # Lookahead window for upcoming rain (days)
RAIN_FORECAST_THRESHOLD_MM: float = 1.0  # Min precipitation to advise cleaning unneeded (mm)
ALERT_DEDUPLICATION_DAYS: int = 7        # Suppress identical alerts within 7 days
WATCHDOG_EVALUATION_DAYS: int = int(
    os.environ.get("WATCHDOG_EVALUATION_DAYS", "45")
)  # Bounded history window for watchdog (days)

# ── Open-Meteo API URLs and retry configuration ─────────────────────
OPEN_METEO_FORECAST_URL: str = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HISTORICAL_URL: str = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_GEOCODING_URL: str = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_TIMEOUT_SECONDS: int = 15     # Per-request timeout in seconds
OPEN_METEO_MAX_RETRIES: int = 3          # Maximum HTTP retries for transient errors
OPEN_METEO_BACKOFF_FACTOR: float = 0.5   # Backoff multiplier between retries

# ── Cache directory ─────────────────────────────────────────────────
CACHE_DIR_RAW: str = "data/raw"          # Directory for raw JSON responses

# ── Synthetic generation & feature engineering assumptions ──────────
REFERENCE_PLANT_CAPACITY_KW: float = 5.0      # Reference rooftop size for synthetic training (kWp)
CELL_TEMP_IRRADIANCE_FACTOR: float = 0.03    # Temp rise per W/m² irradiance (°C per W/m²)
STC_TEMPERATURE_C: float = 25.0              # Standard test conditions reference cell temp (°C)
SYNTHETIC_NOISE_STD: float = 0.04            # ~4 % Gaussian noise on daytime generation
SYNTHETIC_DIP_PROBABILITY: float = 0.02      # 2 % probability per daylight hour of cloud/dust dip
SYNTHETIC_DIP_MIN_REDUCTION: float = 0.20    # Minimum drop during dip (20 %)
SYNTHETIC_DIP_MAX_REDUCTION: float = 0.50    # Maximum drop during dip (50 %)

# ── Processed dataset paths ─────────────────────────────────────────
PROCESSED_DATA_DIR: str = "data/processed"
TRAINING_DATA_PATH: str = "data/processed/training.parquet"

# ── Model configuration & persistence ───────────────────────────────
MODEL_PATH: str = "backend/models/solar_xgb.joblib"
MODEL_TEST_MONTHS: int = 6                # Chronological test split size (last 6 months)
XGB_N_ESTIMATORS: int = 250               # Number of boosting rounds
XGB_MAX_DEPTH: int = 6                    # Maximum tree depth
XGB_LEARNING_RATE: float = 0.05           # Boosting learning rate
XGB_SUBSAMPLE: float = 0.8                # Row subsampling ratio
XGB_COLSAMPLE_BYTREE: float = 0.8         # Feature subsampling ratio
XGB_RANDOM_STATE: int = 42                # Reproducibility seed

# ── Diagnostic plot artifact paths ──────────────────────────────────
PLOT_FORECAST_CHECK_PATH: str = "notebooks/forecast_check.png"
PLOT_FEATURE_IMPORTANCE_PATH: str = "notebooks/feature_importance.png"

# ── Advisor economic & sizing assumptions ───────────────────────────
ADVISOR_TARGET_OFFSET_FRACTION: float = 0.85  # Target 85 % annual consumption offset
MIN_SYSTEM_SIZE_KW: float = 0.5               # Smallest practical system size (kWp)
SYSTEM_LIFETIME_YEARS: int = 25               # Economic analysis horizon (years)
TARIFF_ESCALATION_RATE: float = 0.03          # Annual electricity tariff escalation (3 %)
OM_COST_FRACTION: float = 0.01                # Annual O&M cost fraction of Capex (1 %)
DEFAULT_TILT: float = 20.0                    # Standard rooftop tilt angle (degrees)
DEFAULT_AZIMUTH: float = 180.0                # South-facing orientation (degrees)
ADVISOR_REFERENCE_YEAR: str = "2023"          # Reference historical year for yield

# ── Database ────────────────────────────────────────────────────────
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///data/solarsense.db")

# ── Currency ────────────────────────────────────────────────────────
CURRENCY_SYMBOL: str = "₹"
CURRENCY_CODE: str = "INR"

# ── Alert Notification Channels ─────────────────────────────────────
EMAIL_ENABLED: bool = os.environ.get("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER: str = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM: str = os.environ.get("EMAIL_FROM", "alerts@solarsense.local")
EMAIL_TO: str = os.environ.get("EMAIL_TO", "")

WHATSAPP_ENABLED: bool = os.environ.get("WHATSAPP_ENABLED", "false").lower() == "true"
TWILIO_ACCOUNT_SID: str = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_NUMBER: str = os.environ.get("TWILIO_WHATSAPP_NUMBER", "")
WHATSAPP_TO: str = os.environ.get("WHATSAPP_TO", "")

# ── Cloud Deployment & Automation ──────────────────────────────────
DEMO_MODE: bool = os.environ.get("DEMO_MODE", "false").lower() == "true"
DISABLE_SCHEDULER: bool = os.environ.get("DISABLE_SCHEDULER", "false").lower() == "true"
CRON_SECRET: str = os.environ.get("CRON_SECRET", "solarsense-cron-secret")
ALLOWED_ORIGINS_RAW: str = os.environ.get("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS: list[str] = [
    orig.strip() for orig in ALLOWED_ORIGINS_RAW.split(",") if orig.strip()
]

# ── Scheduled Background Watchdog ───────────────────────────────────
SCHEDULER_ENABLED: bool = (
    not DISABLE_SCHEDULER and os.environ.get("SCHEDULER_ENABLED", "true").lower() == "true"
)
WATCHDOG_DAILY_RUN_HOUR: int = int(os.environ.get("WATCHDOG_DAILY_RUN_HOUR", "21"))

# ── Major Indian Metropolitan Cities Registry ───────────────────────
METROPOLITAN_CITIES: dict[str, dict[str, Any]] = {
    "Delhi": {
        "name": "Delhi (NCR)",
        "state": "Delhi",
        "lat": 28.6139,
        "lon": 77.2090,
        "optimal_tilt": 28.0,
        "climate_zone": "Composite",
    },
    "Mumbai": {
        "name": "Mumbai",
        "state": "Maharashtra",
        "lat": 19.0760,
        "lon": 72.8777,
        "optimal_tilt": 19.0,
        "climate_zone": "Warm & Humid",
    },
    "Kolkata": {
        "name": "Kolkata",
        "state": "West Bengal",
        "lat": 22.5626,
        "lon": 88.3630,
        "optimal_tilt": 22.0,
        "climate_zone": "Humid Subtropical",
    },
    "Chennai": {
        "name": "Chennai",
        "state": "Tamil Nadu",
        "lat": 13.0827,
        "lon": 80.2707,
        "optimal_tilt": 13.0,
        "climate_zone": "Tropical Wet & Dry",
    },
    "Bengaluru": {
        "name": "Bengaluru",
        "state": "Karnataka",
        "lat": 12.9716,
        "lon": 77.5946,
        "optimal_tilt": 13.0,
        "climate_zone": "Temperate Plateau",
    },
    "Hyderabad": {
        "name": "Hyderabad",
        "state": "Telangana",
        "lat": 17.3850,
        "lon": 78.4867,
        "optimal_tilt": 17.0,
        "climate_zone": "Semi-Arid",
    },
    "Ahmedabad": {
        "name": "Ahmedabad",
        "state": "Gujarat",
        "lat": 23.0225,
        "lon": 72.5714,
        "optimal_tilt": 23.0,
        "climate_zone": "Hot Semi-Arid",
    },
    "Pune": {
        "name": "Pune",
        "state": "Maharashtra",
        "lat": 18.5204,
        "lon": 73.8567,
        "optimal_tilt": 18.0,
        "climate_zone": "Semi-Arid Plateau",
    },
}
