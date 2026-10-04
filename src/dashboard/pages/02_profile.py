"""Screen 02 - Company Profile.

Autocomplete search, identity card, 6 KPI tiles, 10-year Revenue/PAT chart,
ROE/ROCE dual-axis line chart, and structured Strengths/Weaknesses panel.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.utils.db import (
    get_companies,
    get_pl,
    get_prosandcons,
    get_ratios,
)
from src.dashboard.utils.theme import (
    CHART_GOLD,
    CHART_GREEN,
    CHART_RED,
    COLORS,
    app_stamp,
    page_header,
    plotly_chart,
    section_label,
)


def _search_box(companies: pd.DataFrame) -> str | None:
    """Render the text-search box with autocomplete-style dropdown."""
    labels = [f"{row['ticker']} - {row['company_name']}" for _, row in companies.iterrows()]
    label_to_ticker = {
        f"{row['ticker']} - {row['company_name']}": row["ticker"] for _, row in companies.iterrows()
    }

    typed = st.text_input(
        "Search Company",
        value="",
        placeholder="Enter ticker or company name, e.g. TCS, INFY, HDFCBANK",
    )
    filtered = labels
    if typed.strip():
        q = typed.strip().upper()
        filtered = [lab for lab in labels if q in lab.upper()]
        if not filtered:
            filtered = labels

    selection = st.selectbox(
        "Matching Companies",
        options=filtered,
        index=0 if filtered else None,
        key="profile_select",
    )
    if not selection:
        return None
    return label_to_ticker.get(selection)


def _company_card(info: dict) -> None:
    """Identity card: name, sector, sub-sector, NSE ticker, about."""
    name = info.get("company_name", "Unknown")
    ticker = info.get("ticker", "")
    sector = info.get("broad_sector") or "-"
    sub = info.get("sub_sector") or "-"
    cap = info.get("market_cap_category") or "-"
    about = info.get("about_company") or "No description available."
    website = info.get("website") or ""

    st.markdown(
        f"<div style='margin:0.3rem 0 0.5rem'>"
        f"<span style='font-size:1.2rem;font-weight:700;letter-spacing:-0.01em'>{name}</span>"
        f"&nbsp;&nbsp;<span style='font-family:JetBrains Mono,SF Mono,monospace;"
        f"color:{COLORS['gold']};background:{COLORS['card']};border:1px solid {COLORS['border']};"
        f"padding:2px 8px;border-radius:3px;font-size:0.78rem'>{ticker}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    meta1, meta2, meta3 = st.columns(3)
    meta1.metric("Sector", sector)
    meta2.metric("Sub-sector", sub)
    meta3.metric("Market Cap Category", cap)
    if website:
        st.caption(f"Website: {website}")
    st.markdown(
        f"<div style='padding:10px 14px;border-left:3px solid {COLORS['gold']};"
        f"background:{COLORS['card']};border-radius:0 3px 3px 0;color:{COLORS['text']};"
        f"font-size:0.88rem;line-height:1.5'>{about}</div>",
        unsafe_allow_html=True,
    )


def _kpi_tiles(latest: pd.Series) -> None:
    """Render 6 KPI tiles for the latest year."""

    def _fmt(v: object, suffix: str = "", digits: int = 1) -> str:
        if v is None or pd.isna(v):
            return "n/a"
        return f"{float(v):,.{digits}f}{suffix}"

    roe = latest.get("return_on_equity_pct")
    roce = latest.get("roce_pct")
    npm = latest.get("net_profit_margin_pct")
    de = latest.get("debt_to_equity")
    rev5 = latest.get("revenue_cagr_5yr")
    fcf = latest.get("free_cash_flow_cr")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("ROE", _fmt(roe, "%", 2))
    c2.metric("ROCE", _fmt(roce, "%", 2))
    c3.metric("Net Margin", _fmt(npm, "%", 2))
    c4.metric("D/E", _fmt(de, digits=2))
    c5.metric("Revenue CAGR 5Y", _fmt(rev5, "%", 2))
    c6.metric("Free Cash Flow", _fmt(fcf, " Cr", 0))


def _revenue_pat_chart(pl: pd.DataFrame) -> None:
    """10-year grouped bar chart for Revenue and Net Profit."""
    plot_df = pl.head(10).copy().sort_values("year")
    plot_df["sales"] = pd.to_numeric(plot_df["sales"], errors="coerce")
    plot_df["net_profit"] = pd.to_numeric(plot_df["net_profit"], errors="coerce")
    plot_df = plot_df.dropna(subset=["sales"])
    if plot_df.empty:
        st.info("No revenue history available.")
        return
    if len(plot_df) < 10:
        st.caption(f"Partial history available - {len(plot_df)} year(s).")
    plot_df["Revenue"] = plot_df["sales"].astype(float)
    plot_df["Net Profit"] = plot_df["net_profit"].fillna(0).astype(float)

    fig = go.Figure()
    fig.add_bar(
        x=plot_df["year"],
        y=plot_df["Revenue"],
        name="Revenue",
        marker_color=CHART_GOLD,
        marker_line_width=0,
    )
    fig.add_bar(
        x=plot_df["year"],
        y=plot_df["Net Profit"],
        name="Net Profit",
        marker_color=CHART_GREEN,
        marker_line_width=0,
    )
    fig.update_layout(
        barmode="group",
        title="Revenue and Net Profit (Rs Cr)",
        xaxis_title="Financial Year",
        yaxis_title="Rs Cr",
        height=400,
        bargap=0.25,
        bargroupgap=0.1,
    )
    plotly_chart(fig, height=400)


def _roe_roce_chart(ratios: pd.DataFrame) -> None:
    """Dual-line chart: ROE and ROCE over time."""
    plot_df = ratios.sort_values("year").copy()
    for col in ("return_on_equity_pct", "roce_pct"):
        plot_df[col] = pd.to_numeric(plot_df[col], errors="coerce")
    plot_df = plot_df.dropna(subset=["return_on_equity_pct", "roce_pct"], how="all")
    if plot_df.empty:
        st.info("No ROE/ROCE history available.")
        return
    fig = go.Figure()
    roe = plot_df["return_on_equity_pct"]
    roce = plot_df["roce_pct"]
    if roe.notna().any():
        fig.add_trace(
            go.Scatter(
                x=plot_df.loc[roe.notna(), "year"],
                y=roe.dropna(),
                name="ROE",
                mode="lines+markers",
                line=dict(color=CHART_GOLD, width=2.2),
                marker=dict(size=5, color=CHART_GOLD),
            )
        )
    if roce.notna().any():
        fig.add_trace(
            go.Scatter(
                x=plot_df.loc[roce.notna(), "year"],
                y=roce.dropna(),
                name="ROCE",
                mode="lines+markers",
                line=dict(color=COLORS["blue"], width=2.2, dash="dash"),
                marker=dict(size=5, color=COLORS["blue"]),
            )
        )
    fig.update_layout(
        title="ROE and ROCE Trend (%)",
        xaxis_title="Financial Year",
        yaxis_title="Percent",
        height=400,
    )
    plotly_chart(fig, height=400)


def _pros_cons(ticker: str) -> None:
    """Render structured strengths/risks panels."""
    pros, cons = get_prosandcons(ticker)
    left, right = st.columns(2)
    with left:
        section_label("Strengths")
        if not pros:
            st.caption("No strength data available.")
        else:
            for p in pros:
                st.markdown(
                    f"<div style='padding:6px 10px;border-left:2px solid {CHART_GREEN};"
                    f"background:{COLORS['card']};margin-bottom:4px;font-size:0.85rem'>"
                    f"{p}</div>",
                    unsafe_allow_html=True,
                )
    with right:
        section_label("Risks")
        if not cons:
            st.caption("No risk data available.")
        else:
            for c in cons:
                st.markdown(
                    f"<div style='padding:6px 10px;border-left:2px solid {CHART_RED};"
                    f"background:{COLORS['card']};margin-bottom:4px;font-size:0.85rem'>"
                    f"{c}</div>",
                    unsafe_allow_html=True,
                )


def render() -> None:
    """Render the Company Profile page."""
    page_header("Company Profile", "Single-name fundamental drill-down")

    companies = get_companies()
    ticker = _search_box(companies)

    if ticker is None:
        st.info("Enter a ticker or company name to begin.")
        return

    info_df = companies[companies["ticker"] == ticker]
    if info_df.empty:
        st.error("Ticker not found.")
        return
    info = info_df.iloc[0].to_dict()

    _company_card(info)

    ratios = get_ratios(ticker)
    pl = get_pl(ticker)
    if ratios.empty:
        st.warning("No financial ratios found.")
        return

    latest = ratios.iloc[0]
    section_label(f"Latest FY Snapshot - {latest['year']}")
    _kpi_tiles(latest)

    if not pl.empty:
        section_label("Revenue and Earnings")
        _revenue_pat_chart(pl)
    section_label("Profitability Trend")
    _roe_roce_chart(ratios)

    section_label("Qualitative Assessment")
    _pros_cons(ticker)

    app_stamp()
