"""Screen 05 - Trend Analysis.

Company search plus multi-metric selector overlaying up to 3 metrics on
a Plotly dual-Y line chart with YoY change annotations at the latest point.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.utils.db import get_companies, get_full_ratios_with_pl
from src.dashboard.utils.theme import (
    CHART_PALETTE,
    COLORS,
    app_stamp,
    fy_short,
    page_header,
    plotly_chart,
    section_label,
)

METRICS = {
    "Revenue (Rs Cr)": ("sales", False),
    "Net Profit (Rs Cr)": ("net_profit", False),
    "ROE (%)": ("return_on_equity_pct", False),
    "ROCE (%)": ("roce_pct", False),
    "Operating Margin (%)": ("operating_profit_margin_pct", False),
    "Net Margin (%)": ("net_profit_margin_pct", False),
    "Debt/Equity": ("debt_to_equity", True),
    "Free Cash Flow (Rs Cr)": ("free_cash_flow_cr", False),
    "Interest Coverage": ("interest_coverage", False),
    "EPS (Rs)": ("earnings_per_share", False),
}


def _select_ticker(companies: pd.DataFrame) -> str:
    labels = [f"{r['ticker']} - {r['company_name']}" for _, r in companies.iterrows()]
    label_to_ticker = {
        f"{r['ticker']} - {r['company_name']}": r["ticker"] for _, r in companies.iterrows()
    }
    default_idx = next((i for i, lab in enumerate(labels) if lab.startswith("TCS - ")), 0)
    sel = st.selectbox("Company", labels, index=default_idx)
    return label_to_ticker[sel]


def _yoy_pct(prev: float, curr: float) -> str | None:
    if prev is None or pd.isna(prev) or prev == 0 or pd.isna(curr):
        return None
    pct = (curr - prev) / abs(prev) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.0f}%"


def render() -> None:
    """Render the Trend Analysis page."""
    page_header("Trend Analysis", "Multi-year KPI trends with YoY change annotations.")

    companies = get_companies()
    ticker = _select_ticker(companies)

    selected = st.multiselect(
        "Metrics (up to 3)",
        options=list(METRICS.keys()),
        default=["Revenue (Rs Cr)", "Net Profit (Rs Cr)"],
        max_selections=3,
    )
    if not selected:
        st.info("Select at least one metric to plot.")
        app_stamp()
        return

    panel = get_full_ratios_with_pl()
    sub = panel[panel["company_id"] == ticker].sort_values("year").tail(10).copy()
    if sub.empty:
        st.warning(f"No trend data available for {ticker}.")
        app_stamp()
        return

    name_row = sub.iloc[0]
    section_label(f"{name_row['company_name']} ({ticker})")
    display_years = sub["year"].map(fy_short)

    fig = go.Figure()
    axis_used = {"y": False, "y2": False}
    annotations: list[dict] = []

    for i, mname in enumerate(selected):
        col, _inv = METRICS[mname]
        series = pd.to_numeric(sub[col], errors="coerce")
        yaxis = "y" if not axis_used["y"] else ("y2" if not axis_used["y2"] else "y")
        axis_used[yaxis] = True
        color = CHART_PALETTE[i % len(CHART_PALETTE)]
        fig.add_trace(
            go.Scatter(
                x=display_years,
                y=series,
                name=mname,
                mode="lines+markers",
                line=dict(color=color, width=2.3),
                marker=dict(size=5, color=color),
                yaxis=yaxis,
                hovertemplate=f"{mname}: %{{y:,.1f}}<extra></extra>",
            )
        )
        vals = series.tolist()
        years = display_years.tolist()
        for j in range(1, len(vals)):
            yoy = _yoy_pct(vals[j - 1], vals[j])
            if yoy and j == len(vals) - 1:
                ycolor = COLORS["green"] if not yoy.startswith("-") else COLORS["red"]
                annotations.append(
                    dict(
                        x=years[j],
                        y=vals[j],
                        xanchor="left",
                        yanchor="bottom",
                        text=f"<b>{yoy}</b>",
                        showarrow=False,
                        font=dict(color=ycolor, size=11, family="JetBrains Mono, monospace"),
                        xref="x",
                        yref=f"{yaxis if yaxis == 'y' else 'y2'}",
                        xshift=8,
                    )
                )

    layout: dict = dict(
        title=f"{ticker} - 10-Year Trend",
        xaxis_title="Financial Year",
        yaxis=dict(title=selected[0], side="left"),
        height=480,
        annotations=annotations,
    )
    if len(selected) > 1 and axis_used["y2"]:
        layout["yaxis2"] = dict(
            title=selected[1] if len(selected) >= 2 else "",
            side="right",
            overlaying="y",
            showgrid=False,
        )
    fig.update_layout(**layout)
    plotly_chart(fig, height=480)

    with st.expander("Data Table"):
        show_cols = ["year"] + [METRICS[m][0] for m in selected]
        tbl = sub[show_cols].copy()
        tbl["year"] = tbl["year"].map(fy_short)
        tbl.columns = ["Year", *list(selected)]
        for c in tbl.columns[1:]:
            tbl[c] = pd.to_numeric(tbl[c], errors="coerce")
        st.dataframe(
            tbl,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Year": st.column_config.TextColumn("Year"),
                **{m: st.column_config.NumberColumn(m, format="%.2f") for m in selected},
            },
        )

    app_stamp()
