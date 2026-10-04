"""Screen 04 - Peer Comparison.

Peer-group selector, scatterpolar radar chart for the selected company
vs peer average, and a KPI table with benchmark row highlighted in gold.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.utils.db import get_peer_groups, get_peers
from src.dashboard.utils.theme import (
    CHART_GOLD,
    COLORS,
    app_stamp,
    number_col,
    page_header,
    percent_col,
    plotly_chart,
    ratio_col,
    section_label,
    text_col,
)

RADAR_AXES = [
    ("roe", "ROE", "roe_pct", False),
    ("roce", "ROCE", "roce_pct", False),
    ("npm", "NPM", "npm_pct", False),
    ("de", "D/E (inv)", "de", True),
    ("cfo_pat", "CFO/PAT", "cfo_pat", False),
    ("pat_cagr", "PAT CAGR", "pat_cagr_5yr", False),
    ("rev_cagr", "REV CAGR", "rev_cagr_5yr", False),
    ("composite", "Composite", "composite", False),
]


def _percentile_rank(series: pd.Series, value: float, invert: bool = False) -> float:
    """Percentile rank on a 0-1 scale (1 = best in group).

    ``invert=True`` flips the scale so that lower raw values rank higher
    (used for D/E, where lower leverage is better). NaN returns 0.5.
    """
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty or pd.isna(value):
        return 0.5
    if invert:
        s = -s
        value = -value
    n = len(s)
    if n == 1:
        return 1.0
    rank = int((s < value).sum()) + 1
    return (rank - 1) / (n - 1)


def _build_radar(group_df: pd.DataFrame, ticker: str, group_name: str) -> go.Figure:
    """Scatterpolar comparing ``ticker`` against the peer average."""
    peer_vals: list[float] = []
    company_vals: list[float] = []
    labels: list[str] = []
    crow = group_df[group_df["ticker"] == ticker]
    crow = crow.iloc[0] if not crow.empty else None

    for _key, label, col, invert in RADAR_AXES:
        labels.append(label)
        col_series = group_df[col]
        peer_vals.append(_percentile_rank(col_series, col_series.mean(skipna=True), invert=invert))
        if crow is not None:
            company_vals.append(_percentile_rank(col_series, crow[col], invert=invert))
        else:
            company_vals.append(0.5)

    labels_c = [*labels, labels[0]]
    peer_vals_c = [*peer_vals, peer_vals[0]]
    company_vals_c = [*company_vals, company_vals[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=company_vals_c,
            theta=labels_c,
            fill="toself",
            name=ticker,
            line=dict(color=CHART_GOLD, width=2.4),
            fillcolor="rgba(201,162,39,0.18)",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=peer_vals_c,
            theta=labels_c,
            fill=None,
            name="Peer Average",
            line=dict(color=COLORS["text_mute"], width=1.8, dash="dash"),
        )
    )
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                visible=True,
                range=[0, 1],
                tickvals=[0.25, 0.50, 0.75, 1.00],
                ticktext=["25", "50", "75", "100"],
                gridcolor=COLORS["border"],
                linecolor=COLORS["border"],
                tickfont=dict(size=10, color=COLORS["text_mute"]),
            ),
            angularaxis=dict(
                tickfont=dict(size=11, color=COLORS["text"]),
                gridcolor=COLORS["border"],
                linecolor=COLORS["border"],
            ),
        ),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.08, xanchor="center", x=0.5),
        margin=dict(l=40, r=40, t=30, b=40),
        height=520,
        title=dict(text=f"{ticker} vs {group_name} Peer Average (percentile)", x=0),
    )
    return fig


def _kpi_table(group_df: pd.DataFrame) -> None:
    """KPI table with benchmark row highlighted in gold."""
    display = group_df[
        [
            "ticker",
            "company_name",
            "is_benchmark",
            "roe_pct",
            "roce_pct",
            "npm_pct",
            "de",
            "icr",
            "fcf_cr",
            "rev_cagr_5yr",
            "pat_cagr_5yr",
            "composite",
            "pe_ratio",
            "pb_ratio",
            "div_yield_pct",
        ]
    ].copy()
    display.columns = [
        "Ticker",
        "Company",
        "Bmk",
        "ROE",
        "ROCE",
        "NPM",
        "D/E",
        "ICR",
        "FCF",
        "Rev CAGR",
        "PAT CAGR",
        "Composite",
        "P/E",
        "P/B",
        "Div Yield",
    ]
    display["Bmk"] = display["Bmk"].map(lambda v: "B" if v == 1 else "")

    def _highlight_bench(row: pd.Series) -> list[str]:
        if row["Bmk"] == "B":
            style = (
                f"background-color: rgba(201,162,39,0.18); " f"border-left: 3px solid {CHART_GOLD};"
            )
        else:
            style = ""
        return [style] * len(row)

    styled = display.style.apply(_highlight_bench, axis=1)
    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
        height=420,
        column_config={
            "Ticker": text_col("Ticker"),
            "Company": text_col("Company"),
            "Bmk": st.column_config.TextColumn("Bmk", width="small"),
            "ROE": percent_col("ROE"),
            "ROCE": percent_col("ROCE"),
            "NPM": percent_col("NPM"),
            "D/E": number_col("D/E", digits=2),
            "ICR": number_col("ICR", digits=2),
            "FCF": number_col("FCF", digits=0),
            "Rev CAGR": percent_col("Rev CAGR"),
            "PAT CAGR": percent_col("PAT CAGR"),
            "Composite": number_col("Composite", digits=1),
            "P/E": ratio_col("P/E"),
            "P/B": ratio_col("P/B", digits=1),
            "Div Yield": percent_col("Div Yield"),
        },
    )
    st.caption("Gold-highlighted row denotes peer-group benchmark (B).")


def render() -> None:
    """Render the Peer Comparison page."""
    page_header("Peer Comparison", "Radar analytics and KPI benchmarking by peer group.")

    groups = get_peer_groups()
    group_name = st.selectbox(
        "Peer Group",
        options=groups["peer_group_name"].tolist(),
        index=(
            groups["peer_group_name"].tolist().index("IT Services")
            if "IT Services" in groups["peer_group_name"].tolist()
            else 0
        ),
    )

    group_df = get_peers(group_name)
    if group_df.empty:
        st.warning(f"No members found for peer group '{group_name}'.")
        app_stamp()
        return

    tickers = group_df["ticker"].tolist()
    benchmark_row = group_df[group_df["is_benchmark"] == 1]
    default_ticker = benchmark_row["ticker"].iloc[0] if not benchmark_row.empty else tickers[0]

    col_left, col_right = st.columns([1, 1])
    with col_left:
        ticker = st.selectbox("Company", tickers, index=tickers.index(default_ticker))
    with col_right:
        st.metric("Group Members", f"{len(group_df)}")

    plotly_chart(_build_radar(group_df, ticker, group_name), height=520)

    section_label(f"{group_name} - KPI Table")
    _kpi_table(group_df)

    app_stamp()
