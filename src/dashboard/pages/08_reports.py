"""Screen 08 - Annual Reports / Downloadable Reports (Day 25).

Search a company, list available annual-report years with clickable
BSE PDF links. A lightweight URL check marks 404s with a red "Report
unavailable" badge.
"""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

from src.dashboard.utils.db import get_companies, get_documents


@st.cache_data(ttl=1800)
def _check_url(url: str, timeout: int = 4) -> tuple[bool, str]:
    """Return (reachable, status-text) for the given URL.

    Checks for known bad substrings first (``missing`` paths, empty values),
    then attempts a lightweight HEAD request with a short timeout. Network
    failures or non-2xx/3xx responses return False so the UI can show the
    red unavailable badge quickly.
    """
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
        return False, "network unreachable"


def _select_ticker(companies: pd.DataFrame) -> str:
    labels = [f"{r['ticker']} - {r['company_name']}" for _, r in companies.iterrows()]
    label_to_ticker = {
        f"{r['ticker']} - {r['company_name']}": r["ticker"] for _, r in companies.iterrows()
    }
    default_idx = next((i for i, lab in enumerate(labels) if lab.startswith("TCS - ")), 0)
    sel = st.selectbox("Company", labels, index=default_idx, key="reports_ticker")
    return label_to_ticker[sel]


def _render_report_rows(docs: pd.DataFrame) -> None:
    """Render a two-column table of [year | link/badge] for each row."""
    for _i, row in docs.iterrows():
        year = int(row["year"])
        url = row["url"]
        c1, c2, c3 = st.columns([1, 4, 2])
        c1.markdown(f"**{year}**")
        if url and str(url).startswith("http") and "missing" not in str(url).lower():
            reachable, status = _check_url(str(url))
            if reachable:
                c2.markdown(
                    f"<a href='{url}' target='_blank'>📄 Open {year} Annual Report PDF</a>",
                    unsafe_allow_html=True,
                )
                c3.caption(f"Available ({status})")
            else:
                c2.markdown(
                    "<span style='color:#721c24'>❌ Report unavailable</span>",
                    unsafe_allow_html=True,
                )
                c3.caption(f"{status}")
        else:
            c2.markdown(
                "<span style='color:#721c24'>❌ Report unavailable</span>",
                unsafe_allow_html=True,
            )
            c3.caption("No source URL")


def _project_reports_section() -> None:
    """Static links to the project-generated Excel/PNG artifacts."""
    st.divider()
    st.subheader("Project-generated reports")
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    artifacts = [
        ("Screener output", root / "output" / "screener_output.xlsx", "xlsx"),
        ("Peer comparison workbook", root / "output" / "peer_comparison.xlsx", "xlsx"),
    ]
    for label, path, kind in artifacts:
        if path.exists():
            with open(path, "rb") as fh:
                st.download_button(
                    label=f"⬇️  Download {label} (.{kind})",
                    data=fh.read(),
                    file_name=path.name,
                    mime=("application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"),
                    use_container_width=True,
                )
        else:
            st.caption(f"{label}: file not found ({path})")


def render() -> None:
    st.title("Reports & Documents")
    st.caption("Annual report PDFs from BSE, plus project-generated Excel reports.")

    companies = get_companies()
    ticker = _select_ticker(companies)

    docs = get_documents(ticker)
    if docs.empty:
        st.warning(f"No annual-report records found for {ticker}.")
    else:
        st.subheader(f"Annual Reports - {ticker}")
        st.caption(
            "Links point to the BSE India annual-report archive. A red "
            "'unavailable' badge means the URL returned HTTP 404 or is "
            "flagged as a missing link in the source data."
        )
        _render_report_rows(docs)

    _project_reports_section()
