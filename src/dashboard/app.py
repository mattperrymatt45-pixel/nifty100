"""Nifty 100 Financial Intelligence Platform - Streamlit Dashboard.

Sprint 4 (Days 22-28): 8-screen institutional-grade analytics dashboard
on top of the production SQLite warehouse.

Run with::

    streamlit run src/dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable when launched via ``streamlit run``
# from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

# ---------------------------------------------------------------------------
# Page config must be the first Streamlit command executed.
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Nifty 100 Terminal",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Theme applied before any rendering so CSS applies to all elements below.
# ---------------------------------------------------------------------------
from src.dashboard.utils.theme import apply_theme  # noqa: E402

apply_theme()

# ---------------------------------------------------------------------------
# Sidebar navigation - explicit imports keep the page registry decoupled
# from the numeric-prefixed module names in ``pages/``.
# ---------------------------------------------------------------------------
from src.dashboard.pages import (  # noqa: E402
    capital,
    home,
    peers,
    profile,
    reports,
    screener,
    sectors,
    trends,
)
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

PAGES: dict[str, tuple[str, object]] = {
    "Overview": ("Market dashboard and constituent KPIs", home),
    "Company Profile": ("Single-name fundamental drill-down", profile),
    "Screener": ("Preset and custom stock screening", screener),
    "Peer Comparison": ("Peer-group percentiles and radar analytics", peers),
    "Trends": ("Multi-year KPI trends", trends),
    "Sectors": ("Sector-level analytics", sectors),
    "Capital Allocation": ("Cash-flow pattern classification", capital),
    "Reports": ("Annual reports and downloadable artifacts", reports),
}


def _render_sidebar() -> str:
    """Render the navigation sidebar and return the selected page key."""
    with st.sidebar:
        st.markdown(
            "<div class='sidebar-brand'>"
            "<div class='brand-name'>NIFTY 100</div>"
            "<div class='brand-sub'>Financial Terminal</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            "<div class='section-label' style='margin-top:0.6rem'>Navigation</div>",
            unsafe_allow_html=True,
        )
        selection = st.radio(
            "Navigation",
            options=list(PAGES.keys()),
            index=0,
            label_visibility="collapsed",
        )
        st.caption(PAGES[selection][0])

    return selection


def main() -> None:
    """Dispatch to the selected page's ``render()`` function."""
    logger.info("Dashboard launched")
    selection = _render_sidebar()
    _label, module = PAGES[selection]
    module.render()


if __name__ == "__main__":
    main()
