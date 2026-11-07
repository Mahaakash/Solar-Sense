"""
frontend/pages/3_Alerts.py
──────────────────────────
Watchdog Alerts: Intelligent fault & degradation diagnoses with loss quantifications and root-cause explanations.
"""

import re
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from frontend.api_client import (
    ApiClientError,
    check_health,
    get_site_alerts,
    list_sites,
    trigger_site_check,
)
from frontend.theme import apply_custom_theme, render_hero

st.set_page_config(
    page_title="Alerts & Diagnostics — SolarSense",
    page_icon="🚨",
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
    title="🚨 Performance Watchdog Alerts",
    subtitle="Automated root-cause diagnostics screening telemetry against weather expectations to isolate inverter faults and dust from normal overcast days.",
    badge_text="REAL-TIME DIAGNOSTICS ACTIVE",
    badge_type="alert",
)

st.divider()

# ── 1. Site Selector ────────────────────────────────────────────────
sites_list: list[dict] = []
try:
    sites_list = list_sites()
except ApiClientError as err:
    st.error(f"❌ {err}")

if not sites_list:
    st.warning("⚠️ No installations registered yet. Run `python scripts/seed_demo.py` or register a site in 'My System'.")
    st.stop()

site_options = {
    f"Site #{s['id']} — {s['name']} ({s['capacity_kw']} kWp)": s["id"]
    for s in sites_list
}

col_sel, col_btn = st.columns([3, 1], gap="medium")
with col_sel:
    selected_label = st.selectbox(
        "Select Installation Site to Inspect Alerts",
        options=list(site_options.keys()),
        index=0,
    )
    selected_site_id = site_options[selected_label]

with col_btn:
    st.write("")
    st.write("")
    run_check_btn = st.button("🔍 Run Check Now", type="primary", use_container_width=True)

if run_check_btn:
    with st.spinner("Executing weather-adjusted watchdog evaluation..."):
        try:
            new_alerts = trigger_site_check(selected_site_id)
            st.toast(f"Watchdog check complete. Found {len(new_alerts)} alert(s).", icon="✅")
            st.rerun()
        except ApiClientError as exc:
            st.error(f"❌ Failed to run watchdog check: {exc}")

st.divider()

# ── 2. Alert Feed & Diagnostics ─────────────────────────────────────
with st.spinner("Screening diagnostic alerts for selected installation..."):
    try:
        alerts = get_site_alerts(selected_site_id)
    except ApiClientError as exc:
        st.error(f"❌ Failed to fetch alerts: {exc}")
        alerts = []

if not alerts:
    st.html(
        """
        <div style="padding: 24px; background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 14px; text-align: center; margin: 20px 0;">
            <div style="font-size: 2rem; margin-bottom: 8px;">🎉</div>
            <h3 style="color: #34D399; margin: 0 0 6px 0;">All Systems Optimal</h3>
            <p style="color: #94A3B8; margin: 0; font-size: 0.95rem;">No underperformance anomalies or operational faults diagnosed for this installation.</p>
        </div>
        """
    )
