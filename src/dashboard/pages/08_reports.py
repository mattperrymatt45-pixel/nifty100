"""Screen 08 - Reports and Documents.

Annual-report URL check, plus download buttons for project-generated
Excel artifacts.
"""

from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

from src.dashboard.utils.db import get_companies, get_documents
from src.dashboard.utils.theme import (
    CHART_GREEN,
    CHART_RED,
    COLORS,
    app_stamp,
    page_header,
    section_label,
)


@st.cache_data(ttl=1800)
def _check_url(url: str, timeout: int = 2) -> tuple[bool, str]:
    """Return (reachable, status-text) for the given URL with a 2s timeout."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return False, "invalid URL"
    if "/missing/" in url or url.endswith("missing"):
        return False, "archival link missing"
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            return 200 <= code < 400, f"HTTP {code}"
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError, ValueError):
        return False, "unreachable"


def _select_ticker(companies: pd.DataFrame) -> str:
    labels = [f"{r['ticker']} - {r['company_name']}" for _, r in companies.iterrows()]
    label_to_ticker = {
        f"{r['ticker']} - {r['company_name']}": r["ticker"] for _, r in companies.iterrows()
    }
    default_idx = next((i for i, lab in enumerate(labels) if lab.startswith("TCS - ")), 0)
    sel = st.selectbox("Company", labels, index=default_idx, key="reports_ticker")
    return label_to_ticker[sel]


def _render_report_rows(docs: pd.DataFrame) -> None:
    """Render a table of [year | link | status] for each document row."""
    for _i, row in docs.iterrows():
        year = int(row["year"])
        url = row["url"]
        c1, c2, c3 = st.columns([1, 4, 2])
        c1.markdown(f"**{year}**")
        if url and str(url).startswith("http") and "missing" not in str(url).lower():
            reachable, status = _check_url(str(url))
            if reachable:
                c2.markdown(
                    f"<a href='{url}' target='_blank' style='color:{COLORS['blue']}'>"
                    f"Open {year} Annual Report (PDF)</a>",
                    unsafe_allow_html=True,
                )
                c3.markdown(
                    f"<span style='color:{CHART_GREEN};font-size:0.8rem'>"
                    f"Available ({status})</span>",
                    unsafe_allow_html=True,
                )
            else:
                c2.markdown(
                    f"<span style='color:{COLORS['text_mute']}'>Report unavailable</span>",
                    unsafe_allow_html=True,
                )
                c3.markdown(
                    f"<span style='color:{CHART_RED};font-size:0.8rem'>{status}</span>",
                    unsafe_allow_html=True,
                )
        else:
            c2.markdown(
                f"<span style='color:{COLORS['text_mute']}'>Report unavailable</span>",
                unsafe_allow_html=True,
            )
            c3.caption("No source URL")


def _project_reports_section() -> None:
    """Static download buttons for project-generated Excel artifacts."""
    section_label("Project Artifacts")
    root = Path(__file__).resolve().parents[3]
    artifacts = [
        ("Screener Output", root / "output" / "screener_output.xlsx", "xlsx"),
        ("Peer Comparison", root / "output" / "peer_comparison.xlsx", "xlsx"),
        ("Valuation Summary", root / "output" / "valuation_summary.xlsx", "xlsx"),
        ("Capital Allocation", root / "output" / "capital_allocation_report.xlsx", "xlsx"),
        ("Cashflow Intelligence", root / "output" / "cashflow_intelligence.xlsx", "xlsx"),
    ]
    for label, path, kind in artifacts:
        if path.exists():
            with open(path, "rb") as fh:
                st.download_button(
                    label=f"Download {label} (.{kind})",
                    data=fh.read(),
                    file_name=path.name,
                    mime=("application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"),
                    use_container_width=True,
                )
        else:
            st.caption(f"{label}: file not present ({path.name})")


def render() -> None:
    """Render the Reports page."""
    page_header("Reports and Documents", "Annual report archive and generated artifacts.")

    companies = get_companies()
    ticker = _select_ticker(companies)

    docs = get_documents(ticker)
    if docs.empty:
        st.warning(f"No annual-report records for {ticker}.")
    else:
        section_label(f"Annual Reports - {ticker}")
        st.caption("Links point to the BSE India annual-report archive.")
        _render_report_rows(docs)

    _project_reports_section()
    app_stamp()
