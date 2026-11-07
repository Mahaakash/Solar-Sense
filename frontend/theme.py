"""
frontend/theme.py
─────────────────
Centralized UI theming, typography, glassmorphism styles, and interactive Altair charts for SolarSense.
"""

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st


def apply_custom_theme() -> None:
    """Inject premium Google Fonts and glassmorphic styling into the Streamlit session."""
    st.html(
        """
        <style>
        /* ── Import Premium Google Fonts ────────────────────────────── */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap');

        /* ── Global Typography & Background ─────────────────────────── */
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: #F9FAFB;
        }

        .stApp {
            background-color: #0B0F19;
            background-image:
                radial-gradient(circle at 50% 0%, rgba(245, 158, 11, 0.06) 0%, transparent 65%),
                radial-gradient(circle at 100% 100%, rgba(16, 185, 129, 0.04) 0%, transparent 50%);
            background-attachment: fixed;
        }

        /* ── Headings ───────────────────────────────────────────────── */
        h1, h2, h3, h4, h5, h6 {
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            letter-spacing: -0.025em;
            font-weight: 700;
        }

        /* ── Glassmorphic Cards & Containers ────────────────────────── */
        div[data-testid="stVerticalBlockBorderWrapper"] > div {
            background: rgba(17, 24, 39, 0.65) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 14px !important;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.35);
            transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] > div:hover {
            border-color: rgba(245, 158, 11, 0.25) !important;
            box-shadow: 0 8px 28px -4px rgba(245, 158, 11, 0.12);
        }

        /* ── Native Metric Cards ────────────────────────────────────── */
        div[data-testid="stMetric"] {
            background: rgba(17, 24, 39, 0.75) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 14px !important;
            padding: 16px 20px !important;
            backdrop-filter: blur(12px);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
            transition: all 0.2s ease;
        }

        div[data-testid="stMetric"]:hover {
            border-color: rgba(245, 158, 11, 0.3) !important;
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
        }

        div[data-testid="stMetricLabel"] {
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-size: 0.82rem !important;
            font-weight: 600 !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #94A3B8 !important;
        }

        div[data-testid="stMetricValue"] {
            font-family: 'JetBrains Mono', monospace !important;
            font-weight: 700 !important;
            letter-spacing: -0.03em !important;
            color: #F8FAFC !important;
            font-size: 1.85rem !important;
        }

        div[data-testid="stMetricDelta"] {
            font-family: 'JetBrains Mono', monospace !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
        }

        /* ── Buttons ────────────────────────────────────────────────── */
        button[kind="primary"] {
            background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%) !important;
            color: #0F172A !important;
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-weight: 700 !important;
            font-size: 0.95rem !important;
            border: none !important;
            border-radius: 10px !important;
            padding: 0.6rem 1.4rem !important;
            box-shadow: 0 4px 14px rgba(245, 158, 11, 0.35) !important;
            transition: all 0.2s ease !important;
        }

        button[kind="primary"]:hover {
            transform: translateY(-1px) !important;
            box-shadow: 0 6px 20px rgba(245, 158, 11, 0.5) !important;
            filter: brightness(1.08) !important;
        }

        button[kind="secondary"] {
            background: rgba(30, 41, 59, 0.6) !important;
            color: #E2E8F0 !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            transition: all 0.2s ease !important;
        }

        button[kind="secondary"]:hover {
            border-color: rgba(245, 158, 11, 0.4) !important;
            background: rgba(45, 55, 72, 0.8) !important;
            color: #F8FAFC !important;
        }

        /* ── Input Fields ───────────────────────────────────────────── */
        input, select, textarea {
            background-color: rgba(15, 23, 42, 0.8) !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            color: #F8FAFC !important;
            border-radius: 8px !important;
            font-family: 'Inter', sans-serif !important;
        }

        input:focus, select:focus, textarea:focus {
            border-color: #F59E0B !important;
            box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.2) !important;
        }

        /* ── Sidebar Styling ────────────────────────────────────────── */
        section[data-testid="stSidebar"] {
            background-color: #0E131F !important;
            border-right: 1px solid rgba(255, 255, 255, 0.07) !important;
        }

        /* ── Expanders ──────────────────────────────────────────────── */
        div[data-testid="stExpander"] {
            background: rgba(15, 23, 42, 0.5) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 12px !important;
        }

        /* ── Animated Pulsing Badge ─────────────────────────────────── */
        @keyframes pulseGlow {
            0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.6); }
            70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
            100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }

        .pulse-online {
            display: inline-block;
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background-color: #10B981;
            animation: pulseGlow 2s infinite;
            margin-right: 6px;
            vertical-align: middle;
        }

        .pulse-alert {
            display: inline-block;
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background-color: #EF4444;
            animation: pulseGlow 1.5s infinite;
            margin-right: 6px;
            vertical-align: middle;
        }

        /* ── Metro Quick-Pills Bar ─────────────────────────────────── */
        .metro-pill-container {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding-bottom: 6px;
        }

        /* ── Scrollbars ─────────────────────────────────────────────── */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(11, 15, 25, 0.6);
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.18);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(245, 158, 11, 0.5);
        }
        </style>
        """
    )