else:
    # Compute summary counters
    crit_count = sum(1 for a in alerts if a.get("severity") == "critical")
    warn_count = sum(1 for a in alerts if a.get("severity") == "warning")
    info_count = sum(1 for a in alerts if a.get("severity") == "info")

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.metric("Critical Faults", f"{crit_count}", delta="Requires Inspection" if crit_count > 0 else "None", delta_color="inverse" if crit_count > 0 else "off")
    with sc2:
        st.metric("Warnings", f"{warn_count}", delta="Maintenance Due" if warn_count > 0 else "None", delta_color="inverse" if warn_count > 0 else "off")
    with sc3:
        st.metric("Total Diagnoses", f"{len(alerts)} Items")

    st.write("")
    st.markdown(f"### 📋 Diagnosed Issues ({len(alerts)} Alert{'s' if len(alerts) > 1 else ''})")

    for alert in alerts:
        severity = alert["severity"].lower()
        cause = alert["cause"].lower()
        alert_date = alert["date"]
        message = alert["message"]

        # Parse estimated loss from message if present
        kwh_match = re.search(r"(\d+\.?\d*)\s*kWh", message)
        inr_match = re.search(r"₹\s*([0-9,]+\.?[0-9]*)", message)

        lost_kwh_str = f"{kwh_match.group(1)} kWh" if kwh_match else None
        lost_inr_str = f"₹{inr_match.group(1)}" if inr_match else None

        # Visual accent tokens
        if severity == "critical":
            badge_icon = "🔴"
            badge_title = "CRITICAL FAULT"
            border_glow = "rgba(239, 68, 68, 0.4)"
            accent_bg = "rgba(239, 68, 68, 0.08)"
            tag_color = "#F87171"
        elif severity == "warning":
            badge_icon = "🟡"
            badge_title = "WARNING: UNDERPERFORMANCE"
            border_glow = "rgba(245, 158, 11, 0.35)"
            accent_bg = "rgba(245, 158, 11, 0.08)"
            tag_color = "#FBBF24"
        else:
            badge_icon = "🔵"
            badge_title = "INFO / BASELINE"
            border_glow = "rgba(56, 189, 248, 0.3)"
            accent_bg = "rgba(56, 189, 248, 0.08)"
            tag_color = "#38BDF8"

        with st.container(border=True):
            header_col, date_col = st.columns([3, 1])
            with header_col:
                st.html(
                    f"""
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 1.1rem;">{badge_icon}</span>
                        <strong style="font-size: 1.05rem; color: #F8FAFC; letter-spacing: -0.01em;">{badge_title}</strong>
                        <span style="padding: 2px 8px; background: {accent_bg}; border: 1px solid {border_glow}; border-radius: 6px; font-size: 0.72rem; font-weight: 700; color: {tag_color}; font-family: 'JetBrains Mono', monospace;">
                            {cause.replace('_', ' ').upper()}
                        </span>
                    </div>
                    """
                )
            with date_col:
                st.html(f"<div style='text-align: right; color: #94A3B8; font-family: \"JetBrains Mono\", monospace; font-size: 0.85rem;'>Detected: <strong>{alert_date}</strong></div>")

            # Escape tilde so Markdown doesn't render it as strikethrough (~text~)
            safe_message = message.replace("~", r"\~")
            st.html(f"<div style='font-size: 0.95rem; color: #E2E8F0; margin: 8px 0 12px 0; line-height: 1.5;'>{safe_message}</div>")

            # Impact pill if loss is computed
            if lost_kwh_str or lost_inr_str:
                col_loss1, col_loss2 = st.columns(2)
                with col_loss1:
                    st.html(
                        f"""
                        <div style="padding: 8px 14px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.25); border-radius: 8px; font-size: 0.88rem;">
                            ⚡ <strong>Estimated Generation Lost:</strong> <span style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #F87171;">{lost_kwh_str}</span>
                        </div>
                        """
                    )
                with col_loss2:
                    st.html(
                        f"""
                        <div style="padding: 8px 14px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.25); border-radius: 8px; font-size: 0.88rem;">
                            💸 <strong>Estimated Revenue Lost:</strong> <span style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #F87171;">{lost_inr_str}</span>
                        </div>
                        """
                    )

            # ── "Why did I get this alert?" Expander ───────────────────
            with st.expander("🔎 Why did I get this alert? (Technical & Meteorological Breakdown)", expanded=True):
                if cause == "fault":
                    st.markdown(
                        """
                        **Diagnostic Reasoning:**
                        - **Single-Day Drop:** A sudden generation drop of **≥ 50%** occurred between consecutive clear days.
                        - **Clear-Sky Verification:** The weather model confirmed solar irradiance was high (>2.5 kWh/kWp expected yield). Output fell drastically despite bright sunshine.
                        - **Probable Root Causes:**
                          - String fuse or DC breaker tripped.
                          - Inverter fault / grid sync disconnection.
                          - Blown bypass diode or cable detachment.
                        - **Recommended Action:** Check inverter fault logs and inspect DC junction boxes immediately.
                        """
                    )
                elif cause == "dust":
                    st.markdown(
                        """
                        **Diagnostic Reasoning:**
                        - **Sustained Decline:** The 7-day average Performance Ratio dropped below **60%** (`config.PR_ALERT_LEVEL`).
                        - **Rainfall Check:** Total precipitation over the 14-day window was **≤ 2.0 mm**, ruling out weather-induced cloud drops.
                        - **Downward Slope:** Output steadily decayed over 2+ weeks, characteristic of particulate and dust accumulation on glass.
                        - **Rain Forecast Check:** The upcoming 48-hour forecast is scanned. If rain is due, cleaning is deferred to avoid wasting water.
                        - **Recommended Action:** Rinse panels with demineralized water in the early morning or evening.
                        """
                    )
                elif cause == "ageing":
                    st.markdown(
                        """
                        **Diagnostic Reasoning:**
                        - **Age Threshold:** System has been operating for **≥ 2.0 years**.
                        - **Degradation Exceeded:** Actual output has fallen by more than **5% beyond** the standard 0.5%/year warranty degradation rate.
                        - **Recommended Action:** Contact the module manufacturer to claim 25-year linear performance warranty.
                        """
                    )
                elif cause == "insufficient_data":
                    st.markdown(
                        """
                        **Diagnostic Reasoning:**
                        - Fewer than 7 days of daily readings have been ingested.
                        - The watchdog engine requires a minimum 7-day rolling window to compute reliable baseline Performance Ratios.
                        """
                    )
                else:
                    st.markdown(
                        f"**Diagnostic Reasoning:** System underperformed expected output by more than normal tolerance margins for cause `{cause}`."
                    )

            st.write("")
