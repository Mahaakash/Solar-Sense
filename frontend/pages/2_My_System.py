"""
frontend/pages/2_My_System.py
─────────────────────────────
My System: Rooftop solar site registration, telemetry ingestion, and expected vs actual monitoring.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

from frontend.api_client import (
    ApiClientError,
    check_health,
    get_site_health,
    list_sites,
    register_site,
    submit_readings_json,
    upload_readings_csv,
)
from frontend.theme import (
    apply_custom_theme,
    create_telemetry_comparison_chart,
    render_hero,
)

st.set_page_config(
    page_title="My System — SolarSense",
    page_icon="📊",
    layout="wide",
)

# Apply global dark glassmorphism theme and custom fonts
apply_custom_theme()

is_online = check_health()

# ── Sidebar Navigation ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ☀️ SolarSense")
    st.caption("Rooftop Solar Advisor & Watchdog")
    st.divider()
    if is_online:
        st.html(
            """
            <div style="padding: 10px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 8px; font-size: 0.82rem;">
                <span class="pulse-online"></span><strong style="color: #34D399;">Backend Online</strong>
            </div>
            """
        )
    else:
        st.html(
            """
            <div style="padding: 10px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; font-size: 0.82rem;">
                <span class="pulse-alert"></span><strong style="color: #F87171;">Backend Offline</strong>
            </div>
            """
        )
    st.divider()
    st.page_link("app.py", label="Home Dashboard", icon="🏠")
    st.page_link("pages/1_Advisor.py", label="Solar Advisor", icon="💡")
    st.page_link("pages/2_My_System.py", label="My System", icon="📊")
    st.page_link("pages/3_Alerts.py", label="Alerts & Diagnostics", icon="🚨")

# ── Page Header ─────────────────────────────────────────────────────
render_hero(
    title="📊 My System Telemetry & Performance",
    subtitle="Track daily metered inverter kWh against weather-adjusted expectations to pinpoint dust soiling, cloud dips, or electrical string faults.",
    badge_text="TELEMETRY SCREENING ACTIVE",
    badge_type="online",
)

st.divider()

# ── 1. Site Selector & Registration ─────────────────────────────────
sites_list: list[dict] = []
try:
    sites_list = list_sites()
except ApiClientError as err:
    st.error(f"❌ {err}")

col_sel, col_reg = st.columns([3, 1], gap="medium")

selected_site_id: int | None = None

with col_sel:
    if sites_list:
        site_options = {
            f"Site #{s['id']} — {s['name']} ({s['capacity_kw']} kWp)": s["id"]
            for s in sites_list
        }
        selected_label = st.selectbox(
            "Select Installation Site",
            options=list(site_options.keys()),
            index=0,
        )
        selected_site_id = site_options[selected_label]
    else:
        st.warning("⚠️ No installations registered yet. Register a new site below to begin monitoring.")

with col_reg:
    st.write("")
    st.write("")
    show_register_form = st.toggle("➕ Register New Site", value=(len(sites_list) == 0))

if show_register_form:
    with st.form("register_site_form"):
        st.markdown("### 📝 Register New Solar Installation")
        r_col1, r_col2 = st.columns(2)
        with r_col1:
            new_name = st.text_input("System Name", value="My Rooftop PV")
            new_lat = st.number_input("Latitude (°N)", value=22.5626, format="%.4f")
            new_lon = st.number_input("Longitude (°E)", value=88.3630, format="%.4f")
        with r_col2:
            new_cap = st.number_input("Capacity (kWp)", min_value=0.5, max_value=100.0, value=5.0, step=0.5)
            new_tilt = st.number_input("Tilt Angle (°)", min_value=0.0, max_value=60.0, value=20.0, step=1.0)
            new_azimuth = st.number_input("Azimuth (°)", min_value=0.0, max_value=360.0, value=180.0, step=5.0)
            new_date = st.date_input("Installation Date", value=date(2023, 1, 1))

        reg_submit = st.form_submit_button("Save Installation", type="primary")
        if reg_submit:
            try:
                created = register_site(
                    name=new_name.strip(),
                    lat=float(new_lat),
                    lon=float(new_lon),
                    capacity_kw=float(new_cap),
                    tilt=float(new_tilt),
                    azimuth=float(new_azimuth),
                    installed_on=new_date.isoformat(),
                )
                st.success(f"✅ Registered site '{created['name']}' (ID: {created['id']})!")
                st.rerun()
            except ApiClientError as exc:
                st.error(f"❌ Failed to register site: {exc}")

st.divider()

# ── 2. Data Ingestion (Upload CSV / Manual Entry) ────────────────────
if selected_site_id is not None:
    with st.expander("📥 Ingest Generation Readings (CSV or Manual)", expanded=False):
        tab_csv, tab_manual = st.tabs(["📄 Upload CSV File", "✍️ Manual Single-Day Entry"])

        with tab_csv:
            st.markdown(
                "Upload a CSV file containing daily inverter yields. "
                "Required columns: `date` (YYYY-MM-DD) and `actual_kwh` (float)."
            )
            csv_file = st.file_uploader("Choose daily readings CSV", type=["csv"], key="csv_upload")
            if csv_file is not None and st.button("📤 Ingest CSV Data", type="primary"):
                with st.spinner("Uploading readings and triggering watchdog evaluation..."):
                    try:
                        csv_bytes = csv_file.getvalue()
                        resp = upload_readings_csv(
                            site_id=selected_site_id,
                            csv_bytes=csv_bytes,
                            filename=csv_file.name,
                        )
                        st.success(f"✅ Successfully ingested {resp.get('readings_ingested', 0)} readings!")
                        st.rerun()
                    except ApiClientError as exc:
                        st.error(f"❌ Upload failed: {exc}")

        with tab_manual:
            st.markdown("Enter a single day's meter or inverter generation reading:")
            m_col1, m_col2, m_col3 = st.columns([2, 2, 1])
            with m_col1:
                man_date = st.date_input("Reading Date", value=date.today() - timedelta(days=1), key="man_date")
            with m_col2:
                man_kwh = st.number_input("Actual Output (kWh)", min_value=0.0, max_value=500.0, value=15.0, step=0.5, key="man_kwh")
            with m_col3:
                st.write("")
                st.write("")
                man_submit = st.button("Submit", type="primary", key="man_submit")

            if man_submit:
                with st.spinner("Saving reading..."):
                    try:
                        readings_data = [{"date": man_date.isoformat(), "actual_kwh": float(man_kwh)}]
                        resp = submit_readings_json(selected_site_id, readings_data)
                        st.success(f"✅ Saved reading for {man_date} ({man_kwh} kWh)!")
                        st.rerun()
                    except ApiClientError as exc:
                        st.error(f"❌ Submission failed: {exc}")

    # ── 3. Health & Telemetry Display ────────────────────────────────
    with st.spinner("Fetching 30-day weather-adjusted health diagnostics..."):
        try:
            health = get_site_health(selected_site_id, days=30)
        except ApiClientError as exc:
            st.error(f"❌ Unable to load health status: {exc}")
            health = None

    if health:
        st.markdown(f"### ⚡ Health Overview: {health['site_name']} ({health['capacity_kw']} kWp)")

        # Performance Ratio Metric & Status
        pr_val = health.get("current_pr")
        m_col1, m_col2, m_col3 = st.columns(3)

        with m_col1:
            if pr_val is not None:
                pr_pct = pr_val * 100.0
                if pr_val >= 0.80:
                    status_text = "Optimal (≥80%)"
                    d_color = "normal"
                elif pr_val >= 0.60:
                    status_text = "Moderate (60–80%)"
                    d_color = "off"
                else:
                    status_text = "Underperformance (<60%)"
                    d_color = "inverse"

                st.metric(
                    label="Current 7-Day Performance Ratio",
                    value=f"{pr_pct:.1f}%",
                    delta=status_text,
                    delta_color=d_color,
                    help="Ratio of actual inverter energy output to weather-adjusted model prediction over the last 7 days.",
                )
            else:
                st.metric(
                    label="Current 7-Day Performance Ratio",
                    value="Collecting baseline...",
                    help="Need at least 7 days of readings to establish performance ratio.",
                )

        daily_data = health.get("last_30_days", [])
        total_actual = sum(d["actual_kwh"] for d in daily_data)
        total_expected = sum(d["expected_kwh"] for d in daily_data)

        with m_col2:
            st.metric(
                label="30-Day Actual Generation",
                value=f"{total_actual:,.1f} kWh",
                delta=f"{len(daily_data)} days recorded",
                delta_color="off",
            )

        with m_col3:
            st.metric(
                label="30-Day Weather Expected",
                value=f"{total_expected:,.1f} kWh",
                delta=f"Variance: {total_actual - total_expected:+,.1f} kWh",
                delta_color="normal" if total_actual >= total_expected else "inverse",
            )

        # ── 4. Expected vs Actual Line Chart ─────────────────────────
        if daily_data:
            st.markdown("#### 📉 Expected vs Actual Daily Energy (Last 30 Days)")

            # Interactive Altair Chart
            chart = create_telemetry_comparison_chart(daily_data)
            st.altair_chart(chart, use_container_width=True)

            st.caption(
                "🔵 **Cyan points:** Actual metered output (kWh) | "
                "🟠 **Amber dashed/shaded:** Weather-adjusted expectation predicted from satellite solar irradiance and ambient temperature | "
                "🔴 **Red points:** Underperforming days (PR < 80%)."
            )

            # Highlight underperforming days
            underperf_days = [
                d for d in daily_data
                if d.get("performance_ratio") is not None and d["performance_ratio"] < 0.60
            ]
            if underperf_days:
                st.warning(
                    f"⚠️ **{len(underperf_days)} day(s)** experienced severe underperformance (PR < 60%). "
                    "Check the **Alerts** page for automated root-cause diagnoses (dust vs. fault)."
                )

            # Telemetry Table Expander
            with st.expander("📋 View Daily Telemetry Data Table", expanded=False):
                table_df = pd.DataFrame([
                    {
                        "Date": d["date"],
                        "Actual (kWh)": f"{d['actual_kwh']:.2f}",
                        "Expected (kWh)": f"{d['expected_kwh']:.2f}",
                        "PR (%)": f"{d['performance_ratio'] * 100:.1f}%" if d.get("performance_ratio") else "N/A",
                        "Status": (
                            "🔴 Alert (<60%)"
                            if d.get("performance_ratio") is not None and d["performance_ratio"] < 0.60
                            else "🟢 Normal"
                            if d.get("performance_ratio") is not None
                            else "⚪ Low Irradiance"
                        ),
                    }
                    for d in daily_data
                ])
                st.dataframe(table_df, use_container_width=True, hide_index=True)
        else:
            st.info("No daily readings recorded for this site yet. Upload a CSV file or enter readings above.")
