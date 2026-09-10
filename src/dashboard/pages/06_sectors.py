"""Screen 06 - Sectors (placeholder, Day 22 scaffold)."""

from __future__ import annotations

import streamlit as st

from src.dashboard.utils.db import get_sectors


def render() -> None:
    """Render the Sectors shell."""
    st.title("🏭 Sectors")
    st.caption("Sector-level analytics (coming Day 27)")

    sectors = get_sectors()
    st.dataframe(sectors, hide_index=True, use_container_width=True)

    st.info(
        "Sector-ROCE heatmaps, median-vs-benchmark comparisons and aggregate "
        "KPI tiles will be added on Day 27."
    )
