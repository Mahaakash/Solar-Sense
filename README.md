# SolarSense ☀️

> **Dual-Engine Rooftop Solar Advisor & Performance Watchdog for India**  
> *Physics-informed, weather-adjusted forecasting powering intelligent pre-installation sizing and automated post-installation fault diagnosis.*

[![Python 3.11](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.37+-FF4B4B.svg)](https://streamlit.io)
[![XGBoost](https://img.shields.io/badge/XGBoost-2.1+-eb7434.svg)](https://xgboost.readthedocs.io/)
[![Tests Passing](https://img.shields.io/badge/tests-43%20passed-brightgreen.svg)](#running-tests)

---

## 📌 Problem Statement

Rooftop solar adoption across Indian homes and commercial establishments suffers from two critical friction points:

1. **Pre-Installation Planning Uncertainty**: Homeowners receive aggressive, opaque vendor estimates with oversized systems, unrealistic generation claims, and vague payback timelines. Solar capacity should be tailored to actual consumption patterns, roof constraints, local solar irradiance, and seasonal monsoon drops.
2. **Post-Installation Silent Failures**: Once installed, solar systems operate "blindly." When generation drops, owners cannot distinguish ordinary cloud cover from:
   - **Severe Dust & Soiling**: Airborne particulates and soot cause 15–30% gradual output degradation in dry months, remaining unaddressed without rain awareness.
   - **Critical Electrical Faults**: Blown string fuses, inverter trips, or disconnected arrays go unnoticed for weeks, quietly draining financial returns.
   - **Abnormal Module Ageing**: Undetected degradation exceeding manufacturer linear performance warranties.

**SolarSense bridges this divide** through a single unified engine: a **weather-adjusted machine learning model** that calculates expected generation based on real-time solar irradiance and temperature.

---

## 🏗️ System Architecture

```
+-------------------------------------------------------------------------------------------------+
|                                     EXTERNAL WEATHER SERVICES                                   |
|                         Open-Meteo Historical Archive & Live Forecast APIs                      |
+------------------------------------------------+------------------------------------------------+
                                                 | (Hourly Irradiance, POA, Temp, Rain, Wind)
                                                 v
+-------------------------------------------------------------------------------------------------+
|                                     SOLARSENSE CORE ENGINE                                      |
|                                                                                                 |
|   +--------------------------+    +--------------------------+    +--------------------------+  |
|   |   Feature Engineering    |    |  XGBoost Weather-to-Power|    |   Physics Derating Engine|  |
|   | - Solar sin/cos encoding |--> |  Model (solar_xgb.joblib)|--> | - Evans cell temp model  |  |
|   | - Lagged/rolling POA GHI |    |  MAE: 0.027 kW, R²: 0.995|    | - Temp coeff (-0.004/°C) |  |
|   +--------------------------+    +--------------------------+    +--------------------------+  |
+------------------------------------------------+------------------------------------------------+
                                                 |
                                                 v
+-------------------------------------------------------------------------------------------------+
|                                      FASTAPI BACKEND SERVICE                                    |
|                                                                                                 |
|   +--------------------------+    +--------------------------+    +--------------------------+  |
|   |   Mode 1: Solar Advisor  |    |  Mode 2: Watchdog Engine |    |   APScheduler Daily Job  |  |
|   | - 85% target sizing      |    | - Weather-adjusted PR    |    | - Daily automated scan   |  |
|   | - Roof area capping      |    | - Dust decline detection |    | - Auto alert dispatch    |  |
|   | - 25-yr financial returns|    | - Sudden fault detection |    | - Single-site manual API |  |
|   +--------------------------+    +--------------------------+    +--------------------------+  |
|                                                |                                                |
|                                                v                                                |
|                                   +--------------------------+                                  |
|                                   |  Alert Notifier Subsystem|                                  |
|                                   | - EmailNotifier (SMTP)   |                                  |
|                                   | - WhatsAppNotifier (Stub)|                                  |
|                                   +--------------------------+                                  |
+------------------------------------------------+------------------------------------------------+
                                                 | JSON REST API (Port 8000)
                                                 v
+-------------------------------------------------------------------------------------------------+
|                                STREAMLIT MULTI-PAGE FRONTEND (Port 8501)                        |
|                                                                                                 |
|   +--------------------------+    +--------------------------+    +--------------------------+  |
|   |     1_Advisor.py         |    |      2_My_System.py      |    |       3_Alerts.py        |  |
|   | - 4 Key metrics (kWp, ₹) |    | - CSV upload & manual    |    | - Color-coded feed       |  |
|   | - 12-Month yield chart   |    | - 30-Day actual vs exp   |    | - kWh & ₹ loss callouts  |  |
|   | - 25-Yr cumulative curve |    | - 7-Day PR health badge  |    | - "Why did I get alert?" |  |
|   +--------------------------+    +--------------------------+    +--------------------------+  |
+-------------------------------------------------------------------------------------------------+
```

---

## 🚀 Setup & Execution

### Option A: Local Setup (Without Docker)

#### 1. Prerequisites
- Python 3.11+
- Git

#### 2. Environment Preparation
```bash
# Clone the repository
cd SOLARSENSE

# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### 3. Configuration
Copy the configuration template:
```bash
cp .env.example .env
```
*(Optionally adjust email SMTP credentials or leave defaults for local evaluation).*

#### 4. Train the Weather-to-Power Forecast Model
Generate synthetic physics training data and train the XGBoost regressor:
```bash
# 1. Build 3-year historical dataset for Kolkata reference plant
python scripts/make_training_data.py

# 2. Train the XGBoost regressor using time-based split
python scripts/train_model.py
```
*(Saves trained model to `backend/models/solar_xgb.joblib` and evaluation plots to `notebooks/`).*

#### 5. Launch the Application
Start the backend and frontend in separate terminals:

**Terminal 1 — FastAPI Backend:**
```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 — Streamlit Frontend:**
```bash
python -m streamlit run frontend/app.py --server.port 8501
```
Open **[http://localhost:8501](http://localhost:8501)** in your browser.

---

### Option B: Multi-Container Setup (With Docker Compose)

Both services can be run in containerized environments with shared persistent storage for the SQLite database and trained model.

#### 1. Configure Environment
```bash
cp .env.example .env
```

#### 2. Exact Docker Commands
```bash
# Build images and start backend + frontend in detached mode
docker compose up -d --build

# View real-time logs
docker compose logs -f

# Verify container health
docker compose ps

# Stop containers
docker compose down
```

**Container Port Mapping:**
- **Frontend Dashboard**: [http://localhost:8501](http://localhost:8501)
- **Backend API & Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🚀 Cloud Deployment (Render & Streamlit Community Cloud)

SolarSense is designed for distributed, cost-free cloud hosting with:
- **Backend on Render**: Containerized FastAPI service running on Render's Docker Web Service runtime.
- **Frontend on Streamlit Community Cloud**: Serverless Streamlit dashboard connected directly to your GitHub repository.
- **Automated Screening via GitHub Actions**: Daily cron webhook dispatching watchdog evaluations even when the free-tier backend is sleeping.

---

### 1. Deploying the Backend on Render

1. **Push Repository to GitHub**: Ensure `backend/models/solar_xgb.joblib` is committed (permitted by `.gitignore`).
2. **(Optional) Create a Free Hosted PostgreSQL Database**:
   - **Neon / Supabase / Render Postgres**: Create a free PostgreSQL instance.
   - Copy the PostgreSQL connection URI.
   - Note: Render and Neon URIs starting with `postgres://` or `postgresql://` are automatically normalised by SolarSense to use the modern `postgresql+psycopg://` driver.
3. **Create New Web Service on Render**:
   - Log into [Render Dashboard](https://dashboard.render.com/) and click **New +** -> **Web Service**.
   - Connect your SolarSense GitHub repository.
   - Choose **Docker** as the Environment.
   - Set **Branch** to `main` (or your active branch).
   - Health Check Path: `/health`.
4. **Configure Environment Variables**:
   Under **Environment Variables**, add:
   - `DATABASE_URL`: `postgresql://user:password@host:5432/dbname?sslmode=require` *(leave blank to default to local SQLite)*
   - `DEMO_MODE`: `true` *(auto-seeds 8 Indian metropolitan sites if the database is initialized empty)*
   - `DISABLE_SCHEDULER`: `true` *(disables local APScheduler loop; scheduled jobs are triggered by external cron)*
   - `CRON_SECRET`: *(generate a secure random secret, e.g. `openssl rand -hex 16`)*
   - `ALLOWED_ORIGINS`: `https://<your-subdomain>.streamlit.app,http://localhost:8501`
   - `EMAIL_ENABLED`: `false` *(or `true` with your SMTP credentials)*
5. **Deploy**:
   Click **Create Web Service**. Render will build the container using `Dockerfile` and expose it at `https://<service-name>.onrender.com`.

> [!TIP]
> **Database Health Check & Debugging**:
> - Use `GET /health` for fast container health checks (no DB calls, ideal for load balancers).
> - Use `GET /health/db` to verify database connectivity and report the active dialect (`sqlite` or `postgresql`).

> [!NOTE]
> **Data Migration (SQLite to Postgres)**:
> If you have local data in `data/solarsense.db` and want to migrate it to your hosted Postgres instance:
> ```bash
> DATABASE_URL="postgresql://user:password@host:5432/dbname?sslmode=require" python scripts/migrate_sqlite_to_postgres.py
> # Use --force to truncate target tables if re-migrating
> DATABASE_URL="postgresql://user:password@host:5432/dbname?sslmode=require" python scripts/migrate_sqlite_to_postgres.py --force
> ```

> [!NOTE]
> **Database Schema & Migrations**:
> Tables are automatically created on startup via `Base.metadata.create_all()` with automated connection retries.
> For advanced production schema migrations (e.g., column renames or type changes), Alembic can be introduced later (`alembic init alembic`) once production data lifecycle requires schema versioning.

> [!NOTE]
> **Render Free-Tier Limitations**:
> - **Inactivity Sleep**: Render spins down free containers after 15 minutes of inactivity.
> - **Wake-Up Latency**: When an incoming request arrives, the instance takes 30–50 seconds to boot up. SolarSense's frontend automatically detects this and shows a waking spinner with up to 3 automatic retries.
> - **Ephemeral Storage**: Free instances reset their local SQLite database on restart. `DEMO_MODE=true` ensures all 8 metro installations and telemetry automatically repopulate on every cold boot.

---

### 2. Deploying the Frontend on Streamlit Community Cloud

1. **Connect Repository**:
   - Go to [share.streamlit.io](https://share.streamlit.io/) and click **New app**.
   - Select your SolarSense GitHub repository and branch.
   - **Main file path**: `frontend/app.py`.
2. **Configure Secrets**:
   Under **Advanced settings** -> **Secrets (TOML)**, add your Render backend URL:
   ```toml
   BACKEND_URL = "https://<your-service-name>.onrender.com"
   ```
3. **Deploy**:
   Click **Deploy!**. Streamlit will install minimal dependencies from `frontend/requirements.txt` and launch the interface.

---

### 3. Setting Up Daily Automated Watchdog (GitHub Actions)

Because Render free tier sleeps, local scheduler loops (APScheduler) may be paused. SolarSense includes a pre-configured GitHub Actions workflow (`.github/workflows/daily-check.yml`) that wakes the backend and triggers watchdog screening daily:

1. In your GitHub repository, navigate to **Settings** -> **Secrets and variables** -> **Actions**.
2. Click **New repository secret** and add:
   - `BACKEND_URL`: `https://<your-service-name>.onrender.com`
   - `CRON_SECRET`: *(the same secret configured on Render)*
3. The workflow runs every day at 15:30 UTC (9:00 PM IST) and can also be triggered manually under the **Actions** tab.

---

## 🧪 Demo Walkthrough (Multi-Metro Seed Script)

SolarSense includes an automated seeder that demonstrates every diagnostic rule across 8 major Indian metropolitan cities (Delhi NCR, Mumbai, Kolkata, Chennai, Bengaluru, Hyderabad, Ahmedabad, Pune):

```bash
python scripts/seed_demo.py
```

### What the Demo Simulates Across Indian Metros:
1. **Kolkata Rooftop Demo (5.0 kWp, Humid Subtropical)**:
   - Days 1–39: Healthy baseline operation (~95% PR).
   - Days 40–74: Gradual winter dust accumulation (< 1 mm rain) triggering **Warning: Dust Alert**.
   - Days 75–90: Sudden clear-sky inverter/string drop (60% collapse) triggering **Critical: Fault Alert**.
2. **Delhi NCR Commercial Solar (10.0 kWp, Composite)**: Severe winter smog & dust accumulation triggering **Warning: Dust Alert**.
3. **Mumbai Coastal Rooftop (6.0 kWp, Warm & Humid)**: Continuous clean operation (~93% PR) demonstrating **Healthy Baseline**.
4. **Bengaluru Tech Park Solar (15.0 kWp, Temperate Plateau)**: Stable commercial performance (~95.6% PR) demonstrating **Healthy Baseline**.
5. **Chennai Industrial Rooftop (8.0 kWp, Tropical Wet & Dry)**: 4-year-old installation with excess degradation triggering **Warning: Ageing Alert**.
6. **Hyderabad Rooftop PV (7.0 kWp, Semi-Arid)**: Healthy residential performance (~93.4% PR).
7. **Ahmedabad Solar Facility (12.0 kWp, Hot Semi-Arid)**: High-irradiance healthy generation (~95.8% PR).
8. **Pune Residential Solar (5.0 kWp, Semi-Arid Plateau)**: Healthy residential rooftop (~94.0% PR).

### Inspecting the Results:
1. Open **[http://localhost:8501](http://localhost:8501)** and navigate to **Advisor**:
   - Use the **Quick Select Metropolitan City** buttons (`Delhi`, `Mumbai`, `Kolkata`, `Chennai`, `Bengaluru`, `Hyderabad`, `Ahmedabad`, `Pune`) to instantly load climate-optimal tilt angles and coordinates.
2. Navigate to **My System**:
   - Select any metropolitan installation from the dropdown (e.g. `Kolkata Rooftop Demo`, `Delhi NCR Commercial Solar`, `Chennai Industrial Rooftop`).
   - Inspect the **30-Day Expected vs. Actual** line chart and performance ratio.
3. Navigate to **Alerts**:
   - Inspect the multi-city alerts: **Critical Fault**, **Warning Dust**, and **Warning Ageing**.
   - Click `"Why did I get this alert?"` to view the technical and meteorological explanation.
   - Click `"🔍 Run Check Now"` to trigger an on-demand watchdog evaluation across all sites.

---

## 📊 Data Limitations

- **Synthetic Baseline Telemetry**: In the absence of proprietary inverter telemetry, plant power output (`power_kw`) for model training is generated synthetically using standard PV physical equations:
  $$\text{cell\_temp} = \text{temp\_2m} + 0.03 \times \text{irradiance}$$
  $$\text{power\_kw} = \text{capacity\_kw} \times \frac{\text{irradiance}}{1000} \times \text{PR} \times [1 + \gamma (\text{cell\_temp} - 25)]$$
  with simulated Gaussian noise (3–5%) and intermittent cloud dips.
- **Model Role**: The machine learning model learns the physical and diurnal relationship between solar irradiance, ambient temperature, time of day, day of year, and power output.
- **Production Calibration**: For production commercial utility or residential deployment, this synthetic baseline should be fine-tuned with 30–90 days of actual inverter smart-meter telemetry.

---

## 🔮 Future Roadmap

- [ ] **Direct Inverter IoT Telemetry**: Native cloud connectors and edge protocols (Modbus TCP/RTU, RS485, SolarEdge, Enphase Enlighten, Sungrow iSolarCloud, Growatt, and MQTT brokers) for real-time minute-by-minute streaming.
- [ ] **Two-Way WhatsApp Interactive Bot**: Complete the Twilio integration to allow homeowners to text `"Report"` or `"Cleaning Done"` to log maintenance and clear soiling warnings directly from WhatsApp.
- [ ] **Automated Satellite Soiling Index**: Incorporate Copernicus atmosphere aerosol optical depth (AOD) and particulate matter ($PM_{2.5} / PM_{10}$) data for predictive dust alerts.
- [ ] **Drone & Thermal Infrared Inspection (IEC 62446-3)**: Upload aerial thermography or smartphone FLIR thermal images for automated CNN-based detection of hot spots, localized cell micro-cracks, and bypassed string diodes.
- [ ] **DISCOM Net-Metering Tariff Engine**: State-specific tariff structures (West Bengal WBSEDCL, Maharashtra MSEDCL, Delhi BSES, Karnataka BESCOM) with time-of-day (ToD) export rates and net-billing rules.

---

## 🧪 Running Tests & Linting

```bash
# Execute the full pytest test suite (43 unit & integration tests)
python -m pytest tests/ -v

# Run code formatting and linting checks
python -m ruff check backend frontend tests scripts
```

---

## 📜 License
Apache-2.0 License. Built for clean energy resilience in India.
