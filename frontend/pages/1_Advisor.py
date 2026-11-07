"""
frontend/pages/1_Advisor.py
───────────────────────────
Solar Advisor: Pre-installation rooftop solar sizing & 25-year financial lifecycle analysis.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from backend import config
from frontend.api_client import ApiClientError, check_health, get_advisor_recommendation
from frontend.theme import (
    apply_custom_theme,
    create_cumulative_savings_chart,
    create_monthly_generation_chart,
    render_hero,
)

st.set_page_config(
    page_title="Solar Advisor — SolarSense",
    page_icon="💡",
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
    title="💡 Solar Advisor",
    subtitle="Estimate optimal solar array capacity, monthly seasonal yields, and 25-year financial returns tailored to Indian tariffs and solar irradiance.",
    badge_text="WEATHER-ADJUSTED PREDICTIVE SIZING",
    badge_type="online",
)

st.divider()

# ── Input Form ──────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("#### 📍 Location & Electricity Consumption")

    st.markdown("<span style='font-size: 0.85rem; color: #94A3B8; font-weight: 600;'>QUICK SELECT METROPOLITAN CITY:</span>", unsafe_allow_html=True)
    metro_keys = list(config.METROPOLITAN_CITIES.keys())
    m_cols = st.columns(len(metro_keys))
    for col, m_key in zip(m_cols, metro_keys, strict=False):
        current_sel = st.session_state.get("advisor_place_input", "Kolkata")
        btn_type = "primary" if current_sel == m_key else "secondary"
        if col.button(m_key, key=f"metro_{m_key}", type=btn_type, use_container_width=True):
            st.session_state["advisor_place_input"] = m_key
            st.session_state["advisor_tilt_input"] = config.METROPOLITAN_CITIES[m_key]["optimal_tilt"]
            st.rerun()

    current_place = st.session_state.get("advisor_place_input", "Kolkata")
    current_tilt = float(st.session_state.get("advisor_tilt_input", 20.0))

    col1, col2, col3 = st.columns([2, 1.5, 1.5])

    with col1:
        place_input = st.text_input(
            "City or Town in India",
            value=current_place,
            help="Enter any city, town, or neighborhood in India (e.g. Kolkata, Bengaluru, Pune).",
        )

    with col2:
        bill_input = st.number_input(
            "Monthly Electricity Bill (₹ INR)",
            min_value=100.0,
            max_value=1_000_000.0,
            value=3000.0,
            step=250.0,
            format="%.0f",
            help="Your average monthly power bill in Indian Rupees.",
        )

    with col3:
        roof_area_input = st.number_input(
            "Roof Area (m²) — Optional",
            min_value=0.0,
            max_value=10_000.0,
            value=0.0,
            step=10.0,
            format="%.0f",
            help="Usable shadow-free rooftop area in square meters. Leave 0 for unconstrained.",
        )

    with st.expander("⚙️ Advanced System Orientation (Tilt & Azimuth)"):
        col_adv1, col_adv2 = st.columns(2)
        with col_adv1:
            tilt_val = st.slider(
                "Panel Tilt Angle (°)",
                min_value=0.0,
                max_value=60.0,
                value=current_tilt,
                step=1.0,
                help="Optimal tilt in India is typically roughly equal to local latitude (~15°-25°).",
            )
        with col_adv2:
            azimuth_val = st.slider(
                "Azimuth Angle (°)",
                min_value=0.0,
                max_value=360.0,
                value=180.0,
                step=5.0,
                help="180° = True South (optimal for Northern Hemisphere solar yields).",
            )

    st.write("")
    submit_button = st.button("⚡ Calculate Solar Sizing & Returns", type="primary", use_container_width=True)

# ── Computation & Results ───────────────────────────────────────────
if submit_button or "advisor_results" not in st.session_state:
    if place_input.strip():
        with st.spinner("Analyzing historical weather & calculating 25-year financial returns..."):
            try:
                roof_val = roof_area_input if roof_area_input > 0 else None
                result = get_advisor_recommendation(
                    place=place_input.strip(),
                    monthly_bill_inr=float(bill_input),
                    roof_area_m2=roof_val,
                    tilt=float(tilt_val),
                    azimuth=float(azimuth_val),
                )
                st.session_state["advisor_results"] = result
                st.session_state["advisor_place"] = place_input.strip()
            except ApiClientError as exc:
                st.error(f"❌ {exc}")
            except Exception as exc:
                st.error(f"❌ Unexpected calculation error: {exc}")
    else:
        st.warning("Please enter a valid place name.")

# ── Display Results ─────────────────────────────────────────────────
if "advisor_results" in st.session_state:
    res = st.session_state["advisor_results"]
    resolved_name = res.get("location", st.session_state.get("advisor_place", "Kolkata"))
    lat_val = res.get("latitude")
    lon_val = res.get("longitude")
    system_size = float(res.get("system_size_kw", 0.0))
    yearly_gen = float(res.get("yearly_generation_kwh", 0.0))
    specific_yield = (yearly_gen / system_size) if system_size > 0 else 0.0

    st.html(
        f"""
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 20px; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 12px; margin: 18px 0;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 1.4rem;">📍</span>
                <div>
                    <strong style="color: #F8FAFC; font-size: 1.05rem;">Solar Plan for {resolved_name}</strong>
                    <div style="font-size: 0.8rem; color: #94A3B8; font-family: 'JetBrains Mono', monospace;">Coordinates: {lat_val:.4f}° N, {lon_val:.4f}° E</div>
                </div>
            </div>
            <div style="text-align: right;">
                <span style="font-size: 0.75rem; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.05em;">Target Offset</span>
                <div style="color: #34D399; font-weight: 700; font-family: 'JetBrains Mono', monospace;">~85% Net Energy</div>
            </div>
        </div>
        """
    )

    # ── Metric Cards ────────────────────────────────────────────────
    st.markdown("### 📊 Key Recommendations & Payback")
    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.metric(
            label="Recommended Capacity",
            value=f"{system_size:.1f} kWp",
            delta="Roof Capped" if res.get("roof_area_capped") else "85% Target Offset",
            delta_color="off",
            help="Sized in 0.5 kW increments to offset ~85% of grid electricity consumption.",
        )

    with m2:
        st.metric(
            label="Annual Generation",
            value=f"{yearly_gen:,.0f} kWh",
            delta=f"{specific_yield:,.0f} kWh/kWp/yr",
            delta_color="normal",
            help="Total estimated clean energy generated over 1 full weather-adjusted year.",
        )

    with m3:
        st.metric(
            label="Annual Bill Savings",
            value=f"₹{res['yearly_savings_inr']:,.0f}",
            delta=f"Year 1 @ ₹{res['assumptions']['tariff_inr_per_kwh']}/kWh",
            delta_color="normal",
            help="First-year reduction in your grid electricity expenditure.",
        )

    with m4:
        st.metric(
            label="Payback Horizon",
            value=f"{res['payback_period_years']:.1f} Years",
            delta=f"Net 25-yr: ₹{res['net_25yr_savings_inr']:,.0f}",
            delta_color="normal",
            help="Time required for accumulated savings to completely recover system capital cost.",
        )

    # High-impact Financial Banner
    st.html(
        f"""
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; padding: 16px 20px; background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; margin: 18px 0; text-align: center;">
            <div>
                <div style="font-size: 0.78rem; color: #94A3B8; text-transform: uppercase;">Estimated System Cost</div>
                <div style="font-size: 1.25rem; font-weight: 700; color: #F59E0B; font-family: 'JetBrains Mono', monospace;">₹{res['system_cost_inr']:,.0f}</div>
            </div>
            <div>
                <div style="font-size: 0.78rem; color: #94A3B8; text-transform: uppercase;">25-Year Cumulative Net Savings</div>
                <div style="font-size: 1.25rem; font-weight: 700; color: #10B981; font-family: 'JetBrains Mono', monospace;">₹{res['net_25yr_savings_inr']:,.0f}</div>
            </div>
            <div>
                <div style="font-size: 0.78rem; color: #94A3B8; text-transform: uppercase;">Estimated Monthly Consumption</div>
                <div style="font-size: 1.25rem; font-weight: 700; color: #38BDF8; font-family: 'JetBrains Mono', monospace;">{res.get('estimated_monthly_consumption_kwh', 0):,.0f} kWh</div>
            </div>
        </div>
        """
    )

    st.divider()

    # ── Interactive Charts ──────────────────────────────────────────
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.markdown("#### 📅 Monthly Solar Generation (kWh)")
        monthly_items = res.get("monthly_generation", [])
        if monthly_items:
            chart = create_monthly_generation_chart(monthly_items)
            st.altair_chart(chart, use_container_width=True)
            st.caption("Seasonal variation in solar yield driven by monsoon cloud cover and solar angle.")

    with col_chart2:
        st.markdown("#### 📈 25-Year Cumulative Net Savings (₹ INR)")
        savings_items = res.get("cumulative_savings_25yr", [])
        if savings_items:
            chart = create_cumulative_savings_chart(savings_items, res.get("payback_period_years"))
            st.altair_chart(chart, use_container_width=True)
            st.caption(
                "Net return after deducting system capital cost, incorporating annual module "
                "degradation (0.5%/yr) and grid tariff escalation (3%/yr)."
            )

    st.divider()

    # ── Expandable Assumptions Section ──────────────────────────────
    with st.expander("🔎 View Assumptions & Financial Model Parameters", expanded=False):
        assump = res.get("assumptions", {})
        col_a1, col_a2 = st.columns(2)

        with col_a1:
            st.markdown("**Economic Assumptions**")
            st.write(f"- **Grid Tariff:** ₹{assump.get('tariff_inr_per_kwh', 8.0):.2f} per kWh")
            st.write(f"- **System Capital Cost:** ₹{assump.get('system_cost_per_kw_inr', 50000):,.0f} per kWp installed")
            st.write(f"- **Annual Tariff Escalation:** {assump.get('tariff_annual_escalation_pct', 0.03) * 100:.1f}% per year")
            st.write(f"- **Target Consumption Offset:** {assump.get('target_offset_pct', 0.85) * 100:.0f}%")

        with col_a2:
            st.markdown("**Physical & Technical Assumptions**")
            st.write(f"- **Roof Area Required:** {assump.get('roof_area_per_kw_m2', 10.0):.1f} m² per kWp")
            st.write(f"- **Module Output Degradation:** {assump.get('annual_degradation_rate', 0.005) * 100:.2f}% per year")
            st.write(f"- **Sizing Step Size:** {assump.get('sizing_step_kw', 0.5):.1f} kWp increments")
            st.write(f"- **System Lifecycle:** {assump.get('lifecycle_years', 25)} Years")
