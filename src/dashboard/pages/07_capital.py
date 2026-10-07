"""Screen 07 - Capital Allocation Map.

Treemap of all constituents grouped by capital-allocation pattern,
pattern summary tiles, and drill-down constituent list.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard.utils.db import get_full_ratios_with_pl
from src.dashboard.utils.theme import (
    CHART_PALETTE,
    COLORS,
    app_stamp,
    fy_short,
    number_col,
    page_header,
    plotly_chart,
    section_label,
    text_col,
)

# Institutional palette for the 8 patterns (muted, high-contrast).
PATTERN_COLORS = {
    "Reinvestor": "#2EB886",  # forest
    "Shareholder Returns": "#4C8BF5",  # slate blue
    "Cash Accumulator": "#B07AE0",  # muted violet
    "Liquidating Assets": "#E0A43C",  # amber
    "Distress Signal": "#D94F5C",  # brick red
    "Growth Funded by Debt": "#D17B55",  # terracotta
    "Pre-Revenue": "#5E6878",  # slate
    "Mixed": "#8A94A6",  # muted grey
}


def render() -> None:
    """Render the Capital Allocation page."""
    page_header(
        "Capital Allocation Map",
        "Constituents grouped by CFO/CFI/CFF cash-flow pattern, sized by market cap.",
    )

    panel = get_full_ratios_with_pl()
    latest_year = panel["year"].max()
    df = panel[panel["year"] == latest_year].copy()
    df["pattern"] = df["capital_allocation_pattern"].fillna("Mixed")

    # Build treemap hierarchy: root -> pattern -> company
    treemap_df = df[
        [
            "pattern",
            "company_id",
            "company_name",
            "fcf_cr",
            "cfo_pat_ratio",
            "composite_quality_score",
            "market_cap_crore",
        ]
    ].copy()
    treemap_df["parent"] = treemap_df["pattern"]

    pattern_summary = df.groupby("pattern").agg(count=("company_id", "count")).reset_index()
    pattern_summary["parent"] = "Nifty 100"
    pattern_summary["company_id"] = pattern_summary["pattern"]
    pattern_summary["company_name"] = (
        pattern_summary["pattern"] + " (" + pattern_summary["count"].astype(str) + ")"
    )
    pattern_summary["fcf_cr"] = 0
    pattern_summary["cfo_pat_ratio"] = 0
    pattern_summary["composite_quality_score"] = 0
    pattern_summary["market_cap_crore"] = pattern_summary["count"] * 10_000

    root = pd.DataFrame(
        [
            {
                "pattern": "Nifty 100",
                "company_id": "Nifty 100",
                "company_name": f"Nifty 100 ({len(df)} firms)",
                "parent": "",
                "fcf_cr": 0,
                "cfo_pat_ratio": 0,
                "composite_quality_score": 0,
                "market_cap_crore": len(df) * 20_000,
            }
        ]
    )
    treemap_df = pd.concat(
        [root, pattern_summary.assign(pattern="Nifty 100"), treemap_df],
        ignore_index=True,
        sort=False,
    )

    color_map = {p: PATTERN_COLORS.get(p, COLORS["text_mute"]) for p in df["pattern"].unique()}
    color_map["Nifty 100"] = CHART_PALETTE[0]

    fig = px.treemap(
        treemap_df,
        path=["parent", "pattern", "company_id"],
        values="market_cap_crore",
        color="pattern",
        color_discrete_map=color_map,
        hover_name="company_name",
        hover_data={
            "company_name": True,
            "fcf_cr": ":,.0f",
            "cfo_pat_ratio": ":.2f",
            "composite_quality_score": ":.1f",
            "market_cap_crore": ":,.0f",
        },
        title=f"Capital Allocation - {fy_short(latest_year)}",
    )
    fig.update_traces(
        textfont=dict(family="Inter, sans-serif", size=11, color=COLORS["text"]),
        marker=dict(cornerradius=2),
    )
    fig.update_layout(margin=dict(t=40, l=0, r=0, b=10), height=580)
    plotly_chart(fig, height=580)

    # Pattern summary tiles
    section_label("Pattern Breakdown")
    counts = (
        df.groupby("pattern").size().reset_index(name="count").sort_values("count", ascending=False)
    )
    cols = st.columns(min(4, len(counts)))
    for i, row in counts.reset_index(drop=True).iterrows():
        with cols[i % 4]:
            color = PATTERN_COLORS.get(row["pattern"], COLORS["text_mute"])
            st.markdown(
                f"<div style='padding:10px 12px;border-left:3px solid {color};"
                f"background:{COLORS['card']};border-radius:0 3px 3px 0;margin-bottom:4px'>"
                f"<div style='font-size:0.7rem;font-weight:700;letter-spacing:0.1em;"
                f"text-transform:uppercase;color:{COLORS['text_mute']}'>"
                f"{row['pattern']}</div>"
                f"<div style='font-size:1.3rem;font-weight:700;margin-top:0.15rem'>"
                f"{int(row['count'])}</div></div>",
                unsafe_allow_html=True,
            )

    # Drill-down
    section_label("Pattern Drill-Down")
    pattern_choice = st.selectbox(
        "Select Pattern",
        ["(select)", *sorted(df["pattern"].unique().tolist())],
    )
    if pattern_choice != "(select)":
        members = df[df["pattern"] == pattern_choice][
            [
                "company_id",
                "company_name",
                "broad_sector",
                "fcf_cr",
                "cfo_pat_ratio",
                "composite_quality_score",
            ]
        ].sort_values("composite_quality_score", ascending=False, na_position="last")
        members.columns = ["Ticker", "Company", "Sector", "FCF (Cr)", "CFO/PAT", "Composite"]
        st.dataframe(
            members,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Ticker": text_col("Ticker"),
                "Company": text_col("Company"),
                "Sector": text_col("Sector"),
                "FCF (Cr)": number_col("FCF (Cr)", digits=0),
                "CFO/PAT": number_col("CFO/PAT", digits=2),
                "Composite": number_col("Composite", digits=1),
            },
        )

    app_stamp()
