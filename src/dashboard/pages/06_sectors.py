"""Screen 06 - Sector Analysis (Day 25).

Sector dropdown, bubble chart (X=Revenue, Y=ROE, size=Market Cap,
color=sub-sector), and median-KPI bar chart below.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.utils.db import get_full_ratios_with_pl


def render() -> None:
    """Render the "Sectors" dashboard page (median-KPI heatmap and sector drill-down)."""
    st.title("Sector Analysis")
    st.caption("Bubble map of revenue vs profitability, sized by market cap.")

    panel = get_full_ratios_with_pl()
    latest_year = panel["year"].max()
    latest = panel[panel["year"] == latest_year].copy()
    latest = latest.dropna(subset=["sales", "return_on_equity_pct", "market_cap_crore"])

    sectors_list = sorted(latest["broad_sector"].dropna().unique().tolist())
    choice = st.selectbox("Sector", ["All sectors", *sectors_list], index=0)
    sub = latest if choice == "All sectors" else latest[latest["broad_sector"] == choice]
    if sub.empty:
        st.warning(f"No data available for {choice}.")
        return

    # Bubble chart
    plot_df = sub.copy()
    plot_df["Market Cap (Cr)"] = plot_df["market_cap_crore"].clip(lower=1)
    plot_df["Revenue (Cr)"] = plot_df["sales"]
    plot_df["ROE %"] = plot_df["return_on_equity_pct"]
    color_col = "sub_sector" if choice != "All sectors" else "broad_sector"

    fig = px.scatter(
        plot_df,
        x="Revenue (Cr)",
        y="ROE %",
        size="Market Cap (Cr)",
        color=color_col,
        hover_name="company_name",
        hover_data={
            "company_id": True,
            "Revenue (Cr)": ":,.0f",
            "ROE %": ":.1f",
            "Market Cap (Cr)": ":,.0f",
            "market_cap_crore": False,
            "sales": False,
            "return_on_equity_pct": False,
        },
        size_max=60,
        log_x=True,
        title=f"{choice} - Revenue vs ROE vs Market Cap (FY {latest_year})",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True)

    # Median KPI bar chart
    st.subheader("Median KPIs")
    kpi_cols = {
        "ROE %": "return_on_equity_pct",
        "ROCE %": "roce_pct",
        "NPM %": "net_profit_margin_pct",
        "D/E": "debt_to_equity",
        "Rev CAGR 5y %": "revenue_cagr_5yr",
        "PAT CAGR 5y %": "pat_cagr_5yr",
        "Div Yield %": "dividend_yield_pct",
    }
    if choice == "All sectors":
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
                marker_color="#1F77B4",
                text=bar_df[col].map(lambda v: f"{v:.1f}"),
                textposition="outside",
            )
        )
        fig2.update_layout(
            title=f"Median {kpi_choice} by sector",
            xaxis_title=kpi_choice,
            yaxis_title="",
            height=480,
            margin=dict(l=10, r=40, t=50, b=10),
        )
    else:
        meds = sub[list(kpi_cols.values())].median(numeric_only=True)
        names = list(kpi_cols.keys())
        vals = [float(meds[kpi_cols[n]]) for n in names]
        pairs = sorted(
            zip(names, vals, strict=False), key=lambda x: x[1] if not pd.isna(x[1]) else 0
        )
        names_s, vals_s = zip(*pairs, strict=False)
        fig2 = go.Figure(
            go.Bar(
                x=vals_s,
                y=names_s,
                orientation="h",
                marker_color="#1F77B4",
                text=[f"{v:.1f}" if not pd.isna(v) else "-" for v in vals_s],
                textposition="outside",
            )
        )
        fig2.update_layout(
            title=f"{choice} - median KPIs",
            xaxis_title="Median value",
            yaxis_title="",
            height=480,
            margin=dict(l=10, r=40, t=50, b=10),
        )
    st.plotly_chart(fig2, use_container_width=True)

    with st.expander("Constituent table"):
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
            "Revenue (Cr)",
            "ROE %",
            "ROCE %",
            "Mcap (Cr)",
        ]
        st.dataframe(show, hide_index=True, use_container_width=True)
