"""Screen 02 - Company Profile (placeholder, Day 22 scaffold)."""

from __future__ import annotations

import streamlit as st

from src.dashboard.utils.db import get_companies


def render() -> None:
    """Render the Company Profile selector."""
    st.title("🏢 Company Profile")
    st.caption("Per-company fundamentals drill-down (full content in later days)")

    companies = get_companies()
    tickers = companies["ticker"].tolist()
    default_idx = tickers.index("TCS") if "TCS" in tickers else 0

    ticker = st.selectbox(
        "Select company",
        options=tickers,
        index=default_idx,
        format_func=lambda t: (
            f"{t} - " f"{companies.loc[companies['ticker'] == t, 'company_name'].iloc[0]}"
        ),
    )

    row = companies.loc[companies["ticker"] == ticker].iloc[0]
    st.subheader(f"{row['company_name']} ({ticker})")
    st.write(f"**Sector:** {row['broad_sector']} / {row['sub_sector']}")
    st.write(f"**Market-cap category:** {row['market_cap_category']}")
    if row["peer_group_name"]:
        st.write(f"**Peer group:** {row['peer_group_name']}")
    else:
        st.write("**Peer group:** _No peer group assigned_")

    st.info(
        "Full KPI dashboard, P&L / balance-sheet / cash-flow tables, "
        "composite-score panel and radar chart will be added on upcoming "
        "Sprint 4 days."
    )
