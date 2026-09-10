"""Screen 04 - Peer Comparison (placeholder, Day 22 scaffold)."""

from __future__ import annotations

import streamlit as st

from src.dashboard.utils.db import get_peer_groups


def render() -> None:
    """Render the Peer Comparison shell."""
    st.title("👥 Peer Comparison")
    st.caption("Peer-group percentiles & heatmaps (coming Day 25)")

    groups = get_peer_groups()
    choice = st.selectbox("Peer group", groups["peer_group_name"].tolist(), index=0)
    st.write(f"Selected: **{choice}**")
    st.dataframe(groups, hide_index=True, use_container_width=True)

    st.info("Percentile heatmap and radar-chart embed will be added on Day 25.")
