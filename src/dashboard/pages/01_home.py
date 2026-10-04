"""Screen 01 - Overview / Market Dashboard.

KPI tiles, sector composition treemap, top-5 composite table, and a
sidebar FY selector that drives everything.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard.utils.db import get_available_years, get_kpis_for_year, get_peer_groups
from src.dashboard.utils.theme import (
    CHART_PALETTE,
    COLORS,
    app_stamp,
    fmt_cr,
    number_col,
    page_header,
    percent_col,
    plotly_chart,
    ratio_col,
    section_label,
    style_dataframe,
    text_col,
)

_YEAR_RANGE = [f"{y}-03" for y in range(2024, 2018, -1)]


def _year_selector() -> str:
    """Render the global FY selector in the sidebar (shared across pages)."""
    available = set(get_available_years())
    options = [y for y in _YEAR_RANGE if y in available]
    with st.sidebar:
        st.divider()
        st.markdown("<div class='section-label'>Filters</div>", unsafe_allow_html=True)
        return st.selectbox(
            "Financial Year",
            options=options if options else list(available),
            index=0,
            key="home_year",
            help="KPI tiles, sector composition and top-5 update when changed.",
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
    c1.metric("Average ROE", f"{avg_roe:.2f}%")
    c2.metric("Median P/E", f"{med_pe:.2f}x" if pd.notna(med_pe) else "n/a")
    c3.metric("Median D/E", f"{med_de:.2f}" if pd.notna(med_de) else "n/a")
    c4.metric("Constituents", f"{total}")
    c5.metric("Median Rev CAGR 5Y", f"{med_rev_cagr:.2f}%" if pd.notna(med_rev_cagr) else "n/a")
    c6.metric("Debt-Free", f"{debt_free_count}")
    st.caption(f"Fiscal year ending {year}. Source: financial_ratios, market_cap.")


def _sector_treemap(df: pd.DataFrame) -> None:
    """Treemap of company count by sector (cleaner than donut for terminal look)."""
    sector_counts = (
        df.groupby("broad_sector", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    sector_counts["broad_sector"] = sector_counts["broad_sector"].fillna("Unclassified")
    sector_counts["parent"] = "Nifty 100"
    root = pd.DataFrame([{"broad_sector": "Nifty 100", "count": len(df), "parent": ""}])
    tm = pd.concat([root, sector_counts], ignore_index=True)

    fig = px.treemap(
        tm,
        path=["parent", "broad_sector"],
        values="count",
        color="broad_sector",
        color_discrete_sequence=CHART_PALETTE,
        hover_data={"count": True},
    )
    fig.update_traces(
        textinfo="label+value",
        textfont=dict(family="Inter, sans-serif", size=12, color=COLORS["text"]),
        marker=dict(cornerradius=3),
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=10),
        height=420,
    )
    plotly_chart(fig, height=420)


def _top5_table(df: pd.DataFrame) -> None:
    """Render the top-5 companies by composite quality score with proper formatting."""
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
    top.columns = ["Ticker", "Company", "Sector", "ROE", "D/E", "Rev CAGR 5Y", "Composite"]
    section_label("Top 5 by Composite Quality")
    st.dataframe(
        style_dataframe(top, green_cols={"ROE", "Rev CAGR 5Y", "Composite"}),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Ticker": text_col("Ticker"),
            "Company": text_col("Company"),
            "Sector": text_col("Sector"),
            "ROE": percent_col("ROE"),
            "D/E": number_col("D/E", digits=2),
            "Rev CAGR 5Y": percent_col("Rev CAGR 5Y"),
            "Composite": number_col("Composite", digits=1),
        },
    )


def render() -> None:
    """Render the Overview landing page."""
    year = _year_selector()

    page_header("Market Overview", f"Nifty 100 constituent analytics - FY {year}")

    df = get_kpis_for_year(year)
    if df.empty:
        st.warning(f"No data available for {year}. Select another year.")
        return

    _kpi_tiles(df, year)

    left, right = st.columns([1.35, 1])
    with left:
        section_label("Sector Composition")
        _sector_treemap(df)
    with right:
        section_label("Peer Groups")
        groups = get_peer_groups()
        show = groups[["peer_group_name", "member_count", "benchmark_count"]].copy()
        show.columns = ["Peer Group", "Members", "Benchmarks"]
        show.columns = ["Peer Group", "Members", "Benchmarks"]
        _g = groups.rename(
            columns={
                "peer_group_name": "Peer Group",
                "member_count": "Members",
                "benchmark_count": "Benchmarks",
            }
        )[["Peer Group", "Members", "Benchmarks"]]
        st.dataframe(
            _g,
            hide_index=True,
            use_container_width=True,
            height=420,
            column_config={
                "Peer Group": text_col("Peer Group"),
                "Members": number_col("Members", digits=0),
                "Benchmarks": number_col("Benchmarks", digits=0),
            },
        )

    _top5_table(df)

    with st.expander("Full Constituent Table"):
        section_label("All Constituents")
        show = df[
            [
                "ticker",
                "company_name",
                "broad_sector",
                "sub_sector",
                "market_cap_category",
                "market_cap_crore",
                "roe_pct",
                "debt_to_equity",
                "revenue_cagr_5yr",
                "pe_ratio",
                "dividend_yield_pct",
                "composite_quality_score",
            ]
        ].copy()
        show.columns = [
            "Ticker",
            "Company",
            "Sector",
            "Sub-sector",
            "Cap",
            "Market Cap",
            "ROE",
            "D/E",
            "Rev CAGR 5Y",
            "P/E",
            "Div Yield",
            "Composite",
        ]
        # Pre-format currency for display
        show["Market Cap"] = show["Market Cap"].map(lambda v: fmt_cr(v, plain=False))
        st.dataframe(
            style_dataframe(show, green_cols={"ROE", "Rev CAGR 5Y", "Composite"}),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Ticker": text_col("Ticker"),
                "Company": text_col("Company"),
                "Sector": text_col("Sector"),
                "Sub-sector": text_col("Sub-sector"),
                "Cap": text_col("Cap"),
                "Market Cap": text_col("Market Cap"),
                "ROE": percent_col("ROE"),
                "D/E": number_col("D/E", digits=2),
                "Rev CAGR 5Y": percent_col("Rev CAGR 5Y"),
                "P/E": ratio_col("P/E"),
                "Div Yield": percent_col("Div Yield"),
                "Composite": number_col("Composite", digits=1),
            },
        )

    app_stamp()
