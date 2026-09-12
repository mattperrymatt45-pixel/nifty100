"""Screen 04 - Peer Comparison (Day 24).

Peer group dropdown, Scatterpolar radar chart for selected company vs
peer average, and a side-by-side KPI table that highlights the
benchmark row.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.utils.db import get_peer_groups, get_peers

RADAR_AXES = [
    ("roe", "ROE", "roe_pct", False),
    ("roce", "ROCE", "roce_pct", False),
    ("npm", "NPM", "npm_pct", False),
    ("de", "D/E (inv)", "de", True),  # inverted: lower D/E = better
    ("cfo_pat", "CFO/PAT", "cfo_pat", False),
    ("pat_cagr_5yr", "PAT CAGR 5y", "pat_cagr_5yr", False),
    ("rev_cagr_5yr", "Rev CAGR 5y", "rev_cagr_5yr", False),
    ("composite", "Composite", "composite", False),
]


def _percentile_rank(series: pd.Series, value: float, invert: bool = False) -> float:
    """SQL-style PERCENT_RANK (rank-1)/(n-1) with min tie handling.

    ``invert=True`` uses ascending rank on the inverted scale so lower raw
    values map to higher percentiles (used for D/E). NaN values return 0.5
    (neutral midpoint) so missing data doesn't dominate the radar.
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
    rank = int((s < value).sum()) + 1  # 1-based rank (method=min)
    return (rank - 1) / (n - 1)


def _build_radar(group_df: pd.DataFrame, ticker: str) -> go.Figure:
    """Build a Scatterpolar figure comparing ``ticker`` against peer average."""
    peer_vals: list[float] = []
    company_vals: list[float] = []
    labels: list[str] = []
    crow = group_df[group_df["ticker"] == ticker]
    crow = crow.iloc[0] if not crow.empty else None

    for _key, label, col, invert in RADAR_AXES:
        labels.append(label)
        col_series = group_df[col]
        peer_pct = _percentile_rank(col_series, col_series.mean(skipna=True), invert=invert)
        peer_vals.append(peer_pct)
        if crow is not None:
            company_pct = _percentile_rank(col_series, crow[col], invert=invert)
        else:
            company_pct = 0.5
        company_vals.append(company_pct)

    # Close the polygon
    labels_c = [*labels, labels[0]]
    peer_vals_c = [*peer_vals, peer_vals[0]]
    company_vals_c = [*company_vals, company_vals[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=company_vals_c,
            theta=labels_c,
            fill="toself",
            name=f"{ticker}",
            line=dict(color="#1F77B4", width=2.5),
            fillcolor="rgba(31,119,180,0.22)",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=peer_vals_c,
            theta=labels_c,
            fill=None,
            name="Peer Average",
            line=dict(color="#FF4B4B", width=2, dash="dash"),
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 1],
                tickvals=[0.25, 0.5, 0.75, 1.0],
                ticktext=["25%", "50%", "75%", "100%"],
            ),
            angularaxis=dict(tickfont=dict(size=11)),
        ),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.12, xanchor="center", x=0.5),
        margin=dict(l=40, r=40, t=40, b=40),
        height=520,
        title=f"{ticker} vs {group_df.attrs.get('group_name', '')} peer avg (percentile scale)",
    )
    return fig


def _kpi_table(group_df: pd.DataFrame) -> None:
    """Render KPI table with benchmark row highlighted."""
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
        "Bench",
        "ROE %",
        "ROCE %",
        "NPM %",
        "D/E",
        "ICR",
        "FCF (Cr)",
        "Rev CAGR 5y",
        "PAT CAGR 5y",
        "Composite",
        "P/E",
        "P/B",
        "Div Yield %",
    ]
    for c in [
        "ROE %",
        "ROCE %",
        "NPM %",
        "D/E",
        "ICR",
        "FCF (Cr)",
        "Rev CAGR 5y",
        "PAT CAGR 5y",
        "Composite",
        "P/E",
        "P/B",
        "Div Yield %",
    ]:
        display[c] = display[c].map(lambda v: round(float(v), 1) if pd.notna(v) else "")
    display["Bench"] = display["Bench"].map(lambda v: "★" if v == 1 else "")

    def _highlight_bench(row: pd.Series) -> list[str]:
        is_bench = row["Bench"] == "★"
        style = "background-color: #FFD966; font-weight: bold;" if is_bench else ""
        return [style] * len(row)

    styled = display.style.apply(_highlight_bench, axis=1)
    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
        height=420,
    )


def render() -> None:
    """Render the Peer Comparison page."""
    st.title("Peer Comparison")
    st.caption("Radar chart + percentile heatmap by peer group")

    groups = get_peer_groups()
    group_name = st.selectbox(
        "Peer group",
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
        return
    group_df.attrs["group_name"] = group_name

    tickers = group_df["ticker"].tolist()
    benchmark_row = group_df[group_df["is_benchmark"] == 1]
    default_ticker = benchmark_row["ticker"].iloc[0] if not benchmark_row.empty else tickers[0]

    col_left, col_right = st.columns([1, 1])
    with col_left:
        ticker = st.selectbox("Select company", tickers, index=tickers.index(default_ticker))
    with col_right:
        st.metric("Group members", len(group_df))

    st.plotly_chart(_build_radar(group_df, ticker), use_container_width=True)

    st.subheader(f"{group_name} - KPI table")
    st.caption("★ = peer-group benchmark. Gold-highlighted row = benchmark.")
    _kpi_table(group_df)
