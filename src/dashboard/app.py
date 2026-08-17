"""
Nifty 100 Financial Intelligence Platform - Streamlit Dashboard.

NOTE: This is a scaffold file for Sprint 3 (Dashboard).
The full interactive dashboard will be implemented in a later sprint.
Running `make run-dashboard` will launch this placeholder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure project root is importable when launched via `streamlit run`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def main() -> None:
    """Render the placeholder dashboard page."""
    logger.info("Dashboard launched (placeholder)")

    st.set_page_config(
        page_title="Nifty 100 Financial Intelligence Platform",
        page_icon="📈",
        layout="wide",
    )

    st.title("📈 Nifty 100 Financial Intelligence Platform")
    st.caption("Sprint 1 - Environment Setup complete. Dashboard coming in Sprint 3.")

    st.info(
        "The Streamlit dashboard will be implemented in Sprint 3. "
        "It will include interactive Plotly charts, sector analysis, "
        "stock screening, and drill-down views into Nifty 100 constituents."
    )

    st.subheader("Project Status")
    st.markdown("""
        - [x] **Sprint 1 - Day 1:** Environment Setup, tooling, logging, config
        - [ ] **Sprint 1 - Day 2:** ETL pipelines, SQLite schema, data loading
        - [ ] **Sprint 2:** Analytics engine
        - [ ] **Sprint 3:** Interactive dashboard (you are here)
        - [ ] **Sprint 4:** FastAPI REST API
        - [ ] **Sprint 5:** ML / NLP / Reporting
        """)


if __name__ == "__main__":
    main()
