"""Nifty 100 Financial Intelligence Platform - Streamlit Dashboard.

Sprint 4 (Days 22-28): 8-screen interactive analytics dashboard on top
of the production SQLite warehouse.

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
    page_title="Nifty 100 Analytics",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar navigation - manual routing (keeps imports explicit and lets each
# page module register its own ``render()``).
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
    "🏠 Home": ("Overview & market status", home),
    "🏢 Company Profile": ("Per-company fundamentals drill-down", profile),
    "🔍 Screener": ("Preset + custom stock screening", screener),
    "👥 Peer Comparison": ("Peer-group percentiles & heatmaps", peers),
    "📈 Trends": ("Multi-year KPI trends", trends),
    "🏭 Sectors": ("Sector-level analytics", sectors),
    "💰 Capital Allocation": ("Cash-flow pattern classification", capital),
    "📄 Reports": ("Excel/PNG report downloads", reports),
}


def _render_sidebar() -> str:
    """Render the navigation sidebar and return the selected page key."""
    with st.sidebar:
        st.title("📈 Nifty 100")
        st.caption("Financial Intelligence Platform")
        st.divider()

        st.subheader("Navigation")
        selection = st.radio(
            "Go to screen",
            options=list(PAGES.keys()),
            index=0,
            label_visibility="collapsed",
        )
        st.caption(PAGES[selection][0])

        st.divider()
        st.caption("Sprint 4 · Streamlit Dashboard")
        st.caption("Data source: `db/nifty100.db`")

    return selection


def main() -> None:
    """Dispatch to the selected page's ``render()`` function."""
    logger.info("Dashboard launched")
    selection = _render_sidebar()
    _label, module = PAGES[selection]
    module.render()


if __name__ == "__main__":
    main()