def render_hero(title: str, subtitle: str, badge_text: str | None = None, badge_type: str = "online") -> None:
    """Render a modern hero header with gradient title and optional live badge."""
    badge_html = ""
    if badge_text:
        pulse_class = "pulse-online" if badge_type == "online" else "pulse-alert"
        badge_bg = "rgba(16, 185, 129, 0.12)" if badge_type == "online" else "rgba(239, 68, 68, 0.12)"
        badge_color = "#34D399" if badge_type == "online" else "#F87171"
        badge_border = "rgba(16, 185, 129, 0.25)" if badge_type == "online" else "rgba(239, 68, 68, 0.25)"

        badge_html = (
            f'<div style="display: inline-flex; align-items: center; padding: 4px 12px; '
            f'background: {badge_bg}; border: 1px solid {badge_border}; border-radius: 9999px; '
            f'font-size: 0.8rem; font-weight: 600; color: {badge_color}; margin-bottom: 12px; '
            f'font-family: \'JetBrains Mono\', monospace;">'
            f'<span class="{pulse_class}"></span>{badge_text}'
            f'</div><br>'
        )

    hero_html = (
        f'<div style="padding: 6px 0 16px 0;">'
        f'{badge_html}'
        f'<h1 style="font-size: 2.35rem; font-weight: 800; margin: 0 0 8px 0; '
        f'background: linear-gradient(90deg, #F59E0B 0%, #FBBF24 50%, #10B981 100%); '
        f'-webkit-background-clip: text; -webkit-text-fill-color: transparent;">'
        f'{title}</h1>'
        f'<p style="font-size: 1.05rem; color: #94A3B8; margin: 0; max-width: 850px; line-height: 1.55;">'
        f'{subtitle}</p>'
        f'</div>'
    )

    st.html(hero_html)


def create_monthly_generation_chart(monthly_data: list[dict[str, Any]]) -> alt.Chart:
    """Create an interactive Altair bar chart with hover tooltips for 12-month generation."""
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    gen_map = {item.get("month_name"): item.get("generation_kwh", 0.0) for item in monthly_data}

    df = pd.DataFrame(
        [
            {
                "Month": m,
                "Month_Index": i + 1,
                "Generation": round(float(gen_map.get(m, 0.0)), 1),
                "Estimated_Value_INR": round(float(gen_map.get(m, 0.0)) * 8.0),
            }
            for i, m in enumerate(month_names)
        ]
    )

    base = alt.Chart(df).encode(
        x=alt.X("Month:N", sort=month_names, axis=alt.Axis(labelAngle=0, labelColor="#94A3B8", title=None, grid=False)),
        y=alt.Y("Generation:Q", axis=alt.Axis(labelColor="#94A3B8", title="Solar Generation (kWh)", gridColor="rgba(255,255,255,0.06)", tickColor="rgba(255,255,255,0.1)")),
    )

    bars = base.mark_bar(
        cornerRadiusTopLeft=6,
        cornerRadiusTopRight=6,
        color="#F59E0B",
    ).encode(
        tooltip=[
            alt.Tooltip("Month:N", title="Month"),
            alt.Tooltip("Generation:Q", title="Yield (kWh)", format=",.1f"),
            alt.Tooltip("Estimated_Value_INR:Q", title="Grid Value (₹)", format=",.0f"),
        ]
    )

    # Subtle text labels above bars
    text = base.mark_text(
        align="center",
        baseline="bottom",
        dy=-4,
        color="#FCD34D",
        fontSize=11,
        font="JetBrains Mono",
    ).encode(text=alt.Text("Generation:Q", format=".0f"))

    chart = (bars + text).properties(
        height=320,
    ).configure_view(
        strokeWidth=0,
    ).interactive(bind_y=False)

    return chart


