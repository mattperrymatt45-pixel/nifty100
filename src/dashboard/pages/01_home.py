"""Screen 01 - Home / Overview (Day 23).

KPI tiles, sector-breakdown donut, top-5 composite table, and a sidebar
year selector (2019-2024) that drives everything.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard.utils.db import get_available_years, get_kpis_for_year, get_peer_groups

_YEAR_RANGE = [f"{y}-03" for y in range(2024, 2018, -1)]  # 2024 -> 2019


def _year_selector() -> str:
    """Render the global FY selector in the sidebar (shared across pages)."""
    available = set(get_available_years())
    options = [y for y in _YEAR_RANGE if y in available]
    with st.sidebar:
        st.divider()
        st.subheader("Filters")
        return st.selectbox(
            "Financial Year",
            options=options if options else list(available),
            index=0,
            key="home_year",
            help="KPI tiles, sector chart and top-5 all update when changed.",
        )


def _kpi_tiles(df: pd.DataFrame, year: str) -> None:
    """Render 6 KPI tiles at the top of the page."""
    avg_roe = df["roe_pct"].mean(skipna=True)
    med_pe = df["pe_ratio"].median(skipna=True)
    med_de = df["debt_to_equity"].median(skipna=True)
    total = len(df)
    med_rev_cagr = df["revenue_cagr_5yr"].median(skipna=True)
    debt_free_count = int(((df["icr_label"] == "Debt Free") | (df["debt_to_equity"] <= 0.05)).sum())

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Average ROE", f"{avg_roe:.1f}%")
    c2.metric("Median P/E", f"{med_pe:.1f}x" if pd.notna(med_pe) else "n/a")
    c3.metric("Median D/E", f"{med_de:.2f}" if pd.notna(med_de) else "n/a")
    c4.metric("Total Companies", f"{total}")
    c5.metric("Median Rev CAGR 5y", f"{med_rev_cagr:.1f}%" if pd.notna(med_rev_cagr) else "n/a")
    c6.metric("Debt-Free Companies", f"{debt_free_count}")
    st.caption(f"All metrics for fiscal year ending {year}. Source: financial_ratios + market_cap.")


def _sector_donut(df: pd.DataFrame) -> None:
    """Render Plotly donut chart of company count by broad sector."""
    sector_counts = (
        df.groupby("broad_sector", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    sector_counts["broad_sector"] = sector_counts["broad_sector"].fillna("Unclassified")

    fig = px.pie(
        sector_counts,
        names="broad_sector",
        values="count",
        hole=0.45,
        color_discrete_sequence=px.colors.qualitative.Set3,
        title="Companies by sector",
    )
    fig.update_traces(textposition="outside", textinfo="label+percent")
    fig.update_layout(
        legend=dict(orientation="v", yanchor="top", y=1.0, xanchor="left", x=1.02),
        margin=dict(l=10, r=10, t=50, b=10),
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)


def _top5_table(df: pd.DataFrame) -> None:
    """Render the top-5 companies by composite quality score."""
    cols = [
        "ticker",
        "company_name",
        "broad_sector",
        "roe_pct",
        "debt_to_equity",
        "revenue_cagr_5yr",
        "composite_quality_score",
    ]
    top = df[cols].head(5).copy()
    top.columns = ["Ticker", "Company", "Sector", "ROE %", "D/E", "Rev CAGR 5y %", "Composite"]
    for c in ["ROE %", "D/E", "Rev CAGR 5y %", "Composite"]:
        top[c] = top[c].map(lambda v: f"{v:.1f}" if pd.notna(v) else "-")
    st.markdown("**Top 5 companies by composite quality score**")
    st.dataframe(top, hide_index=True, use_container_width=True)


def render() -> None:
    """Render the Home landing page."""
    year = _year_selector()

    st.title("Nifty 100 Financial Intelligence Platform")
    st.caption(f"Sprint 4 dashboard - FY {year} overview")

    df = get_kpis_for_year(year)
    if df.empty:
        st.warning(f"No data available for {year}. Try another year.")
        return

    _kpi_tiles(df, year)
    st.divider()

    left, right = st.columns([1.3, 1])
    with left:
        _sector_donut(df)
    with right:
        st.subheader("Peer groups")
        groups = get_peer_groups()
        st.dataframe(
            groups[["peer_group_name", "member_count", "benchmark_count"]],
            hide_index=True,
            use_container_width=True,
            height=420,
        )

    st.divider()
    _top5_table(df)

    with st.expander("Full constituent table"):
        show = df[
            [
                "ticker",
                "company_name",
                "broad_sector",
                "sub_sector",
                "market_cap_category",
                "roe_pct",
                "debt_to_equity",
                "revenue_cagr_5yr",
                "composite_quality_score",
            ]
        ].copy()
        for c in ["roe_pct", "debt_to_equity", "revenue_cagr_5yr", "composite_quality_score"]:
            show[c] = show[c].map(lambda v: round(float(v), 1) if pd.notna(v) else np.nan)
        st.dataframe(show, hide_index=True, use_container_width=True)
