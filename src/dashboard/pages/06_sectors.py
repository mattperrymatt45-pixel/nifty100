"""Screen 06 - Sector Analysis.

Sector selector, bubble chart (X=Revenue, Y=ROE, size=Market Cap,
color=sub-sector), and median-KPI bar chart.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.utils.db import get_full_ratios_with_pl
from src.dashboard.utils.theme import (
    CHART_GOLD,
    CHART_PALETTE,
    COLORS,
    app_stamp,
    fmt_cr,
    page_header,
    percent_col,
    plotly_chart,
    section_label,
    text_col,
)


def render() -> None:
    """Render the Sector Analysis page."""
    page_header("Sector Analysis", "Revenue vs profitability, sized by market capitalization.")

    panel = get_full_ratios_with_pl()
    latest_year = panel["year"].max()
    latest = panel[panel["year"] == latest_year].copy()
    latest = latest.dropna(subset=["sales", "return_on_equity_pct", "market_cap_crore"])

    sectors_list = sorted(latest["broad_sector"].dropna().unique().tolist())
    choice = st.selectbox("Sector", ["All Sectors", *sectors_list], index=0)
    sub = latest if choice == "All Sectors" else latest[latest["broad_sector"] == choice]
    if sub.empty:
        st.warning(f"No data available for {choice}.")
        app_stamp()
        return

    # Bubble chart
    plot_df = sub.copy()
    plot_df["Market Cap"] = plot_df["market_cap_crore"].clip(lower=1)
    plot_df["Revenue"] = plot_df["sales"]
    plot_df["ROE"] = plot_df["return_on_equity_pct"]
    color_col = "sub_sector" if choice != "All Sectors" else "broad_sector"

    fig = px.scatter(
        plot_df,
        x="Revenue",
        y="ROE",
        size="Market Cap",
        color=color_col,
        hover_name="company_name",
        hover_data={
            "company_id": True,
            "Revenue": ":,.0f",
            "ROE": ":.2f",
            "Market Cap": ":,.0f",
            "market_cap_crore": False,
            "sales": False,
            "return_on_equity_pct": False,
        },
        size_max=55,
        log_x=True,
        title=f"{choice} - Revenue vs ROE vs Market Cap (FY {latest_year})",
        color_discrete_sequence=CHART_PALETTE,
    )
    fig.update_traces(marker=dict(line=dict(width=0.5, color=COLORS["bg"]), opacity=0.85))
    fig.update_layout(
        height=520,
        xaxis_title="Revenue (Rs Cr, log scale)",
        yaxis_title="ROE (%)",
    )
    plotly_chart(fig, height=520)

    # Median KPI bar chart
    section_label("Median KPIs")
    kpi_cols = {
        "ROE (%)": "return_on_equity_pct",
        "ROCE (%)": "roce_pct",
        "Net Margin (%)": "net_profit_margin_pct",
        "D/E": "debt_to_equity",
        "Rev CAGR 5Y (%)": "revenue_cagr_5yr",
        "PAT CAGR 5Y (%)": "pat_cagr_5yr",
        "Div Yield (%)": "dividend_yield_pct",
    }
    if choice == "All Sectors":
        medians = (
            sub.groupby("broad_sector")[list(kpi_cols.values())]
            .median(numeric_only=True)
            .reset_index()
        )
        kpi_choice = st.selectbox("KPI", list(kpi_cols.keys()), index=0)
        col = kpi_cols[kpi_choice]
        bar_df = medians[["broad_sector", col]].dropna().sort_values(col, ascending=True)
        fig2 = go.Figure(
            go.Bar(
                x=bar_df[col],
                y=bar_df["broad_sector"],
                orientation="h",
                marker=dict(color=CHART_GOLD),
                marker_line_width=0,
                text=bar_df[col].map(lambda v: f"{v:.2f}"),
                textposition="outside",
                textfont=dict(color=COLORS["text"], size=11),
            )
        )
        fig2.update_layout(
            title=f"Median {kpi_choice} by Sector",
            xaxis_title=kpi_choice,
            yaxis_title="",
            height=520,
        )
    else:
        meds = sub[list(kpi_cols.values())].median(numeric_only=True)
        names = list(kpi_cols.keys())
        vals = [float(meds[kpi_cols[n]]) for n in names]
        pairs = sorted(
            zip(names, vals, strict=False), key=lambda x: x[1] if not pd.isna(x[1]) else -1e9
        )
        names_s, vals_s = zip(*pairs, strict=False)
        fig2 = go.Figure(
            go.Bar(
                x=vals_s,
                y=names_s,
                orientation="h",
                marker=dict(color=CHART_GOLD),
                marker_line_width=0,
                text=[f"{v:.2f}" if not pd.isna(v) else "-" for v in vals_s],
                textposition="outside",
                textfont=dict(color=COLORS["text"], size=11),
            )
        )
        fig2.update_layout(
            title=f"{choice} - Median KPIs",
            xaxis_title="Median Value",
            yaxis_title="",
            height=520,
        )
    plotly_chart(fig2, height=520)

    with st.expander("Constituent Table"):
        section_label(f"{choice} Constituents")
        show = sub[
            [
                "company_id",
                "company_name",
                "broad_sector",
                "sub_sector",
                "sales",
                "return_on_equity_pct",
                "roce_pct",
                "market_cap_crore",
            ]
        ].copy()
        show.columns = [
            "Ticker",
            "Company",
            "Sector",
            "Sub-sector",
            "Revenue",
            "ROE",
            "ROCE",
            "Market Cap",
        ]
        show["Revenue"] = show["Revenue"].map(lambda v: fmt_cr(v))
        show["Market Cap"] = show["Market Cap"].map(lambda v: fmt_cr(v))
        st.dataframe(
            show,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Ticker": text_col("Ticker"),
                "Company": text_col("Company"),
                "Sector": text_col("Sector"),
                "Sub-sector": text_col("Sub-sector"),
                "Revenue": text_col("Revenue"),
                "ROE": percent_col("ROE"),
                "ROCE": percent_col("ROCE"),
                "Market Cap": text_col("Market Cap"),
            },
        )

    app_stamp()
