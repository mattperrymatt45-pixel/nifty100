"""Screen 02 - Company Profile (Day 23).

Autocomplete search, identity card, 6 KPI tiles, 10-year Revenue/PAT bar
chart, ROE/ROCE dual-axis line chart, and pros/cons badges.
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


def _search_box(companies: pd.DataFrame) -> str | None:
    """Render the text-search box with autocomplete-style dropdown."""
    # Build (ticker, name) -> label mapping
    labels = [f"{row['ticker']} - {row['company_name']}" for _, row in companies.iterrows()]
    label_to_ticker = {
        f"{row['ticker']} - {row['company_name']}": row["ticker"] for _, row in companies.iterrows()
    }

    typed = st.text_input(
        "Search company (type ticker or name, then select below)",
        value="",
        placeholder="e.g. TCS, INFY, Reliance, HDFC Bank",
        help="Type a ticker or a substring of the company name, then pick from " "the dropdown.",
    )
    filtered = labels
    if typed.strip():
        q = typed.strip().upper()
        filtered = [lab for lab in labels if q in lab.upper()]
        if not filtered:
            filtered = labels  # fall back to full list if no match

    selection = st.selectbox(
        "Matching companies",
        options=filtered,
        index=0 if filtered else None,
        key="profile_select",
    )
    if not selection:
        return None
    return label_to_ticker.get(selection)


def _company_card(info: dict) -> None:
    """Render identity card with name, sector, sub-sector, NSE ticker, about."""
    name = info.get("company_name", "Unknown")
    ticker = info.get("ticker", "")
    sector = info.get("broad_sector") or "-"
    sub = info.get("sub_sector") or "-"
    cap = info.get("market_cap_category") or "-"
    about = info.get("about_company") or "No description available."
    website = info.get("website") or ""

    st.subheader(f"{name}  (`{ticker}`)")
    meta1, meta2, meta3 = st.columns(3)
    meta1.metric("NSE Ticker", ticker)
    meta2.metric("Sector", sector)
    meta3.metric("Market-cap category", cap)
    st.caption(f"Sub-sector: {sub}")
    if website:
        st.caption(f"Website: {website}")
    st.markdown(
        f"<div style='padding:10px 14px;border-left:4px solid #1F77B4;"
        f"background:#F7F9FC;border-radius:4px'>{about}</div>",
        unsafe_allow_html=True,
    )


def _kpi_tiles(latest: pd.Series) -> None:
    """Render 6 KPI tiles for the latest year."""

    def _fmt(v: object, suffix: str = "", digits: int = 1) -> str:
        if v is None or pd.isna(v):
            return "n/a"
        return f"{float(v):.{digits}f}{suffix}"

    roe = latest.get("return_on_equity_pct")
    roce = latest.get("roce_pct")
    npm = latest.get("net_profit_margin_pct")
    de = latest.get("debt_to_equity")
    rev5 = latest.get("revenue_cagr_5yr")
    fcf = latest.get("free_cash_flow_cr")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("ROE", _fmt(roe, "%"))
    c2.metric("ROCE", _fmt(roce, "%"))
    c3.metric("Net Profit Margin", _fmt(npm, "%"))
    c4.metric("D/E", _fmt(de, digits=2))
    c5.metric("Revenue CAGR 5y", _fmt(rev5, "%"))
    c6.metric("Free Cash Flow (Cr)", _fmt(fcf, digits=0))


def _revenue_pat_chart(pl: pd.DataFrame) -> None:
    """10-year grouped bar chart for Revenue (sales) and Net Profit.

    Rows with NaN sales/profit are dropped; if fewer than 10 years of
    history exist an informational note is rendered above the chart.
    """
    plot_df = pl.head(10).copy()  # already desc - head = most recent
    plot_df = plot_df.sort_values("year")
    plot_df["sales"] = pd.to_numeric(plot_df["sales"], errors="coerce")
    plot_df["net_profit"] = pd.to_numeric(plot_df["net_profit"], errors="coerce")
    plot_df = plot_df.dropna(subset=["sales"])
    if plot_df.empty:
        st.info("No revenue history available for this company.")
        return
    if len(plot_df) < 10:
        st.caption(
            f"Note: only {len(plot_df)} year(s) of revenue history available " "(partial data)."
        )
    plot_df["Revenue (Cr)"] = plot_df["sales"].astype(float)
    plot_df["Net Profit (Cr)"] = plot_df["net_profit"].fillna(0).astype(float)

    fig = go.Figure()
    fig.add_bar(
        x=plot_df["year"], y=plot_df["Revenue (Cr)"], name="Revenue", marker_color="#1F77B4"
    )
    fig.add_bar(
        x=plot_df["year"],
        y=plot_df["Net Profit (Cr)"],
        name="Net Profit",
        marker_color="#2CA02C",
    )
    fig.update_layout(
        barmode="group",
        title="Revenue & Net Profit (Cr)",
        xaxis_title="Financial Year",
        yaxis_title="Cr",
        height=400,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def _roe_roce_chart(ratios: pd.DataFrame) -> None:
    """Dual-axis line chart: ROE and ROCE over time. NaN points are skipped."""
    plot_df = ratios.sort_values("year").copy()
    for col in ("return_on_equity_pct", "roce_pct"):
        plot_df[col] = pd.to_numeric(plot_df[col], errors="coerce")
    plot_df = plot_df.dropna(subset=["return_on_equity_pct", "roce_pct"], how="all")
    if plot_df.empty:
        st.info("No ROE/ROCE history available for this company.")
        return
    roe = plot_df["return_on_equity_pct"]
    roce = plot_df["roce_pct"]
    fig = go.Figure()
    if roe.notna().any():
        fig.add_trace(
            go.Scatter(
                x=plot_df.loc[roe.notna(), "year"],
                y=roe.dropna(),
                name="ROE %",
                mode="lines+markers",
                line=dict(color="#1F77B4", width=2.5),
            )
        )
    if roce.notna().any():
        fig.add_trace(
            go.Scatter(
                x=plot_df.loc[roce.notna(), "year"],
                y=roce.dropna(),
                name="ROCE %",
                mode="lines+markers",
                line=dict(color="#FF4B4B", width=2.5, dash="dash"),
            )
        )
    fig.update_layout(
        title="ROE & ROCE trend (%)",
        xaxis_title="Financial Year",
        yaxis_title="Percent",
        height=400,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def _pros_cons(ticker: str) -> None:
    """Render pros/cons as green-check / red-cross badge lists."""
    pros, cons = get_prosandcons(ticker)
    left, right = st.columns(2)
    with left:
        st.markdown("#### Strengths")
        if not pros:
            st.caption("No pros data available for this company.")
        else:
            for p in pros:
                st.markdown(f":green[✅] {p}")
    with right:
        st.markdown("#### Weaknesses / Risks")
        if not cons:
            st.caption("No cons data available for this company.")
        else:
            for c in cons:
                st.markdown(f":red[❌] {c}")


def render() -> None:
    """Render the Company Profile page."""
    st.title("Company Profile")
    st.caption("Per-company fundamentals drill-down")

    companies = get_companies()
    ticker = _search_box(companies)

    if ticker is None:
        st.info("Start typing a company name or ticker to begin.")
        return

    info_df = companies[companies["ticker"] == ticker]
    if info_df.empty:
        st.error("Ticker not found - please try another.")
        return
    info = info_df.iloc[0].to_dict()

    _company_card(info)
    st.divider()

    ratios = get_ratios(ticker)
    pl = get_pl(ticker)
    if ratios.empty:
        st.warning("No financial ratios found for this ticker.")
        return

    latest = ratios.iloc[0]
    st.markdown(f"### Latest FY snapshot: `{latest['year']}`")
    _kpi_tiles(latest)
    st.divider()

    if not pl.empty:
        _revenue_pat_chart(pl)
    _roe_roce_chart(ratios)

    st.divider()
    _pros_cons(ticker)
