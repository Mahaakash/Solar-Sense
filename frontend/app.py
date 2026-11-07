"""
frontend/app.py
───────────────
Main landing dashboard for SolarSense.
Presents the dual operating modes (Solar Advisor & Watchdog) and monitors backend status.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from frontend.api_client import BASE_URL, check_health, list_sites
from frontend.theme import apply_custom_theme, render_hero

# Configure page metadata & responsive layout
st.set_page_config(
    page_title="SolarSense — Rooftop Solar Advisor & Watchdog",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Apply global dark glassmorphism theme and custom fonts
apply_custom_theme()

is_online = check_health()

# ── Sidebar ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ☀️ SolarSense")
    st.caption("Intelligent Rooftop Solar for India")
    st.divider()

    # Backend connectivity check with live pulse
    if is_online:
        st.html(
            f"""
            <div style="padding: 12px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 10px; font-size: 0.85rem;">
                <span class="pulse-online"></span><strong style="color: #34D399;">Backend Online</strong><br>
                <code style="font-size: 0.75rem; color: #94A3B8;">{BASE_URL}</code>
            </div>
            """
        )
    else:
        st.html(
            f"""
            <div style="padding: 12px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 10px; font-size: 0.85rem;">
                <span class="pulse-alert"></span><strong style="color: #F87171;">Backend Offline</strong><br>
                <code style="font-size: 0.75rem; color: #94A3B8;">{BASE_URL}</code>
            </div>
            """
        )

    st.divider()
    st.markdown("### 🧭 Quick Navigation")
    st.page_link("pages/1_Advisor.py", label="Solar Advisor (Pre-Install)", icon="💡")
    st.page_link("pages/2_My_System.py", label="My System (Telemetry)", icon="📊")
    st.page_link("pages/3_Alerts.py", label="Alerts & Diagnostics", icon="🚨")

    st.divider()
    st.caption("Market: **India** | Currency: **INR (₹)**")
    st.caption("SolarSense v0.1.0 • Powered by XGBoost & Open-Meteo")

# ── Main Hero Header ────────────────────────────────────────────────
render_hero(
    title="☀️ SolarSense Intelligence Platform",
    subtitle="Bridging pre-installation financial planning with post-installation fault detection through a unified, weather-adjusted solar forecasting engine.",
    badge_text="PAN-INDIA ENGINE READY" if is_online else "BACKEND SERVICE OFFLINE",
    badge_type="online" if is_online else "alert",
)

st.divider()

# ── Two Operating Modes Overview ────────────────────────────────────
col_adv, col_wd = st.columns(2, gap="large")

with col_adv.container(border=True):
    st.markdown("### 💡 Mode 1: Solar Advisor")
    st.caption("**Pre-Installation Planning & 25-Year Lifecycle Economics**")
    st.markdown(
        """
        - **Target Sizing**: Optimally sizes arrays to offset **~85%** of household or commercial electricity bills.
        - **Roof-Aware Capping**: Restricts capacity automatically based on usable shadow-free rooftop square meters.
        - **Monsoon & Weather-Adjusted**: Evaluates 1 full year of satellite irradiance and Evans cell temperatures.
        - **25-Year Lifecycle Modeling**: Upfront capex, annual ₹ savings, payback horizon, and 0.5%/yr degradation.
        """
    )
    st.write("")
    st.page_link(
        "pages/1_Advisor.py",
        label="⚡ Launch Solar Advisor",
        use_container_width=True,
    )

with col_wd.container(border=True):
    st.markdown("### 🚨 Mode 2: Performance Watchdog")
    st.caption("**Post-Installation Telemetry Screening & Fault Diagnosis**")
    st.markdown(
        """
        - **Expected vs Actual Monitoring**: Compares actual smart meter kWh against weather expectations.
        - **Automated Root-Cause Diagnosis**:
          - 🔴 **Inverter String Fault**: Identifies sudden generation collapses on clear days.
          - 🟡 **Dust & Particulate Soiling**: Flags gradual output loss during rainless dry spells.
          - 🔵 **System Ageing**: Spots degradation exceeding manufacturer linear warranties.
        - **Loss Quantification**: Translates underperformance into lost kWh and lost revenue in ₹ INR.
        """
    )
    c1, c2 = st.columns(2)
    with c1:
        st.page_link(
            "pages/2_My_System.py",
            label="📊 Open My System",
            use_container_width=True,
        )
    with c2:
        st.page_link(
            "pages/3_Alerts.py",
            label="🚨 View Alerts Feed",
            use_container_width=True,
        )

st.divider()

# ── Active Sites Overview ───────────────────────────────────────────
st.markdown("### 📡 Registered Indian Solar Installations")
if is_online:
    try:
        sites = list_sites()
        if sites:
            total_cap = sum(float(s.get("capacity_kw", 0)) for s in sites)
            k1, k2, k3 = st.columns(3)
            with k1:
                st.metric("Total Active Sites", f"{len(sites)} Installations")
            with k2:
                st.metric("Monitored Capacity", f"{total_cap:,.1f} kWp")
            with k3:
                st.metric("Coverage", "8 Indian Metros")

            st.write("")
            site_cols = st.columns(min(len(sites), 4))
            for i, site in enumerate(sites[:4]):
                with site_cols[i % 4]:
                    st.metric(
                        label=f"Site #{site['id']} — {site['name'][:18]}",
                        value=f"{site['capacity_kw']} kWp",
                        delta=f"Installed {site['installed_on']}",
                        delta_color="off",
                    )
        else:
            st.info(
                "No sites registered yet. Run `python scripts/seed_demo.py` "
                "or register a new site in the **My System** tab."
            )
    except Exception as exc:
        st.warning(f"Could not load site summary: {exc}")
else:
    st.warning("⚠️ Connect to the backend to view registered installations and live telemetry.")
