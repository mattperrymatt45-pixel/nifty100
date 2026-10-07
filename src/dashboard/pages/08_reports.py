"""Screen 08 - Reports and Documents.

Annual-report link resolution (handling BSE's dynamic site), plus
download buttons for project-generated Excel artifacts.

BSE migrated bseindia.com to a JavaScript-driven Angular app; the legacy
direct-PDF pattern ``bseplus/AnnualReport/<TICKER>/<TICKER>_<year>.pdf`` now
returns HTTP 404 for every filing. We therefore:

1. Try the direct PDF URL first with a standard browser User-Agent and a
   ``Referer`` header (using GET with Range: bytes=0-0 so we can check
   ``Content-Type: application/pdf`` without downloading the full file).
2. If the direct link is not a valid PDF, construct and surface a
   Google-Search fallback link scoped to ``filetype:pdf`` so the user can
   locate the filing in one click, plus a link to BSE's corporate
   announcements page.
"""

from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

from src.dashboard.utils.db import get_companies, get_documents
from src.dashboard.utils.theme import (
    CHART_GOLD,
    CHART_GREEN,
    COLORS,
    app_stamp,
    page_header,
    section_label,
)

# Standard desktop-browser UA + Referer so BSE doesn't block the probe.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
}

_BROWSER_LINK_STYLE = f"color:{COLORS['blue']};text-decoration:none;"
_FALLBACK_LINK_STYLE = f"color:{CHART_GOLD};text-decoration:none;"


def _is_pdf_url(url: str, timeout: int = 4) -> tuple[bool, str]:
    """Probe ``url`` and return (is_valid_pdf, status_text).

    Uses a ranged GET (first byte only) rather than HEAD because many CDNs
    reject HEAD, and we need to confirm the response ``Content-Type`` is
    actually ``application/pdf`` -- HTML landing pages (BSE SPA 200 OK)
    would otherwise appear as valid links.
    """
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return False, "no URL"
    if "/missing/" in url or url.endswith("missing"):
        return False, "archival link missing"
    try:
        req = Request(url, headers={**_BROWSER_HEADERS, "Range": "bytes=0-0"}, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if 200 <= code < 300 and "pdf" in ctype:
                return True, f"HTTP {code} - PDF"
            if 200 <= code < 400:
                # SPA page / HTML landing - not a direct PDF
                return False, f"HTTP {code} (page, not PDF)"
            return False, f"HTTP {code}"
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError, ValueError):
        return False, "unreachable"


def _company_name(ticker: str) -> str:
    """Return a clean company name from the companies table (cached)."""
    df = get_companies()
    row = df[df["ticker"] == ticker]
    if row.empty:
        return ticker
    return str(row.iloc[0]["company_name"])


def _search_url(company_name: str, ticker: str, year: int) -> str:
    """Google-Search URL restricted to PDF annual reports for this filing."""
    q = f"{company_name} {ticker} Annual Report {year-1}-{str(year)[-2:]} BSE NSE filetype:pdf"
    return f"https://www.google.com/search?q={quote_plus(q)}"


def _bse_announcements_url(ticker: str) -> str:
    """BSE corporate-announcements landing page (stable, JS-driven, no 404)."""
    return f"https://www.bseindia.com/corporates/ann?scripcd={quote_plus(ticker)}"


def _select_ticker(companies: pd.DataFrame) -> str:
    labels = [f"{r['ticker']} - {r['company_name']}" for _, r in companies.iterrows()]
    label_to_ticker = {
        f"{r['ticker']} - {r['company_name']}": r["ticker"] for _, r in companies.iterrows()
    }
    default_idx = next((i for i, lab in enumerate(labels) if lab.startswith("TCS - ")), 0)
    sel = st.selectbox("Company", labels, index=default_idx, key="reports_ticker")
    return label_to_ticker[sel]


