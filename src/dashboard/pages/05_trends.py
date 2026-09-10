"""Screen 05 - Trends (placeholder, Day 22 scaffold)."""

from __future__ import annotations

import streamlit as st


def render() -> None:
    """Render the Trends shell."""
    st.title("📈 Trends")
    st.caption("Multi-year KPI line charts (coming Day 24)")
    st.info(
        "Select a ticker and KPI set (profitability / growth / leverage / "
        "cash-flow) to view 10-year line charts. Implemented on Day 24."
    )
