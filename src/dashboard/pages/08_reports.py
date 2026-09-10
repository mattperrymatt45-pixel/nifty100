"""Screen 08 - Reports download page (placeholder, Day 22 scaffold)."""

from __future__ import annotations

import streamlit as st


def render() -> None:
    """Render the Reports shell."""
    st.title("📄 Reports")
    st.caption("Download generated Excel / PNG artifacts (coming Day 28)")
    st.info(
        "Download buttons for screener_output.xlsx, peer_comparison.xlsx, "
        "valuation_summary.xlsx and per-company radar PNGs will be wired in "
        "on Day 28."
    )