def _render_report_rows(docs: pd.DataFrame, ticker: str) -> None:
    """Render a table of [year | direct link or search fallback | status]."""
    name = _company_name(ticker)

    # Probe all years once and cache the per-year (direct_valid, status) pairs.
    @st.cache_data(ttl=1800, show_spinner=False)
    def _probe_all(urls: tuple[tuple[int, str], ...]) -> dict[int, tuple[bool, str]]:
        return {yr: _is_pdf_url(u) for yr, u in urls}

    urls = tuple(
        (int(r["year"]), str(r["url"]) if pd.notna(r["url"]) else "") for _, r in docs.iterrows()
    )
    statuses = _probe_all(urls)

    for _i, row in docs.iterrows():
        year = int(row["year"])
        url = str(row["url"]) if pd.notna(row["url"]) else ""
        direct_valid, status = statuses.get(year, (False, "unknown"))

        c1, c2, c3 = st.columns([1, 5, 2])
        c1.markdown(f"**{year}**")

        if direct_valid:
            c2.markdown(
                f"<a href='{url}' target='_blank' rel='noopener noreferrer' "
                f"style='{_BROWSER_LINK_STYLE}'>"
                f"Open {year} Annual Report (BSE PDF)</a>",
                unsafe_allow_html=True,
            )
            c3.markdown(
                f"<span style='color:{CHART_GREEN};font-size:0.78rem'>" f"Available</span>",
                unsafe_allow_html=True,
            )
        else:
            # Fallback: offer both a Google-search link (highest chance of
            # finding the PDF) and a BSE announcements deep link.
            search = _search_url(name, ticker, year)
            ann = _bse_announcements_url(ticker)
            c2.markdown(
                f"<div style='display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;'>"
                f"<a href='{search}' target='_blank' rel='noopener noreferrer' "
                f"style='{_FALLBACK_LINK_STYLE}'>Search Report ({year})</a>"
                f"<span style='color:{COLORS['text_dim']}'>|</span>"
                f"<a href='{ann}' target='_blank' rel='noopener noreferrer' "
                f"style='{_BROWSER_LINK_STYLE}'>BSE Announcements</a>"
                f"</div>",
                unsafe_allow_html=True,
            )
            status_label = "BSE link archived" if "404" in status or "missing" in status else status
            c3.markdown(
                f"<span style='color:{COLORS['text_mute']};font-size:0.78rem'>"
                f"{status_label}</span>",
                unsafe_allow_html=True,
            )


def _project_reports_section() -> None:
    """Download buttons for project-generated Excel / PDF artifacts."""
    section_label("Project Artifacts")
    root = Path(__file__).resolve().parents[3]
    artifacts = [
        ("Screener Output", root / "output" / "screener_output.xlsx", "xlsx"),
        ("Peer Comparison", root / "output" / "peer_comparison.xlsx", "xlsx"),
        ("Valuation Summary", root / "output" / "valuation_summary.xlsx", "xlsx"),
        ("Capital Allocation", root / "output" / "capital_allocation_report.xlsx", "xlsx"),
        ("Cashflow Intelligence", root / "output" / "cashflow_intelligence.xlsx", "xlsx"),
        ("Analyst Guide (PDF)", root / "docs" / "analyst_guide.pdf", "pdf"),
    ]
    for label, path, kind in artifacts:
        if path.exists():
            with open(path, "rb") as fh:
                st.download_button(
                    label=f"Download {label} (.{kind})",
                    data=fh.read(),
                    file_name=path.name,
                    mime=(
                        "application/pdf"
                        if kind == "pdf"
                        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                    use_container_width=True,
                )
        else:
            st.caption(f"{label}: file not present ({path.name})")


def render() -> None:
    """Render the Reports page."""
    page_header(
        "Reports and Documents",
        "Annual report archive, external filings search, and project-generated artifacts.",
    )

    companies = get_companies()
    ticker = _select_ticker(companies)

    docs = get_documents(ticker)
    if docs.empty:
        st.warning(f"No annual-report records for {ticker}.")
    else:
        section_label(f"Annual Reports - {ticker}")
        st.caption(
            "Direct BSE PDF links are shown when reachable. For years where BSE's "
            "archive has migrated (HTTP 404 / SPA redirect), use the "
            "'Search Report' link to find the filing in one click."
        )
        _render_report_rows(docs, ticker)

    _project_reports_section()
    app_stamp()
