"""Screen 07 - Capital Allocation Map (Day 25).

Plotly treemap of all 92 companies grouped by capital-allocation
pattern. Clicking a pattern shows the list of companies underneath.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard.utils.db import get_full_ratios_with_pl

PATTERN_COLORS = {
    "Reinvestor": "#2CA02C",
    "Shareholder Returns": "#1F77B4",
    "Cash Accumulator": "#9467BD",
    "Liquidating Assets": "#FF7F0E",
    "Distress Signal": "#D62728",
    "Growth Funded by Debt": "#E377C2",
    "Pre-Revenue": "#7F7F7F",
    "Mixed": "#BCBD22",
}


def render() -> None:
    st.title("Capital Allocation Map")
    st.caption(
        "Companies grouped by CFO/CFI/CFF cash-flow pattern. Click a "
        "pattern tile in the treemap to expand constituent companies."
    )

    panel = get_full_ratios_with_pl()
    latest_year = panel["year"].max()
    df = panel[panel["year"] == latest_year].copy()
    df["pattern"] = df["capital_allocation_pattern"].fillna("Mixed")
    df["tile_label"] = df["ticker"]

    # Build treemap data: level 0 = pattern, level 1 = company
    treemap_df = df[
        [
            "pattern",
            "ticker",
            "company_name",
            "fcf_cr",
            "cfo_pat_ratio",
            "composite_quality_score",
            "market_cap_crore",
        ]
    ].copy()
    # Parent column: company rows point to their pattern
    treemap_df["parent"] = treemap_df["pattern"]
    # Pattern rows point to the synthetic root
    pattern_summary = df.groupby("pattern").agg(count=("ticker", "count")).reset_index()
    pattern_summary["parent"] = "All Companies"
    pattern_summary["ticker"] = pattern_summary["pattern"]
    pattern_summary["company_name"] = pattern_summary["pattern"] + (
        " (" + pattern_summary["count"].astype(str) + " companies)"
    )
    pattern_summary["fcf_cr"] = 0
    pattern_summary["cfo_pat_ratio"] = 0
    pattern_summary["composite_quality_score"] = 0
    pattern_summary["market_cap_crore"] = pattern_summary["count"] * 10000
    # Root node
    root = pd.DataFrame(
        [
            {
                "pattern": "All Companies",
                "ticker": "All Companies",
                "company_name": f"All Companies ({len(df)} firms)",
                "parent": "",
                "fcf_cr": 0,
                "cfo_pat_ratio": 0,
                "composite_quality_score": 0,
                "market_cap_crore": len(df) * 20000,
            }
        ]
    )
    treemap_df = pd.concat(
        [root, pattern_summary.assign(pattern="All Companies"), treemap_df],
        ignore_index=True,
        sort=False,
    )

    color_map = {p: PATTERN_COLORS.get(p, "#7F7F7F") for p in df["pattern"].unique()}
    color_map["All Companies"] = "#1F4E78"

    fig = px.treemap(
        treemap_df,
        path=["parent", "pattern", "ticker"],
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
        title=f"Capital allocation map (FY {latest_year}) - sized by market cap",
    )
    fig.update_layout(margin=dict(t=40, l=10, r=10, b=10), height=560)
    st.plotly_chart(fig, use_container_width=True)

    # Pattern legend / counts
    st.subheader("Pattern breakdown")
    counts = (
        df.groupby("pattern").size().reset_index(name="count").sort_values("count", ascending=False)
    )
    cols = st.columns(min(4, len(counts)))
    for i, row in counts.reset_index(drop=True).iterrows():
        with cols[i % 4]:
            color = PATTERN_COLORS.get(row["pattern"], "#7F7F7F")
            st.markdown(
                f"<div style='padding:8px;border-left:5px solid {color};"
                f"background:#F7F9FC'><b>{row['pattern']}</b><br>"
                f"{int(row['count'])} companies</div>",
                unsafe_allow_html=True,
            )

    # Click-to-drilldown: simple pattern selector reveals members
    pattern_choice = st.selectbox(
        "Show companies in pattern",
        ["(select a pattern)", *sorted(df["pattern"].unique().tolist())],
    )
    if pattern_choice != "(select a pattern)":
        members = df[df["pattern"] == pattern_choice][
            [
                "ticker",
                "company_name",
                "broad_sector",
                "fcf_cr",
                "cfo_pat_ratio",
                "composite_quality_score",
            ]
        ].sort_values("composite_quality_score", ascending=False, na_position="last")
        members.columns = ["Ticker", "Company", "Sector", "FCF (Cr)", "CFO/PAT", "Composite"]
        st.dataframe(members, hide_index=True, use_container_width=True)
