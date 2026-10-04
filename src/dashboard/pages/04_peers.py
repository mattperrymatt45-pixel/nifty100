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
    page_header,
    plotly_chart,
    section_label,
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


def _fmt(v: object, pct: bool = False, ratio: bool = False, digits: int = 1) -> str:
    """Format a numeric value as a string with thousand separators.

    Used when rendering tables through a Pandas Styler (which is
    incompatible with Streamlit column_config number formatting).
    """
    if v is None or pd.isna(v):
        return "-"
    n = float(v)
    if pct:
        return f"{n:,.{digits}f}%"
    if ratio:
        return f"{n:,.{digits}f}x"
    return f"{n:,.{digits}f}"


def _kpi_table(group_df: pd.DataFrame) -> None:
    """KPI table with benchmark row highlighted in gold.

    We pre-format numeric columns as strings and apply the gold highlight
    via Pandas Styler.  Styler and ``column_config`` cannot coexist in
    Streamlit, so all formatting (commas, percent signs, 'x' multiples)
    is done here instead of through ``column_config``.
    """
    cols = [
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
    d = group_df[cols].copy()

    # Pre-format every numeric column
    d["ticker"] = d["ticker"].astype(str)
    d["company_name"] = d["company_name"].astype(str)
    d["is_benchmark"] = d["is_benchmark"].map(lambda v: "B" if v == 1 else "")
    d["roe_pct"] = d["roe_pct"].map(lambda v: _fmt(v, pct=True, digits=2))
    d["roce_pct"] = d["roce_pct"].map(lambda v: _fmt(v, pct=True, digits=2))
    d["npm_pct"] = d["npm_pct"].map(lambda v: _fmt(v, pct=True, digits=2))
    d["de"] = d["de"].map(lambda v: _fmt(v, digits=2))
    d["icr"] = d["icr"].map(lambda v: _fmt(v, digits=2))
    d["fcf_cr"] = d["fcf_cr"].map(lambda v: _fmt(v, digits=0))
    d["rev_cagr_5yr"] = d["rev_cagr_5yr"].map(lambda v: _fmt(v, pct=True, digits=2))
    d["pat_cagr_5yr"] = d["pat_cagr_5yr"].map(lambda v: _fmt(v, pct=True, digits=2))
    d["composite"] = d["composite"].map(lambda v: _fmt(v, digits=1))
    d["pe_ratio"] = d["pe_ratio"].map(lambda v: _fmt(v, ratio=True, digits=2))
    d["pb_ratio"] = d["pb_ratio"].map(lambda v: _fmt(v, ratio=True, digits=2))
    d["div_yield_pct"] = d["div_yield_pct"].map(lambda v: _fmt(v, pct=True, digits=2))

    d.columns = [
        "Ticker",
        "Company",
        "Bmk",
        "ROE",
        "ROCE",
        "NPM",
        "D/E",
        "ICR",
        "FCF (Cr)",
        "Rev CAGR",
        "PAT CAGR",
        "Composite",
        "P/E",
        "P/B",
        "Div Yield",
    ]

    gold_bg = f"background-color: rgba(201,162,39,0.18); " f"border-left: 3px solid {CHART_GOLD};"

    def _highlight_bench(row: pd.Series) -> list[str]:
        style = gold_bg if row["Bmk"] == "B" else ""
        return [style] * len(row)

    styled = d.style.apply(_highlight_bench, axis=1)

    # Right-align all numeric columns (after Ticker/Company/Bmk)
    right_cols = list(d.columns[3:])
    styled = styled.set_properties(
        subset=right_cols,
        **{"text-align": "right", "font-variant-numeric": "tabular-nums"},
    )

    st.dataframe(styled, hide_index=True, use_container_width=True, height=420)
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
