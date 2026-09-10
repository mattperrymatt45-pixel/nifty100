"""Screen 01 - Home / Overview."""

from __future__ import annotations

import streamlit as st

from src.dashboard.utils.db import get_companies, get_latest_ratios, get_peer_groups


def render() -> None:
    """Render the Home landing page."""
    st.title("📈 Nifty 100 Financial Intelligence Platform")
    st.caption("Sprint 4 · Live dashboard on top of the Screener.in warehouse")

    companies = get_companies()
    ratios = get_latest_ratios()
    peer_groups = get_peer_groups()

    # ---- KPI tiles ---------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies tracked", f"{len(companies)}")
    c2.metric(
        "Sectors",
        f"{companies['broad_sector'].nunique()}",
    )
    c3.metric(
        "Peer groups",
        f"{len(peer_groups)}",
    )
    latest_year = ratios["year"].iloc[0] if not ratios.empty else "n/a"
    c4.metric("Latest FY", latest_year)

    st.divider()

    # ---- Body --------------------------------------------------------------
    left, right = st.columns([2, 1])
    with left:
        st.subheader("What you can do here")
        st.markdown("""
            - **🏢 Company Profile** - drill into any of the 92 tickers:
              KPI snapshot, P&L/BS/CF history, composite score.
            - **🔍 Screener** - run the six preset screens (Quality
              Compounder, Value Pick, Growth Accelerator, Dividend
              Champion, Debt-Free Blue Chip, Turnaround Watch) or
              custom filters. CSV export supported.
            - **👥 Peer Comparison** - explore percentile ranks within
              each of the 11 peer groups.
            - **📈 Trends** - multi-year KPI line charts.
            - **🏭 Sectors** - sector-level aggregates and ROCE
              heatmaps.
            - **💰 Capital Allocation** - CFO/CFI/CFF pattern
              classification and free cash flow.
            - **📄 Reports** - download the generated Excel and PNG
              artifacts (screener_output.xlsx, peer_comparison.xlsx,
              radar charts).
            """)

    with right:
        st.subheader("Peer groups")
        st.dataframe(
            peer_groups[["peer_group_name", "member_count", "benchmark_count"]],
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("All constituents")
    st.dataframe(
        companies[["ticker", "company_name", "broad_sector", "sub_sector", "market_cap_category"]],
        hide_index=True,
        use_container_width=True,
    )