def create_cumulative_savings_chart(savings_data: list[dict[str, Any]], payback_years: float | None = None) -> alt.Chart:
    """Create an interactive Altair line and gradient area chart for 25-year cumulative cash flows."""
    df = pd.DataFrame(
        [
            {
                "Year": int(item.get("year", 0)),
                "Savings_INR": round(float(item.get("cumulative_savings_inr", 0.0))),
                "Status": "Profitable (Net Return)" if float(item.get("cumulative_savings_inr", 0.0)) >= 0 else "Capital Payback Phase",
            }
            for item in savings_data
        ]
    )

    base = alt.Chart(df).encode(
        x=alt.X("Year:Q", axis=alt.Axis(labelColor="#94A3B8", title="Operating Year", gridColor="rgba(255,255,255,0.06)", tickMinStep=2)),
        y=alt.Y("Savings_INR:Q", axis=alt.Axis(labelColor="#94A3B8", title="Cumulative Net Return (₹ INR)", format=",.0f", gridColor="rgba(255,255,255,0.06)")),
    )

    area = base.mark_area(
        opacity=0.25,
        color="#10B981",
    )

    line = base.mark_line(
        color="#10B981",
        strokeWidth=3,
        point=alt.OverlayMarkDef(color="#34D399", size=45, filled=True),
    ).encode(
        tooltip=[
            alt.Tooltip("Year:Q", title="Year"),
            alt.Tooltip("Savings_INR:Q", title="Net Cumulative Savings", format="₹,.0f"),
            alt.Tooltip("Status:N", title="Milestone"),
        ]
    )

    # Zero break-even reference rule
    zero_rule = alt.Chart(pd.DataFrame([{"y": 0}])).mark_rule(
        strokeDash=[4, 4],
        color="rgba(255, 255, 255, 0.4)",
        strokeWidth=1.5,
    ).encode(y="y:Q")

    chart = (area + line + zero_rule).properties(
        height=320,
    ).configure_view(
        strokeWidth=0,
    ).interactive()

    return chart


def create_telemetry_comparison_chart(history_items: list[dict[str, Any]]) -> alt.Chart:
    """Create an interactive dual-series comparison chart (Actual vs Weather-Adjusted Expected kWh)."""
    rows = []
    for h in history_items:
        date_str = str(h.get("date"))
        actual = float(h.get("actual_kwh", 0.0))
        expected = float(h.get("expected_kwh", 0.0))
        ratio = (actual / expected) if expected > 0.05 else 1.0
        underperforming = ratio < 0.80

        rows.append(
            {
                "Date": date_str,
                "Actual_kWh": round(actual, 2),
                "Expected_kWh": round(expected, 2),
                "PR_Pct": round(ratio * 100, 1),
                "Condition": "Underperforming (<80% PR)" if underperforming else "Normal Operation",
                "Alert_Color": "#EF4444" if underperforming else "#38BDF8",
            }
        )

    df = pd.DataFrame(rows)

    base = alt.Chart(df).encode(
        x=alt.X("Date:N", axis=alt.Axis(labelColor="#94A3B8", title=None, labelAngle=-45, grid=False)),
    )

    # Expected output area & line (warm amber)
    expected_area = base.mark_area(
        opacity=0.15,
        color="#F59E0B",
    ).encode(
        y=alt.Y("Expected_kWh:Q", axis=alt.Axis(labelColor="#94A3B8", title="Daily Energy Yield (kWh)", gridColor="rgba(255,255,255,0.06)")),
    )

    expected_line = base.mark_line(
        color="#F59E0B",
        strokeWidth=2,
        strokeDash=[4, 2],
    ).encode(
        y="Expected_kWh:Q",
    )

    # Actual output line (electric cyan)
    actual_line = base.mark_line(
        color="#38BDF8",
        strokeWidth=2.5,
    ).encode(
        y="Actual_kWh:Q",
    )

    # Points on actual line, dynamically colored by health
    points = base.mark_circle(size=60).encode(
        y="Actual_kWh:Q",
        color=alt.Color(
            "Condition:N",
            scale=alt.Scale(domain=["Normal Operation", "Underperforming (<80% PR)"], range=["#38BDF8", "#EF4444"]),
            legend=alt.Legend(title="System Status", orient="top", labelColor="#E2E8F0", titleColor="#94A3B8"),
        ),
        tooltip=[
            alt.Tooltip("Date:N", title="Date"),
            alt.Tooltip("Actual_kWh:Q", title="Actual Yield", format=",.2f kWh"),
            alt.Tooltip("Expected_kWh:Q", title="Expected Yield", format=",.2f kWh"),
            alt.Tooltip("PR_Pct:Q", title="Performance Ratio", format=",.1f%%"),
            alt.Tooltip("Condition:N", title="Health Status"),
        ],
    )

    chart = (expected_area + expected_line + actual_line + points).properties(
        height=340,
    ).configure_view(
        strokeWidth=0,
    ).interactive(bind_y=False)

    return chart
