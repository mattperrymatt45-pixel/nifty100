"""Screen 05 - Trend Analysis (Day 25).

Company search + multi-metric selector overlaying up to 3 metrics on a
Plotly dual-Y line chart, with YoY % change annotations on each point.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.utils.db import get_companies, get_full_ratios_with_pl

METRICS = {
    "Revenue (Cr)": ("sales", False),
    "Net Profit (Cr)": ("net_profit", False),
    "ROE %": ("return_on_equity_pct", False),
    "ROCE %": ("roce_pct", False),
    "Operating Profit Margin %": ("operating_profit_margin_pct", False),
    "Net Profit Margin %": ("net_profit_margin_pct", False),
    "Debt/Equity": ("debt_to_equity", True),  # inverted axis lower better
    "Free Cash Flow (Cr)": ("free_cash_flow_cr", False),
    "Interest Coverage": ("interest_coverage", False),
    "EPS": ("earnings_per_share", False),
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
    st.title("Trend Analysis")
    st.caption("10-year multi-metric line chart with YoY % change annotations.")

    companies = get_companies()
    ticker = _select_ticker(companies)

    selected = st.multiselect(
        "Metrics (up to 3)",
        options=list(METRICS.keys()),
        default=["Revenue (Cr)", "Net Profit (Cr)"],
        max_selections=3,
    )
    if not selected:
        st.info("Pick at least one metric to plot.")
        return

    panel = get_full_ratios_with_pl()
    sub = panel[panel["company_id"] == ticker].sort_values("year").tail(10).copy()
    if sub.empty:
        st.warning(f"No trend data available for {ticker}.")
        return

    name_row = sub.iloc[0]
    st.subheader(f"{name_row['company_name']} ({ticker})")

    fig = go.Figure()
    palette = ["#1F77B4", "#FF4B4B", "#2CA02C"]
    axis_used = {"y": False, "y2": False}
    annotations: list[dict] = []

    for i, mname in enumerate(selected):
        col, _inv = METRICS[mname]
        series = pd.to_numeric(sub[col], errors="coerce")
        # Put the first metric on left axis; subsequent ones on right axis
        # (so disparate scales don't crush each other).
        yaxis = "y" if not axis_used["y"] else ("y2" if not axis_used["y2"] else "y")
        axis_used[yaxis] = True
        fig.add_trace(
            go.Scatter(
                x=sub["year"],
                y=series,
                name=mname,
                mode="lines+markers+text",
                line=dict(color=palette[i % 3], width=2.5),
                marker=dict(size=7),
                yaxis=yaxis,
                text=[None] * len(series),
                hovertemplate=f"{mname}: %{{y:,.1f}}<extra></extra>",
            )
        )
        # YoY annotations for the last data point of each metric
        vals = series.tolist()
        years = sub["year"].tolist()
        for j in range(1, len(vals)):
            yoy = _yoy_pct(vals[j - 1], vals[j])
            if yoy and j == len(vals) - 1:
                annotations.append(
                    dict(
                        x=years[j],
                        y=vals[j],
                        xanchor="left",
                        yanchor="bottom",
                        text=f"<b>{yoy}</b>",
                        showarrow=False,
                        font=dict(color=palette[i % 3], size=11),
                        xref="x",
                        yref=f"{yaxis if yaxis == 'y' else 'y2'}",
                        xshift=8,
                    )
                )

    layout: dict = dict(
        title=f"{ticker} - 10-year trend",
        xaxis_title="Financial Year",
        yaxis=dict(title=selected[0], side="left"),
        height=480,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
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
    st.plotly_chart(fig, use_container_width=True)

    # Underlying data table (last 10y, selected cols)
    with st.expander("Data table"):
        show_cols = ["year"] + [METRICS[m][0] for m in selected]
        tbl = sub[show_cols].copy()
        tbl.columns = ["Year", *list(selected)]
        st.dataframe(tbl, hide_index=True, use_container_width=True)
