"""Screen 03 - Screener (placeholder, Day 22 scaffold)."""

from __future__ import annotations

import streamlit as st

from src.dashboard.utils.db import get_latest_ratios

PRESETS = [
    "Quality Compounder",
    "Value Pick",
    "Growth Accelerator",
    "Dividend Champion",
    "Debt-Free Blue Chip",
    "Turnaround Watch",
]


def render() -> None:
    """Render the Screener page shell."""
    st.title("🔍 Screener")
    st.caption("Preset + custom stock screening (filters & CSV export coming Day 26)")

    preset = st.selectbox("Preset", PRESETS, index=0)
    st.write(f"Selected preset: **{preset}**")

    df = get_latest_ratios()
    st.write(f"Universe loaded: **{len(df)}** latest-year companies.")
    st.dataframe(
        df[["company_id", "company_name", "broad_sector", "composite_quality_score"]]
        .sort_values("composite_quality_score", ascending=False)
        .head(20),
        hide_index=True,
        use_container_width=True,
    )

    st.info(
        "Preset filters, custom sliders, threshold-coloured tables and "
        "CSV download buttons will be wired in on Day 26."
    )
