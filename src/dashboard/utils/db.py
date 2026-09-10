"""Shared database access layer for the Streamlit dashboard.

Every query function is decorated with ``@st.cache_data(ttl=600)`` so
repeated navigations within a 10-minute window reuse the same
DataFrames instead of re-hitting SQLite. Connection handles are
resolved lazily via :func:`_get_conn`, which always points at the
production database.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.utils.config import settings


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def _db_path() -> str:
    """Absolute path to the production SQLite database."""
    return str(settings.PROJECT_ROOT / "db" / "nifty100.db")


def _get_conn() -> st.connection:  # type: ignore[name-defined]
    """Return a Streamlit-managed SQLite connection (cached per script run)."""
    return st.connection(
        "nifty100",
        type="sql",
        url=f"sqlite:///{_db_path()}",
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600)
def get_companies() -> pd.DataFrame:
    """Return the full companies table joined with sector/peer metadata.

    Columns include ``id`` (ticker), ``company_name``, ``about_company``,
    ``website``, plus ``broad_sector``, ``sub_sector``, ``market_cap_category``
    from ``sectors`` and ``peer_group_name`` from ``peer_groups`` (may be NULL
    for companies without a peer assignment).
    """
    conn = _get_conn()
    query = """
        SELECT
            c.id                                 AS ticker,
            c.company_name,
            c.about_company,
            c.website,
            c.company_logo,
            c.chart_link,
            c.roce_percentage                    AS roce_display_pct,
            c.roe_percentage                     AS roe_display_pct,
            s.broad_sector,
            s.sub_sector,
            s.market_cap_category,
            s.index_weight_pct,
            pg.peer_group_name,
            pg.is_benchmark
        FROM companies c
        LEFT JOIN sectors       s  ON s.company_id  = c.id
        LEFT JOIN peer_groups   pg ON pg.company_id = c.id
        ORDER BY c.company_name
    """
    return conn.query(query, ttl=600)


@st.cache_data(ttl=600)
def get_ratios(ticker: str, year: str | None = None) -> pd.DataFrame:
    """Return financial ratios rows for ``ticker`` (optionally one year).

    When ``year`` is None the full time series is returned, most-recent first.
    """
    if year:
        query = """
            SELECT * FROM financial_ratios
            WHERE company_id = :ticker AND year = :year
            ORDER BY year DESC
        """
        return _get_conn().query(query, params={"ticker": ticker, "year": year}, ttl=600)
    query = """
        SELECT * FROM financial_ratios
        WHERE company_id = :ticker
        ORDER BY year DESC
    """
    return _get_conn().query(query, params={"ticker": ticker}, ttl=600)


@st.cache_data(ttl=600)
def get_latest_ratios() -> pd.DataFrame:
    """Return one row per company for the most-recent fiscal year."""
    query = """
        SELECT fr.*, c.company_name, s.broad_sector, s.sub_sector,
               s.market_cap_category, pg.peer_group_name,
               mc.market_cap_crore, mc.pe_ratio, mc.pb_ratio,
               mc.ev_ebitda, mc.dividend_yield_pct
        FROM financial_ratios fr
        JOIN companies c ON c.id = fr.company_id
        LEFT JOIN sectors s ON s.company_id = fr.company_id
        LEFT JOIN peer_groups pg ON pg.company_id = fr.company_id
        LEFT JOIN market_cap mc ON mc.company_id = fr.company_id
           AND mc.year = CAST(SUBSTR(fr.year, 1, 4) AS INTEGER)
        WHERE fr.year = (SELECT MAX(year) FROM financial_ratios)
        ORDER BY fr.company_id
    """
    return _get_conn().query(query, ttl=600)


@st.cache_data(ttl=600)
def get_pl(ticker: str) -> pd.DataFrame:
    """Return the profit-and-loss history for ``ticker``, most-recent first."""
    query = """
        SELECT * FROM profitandloss
        WHERE company_id = :ticker
        ORDER BY year DESC
    """
    return _get_conn().query(query, params={"ticker": ticker}, ttl=600)


@st.cache_data(ttl=600)
def get_bs(ticker: str) -> pd.DataFrame:
    """Return the balance-sheet history for ``ticker``, most-recent first."""
    query = """
        SELECT * FROM balancesheet
        WHERE company_id = :ticker
        ORDER BY year DESC
    """
    return _get_conn().query(query, params={"ticker": ticker}, ttl=600)


@st.cache_data(ttl=600)
def get_cf(ticker: str) -> pd.DataFrame:
    """Return the cash-flow history for ``ticker``, most-recent first."""
    query = """
        SELECT * FROM cashflow
        WHERE company_id = :ticker
        ORDER BY year DESC
    """
    return _get_conn().query(query, params={"ticker": ticker}, ttl=600)


@st.cache_data(ttl=600)
def get_sectors() -> pd.DataFrame:
    """Return every company joined to its sector classification."""
    query = """
        SELECT s.company_id AS ticker, c.company_name,
               s.broad_sector, s.sub_sector, s.market_cap_category,
               s.index_weight_pct
        FROM sectors s
        JOIN companies c ON c.id = s.company_id
        ORDER BY s.broad_sector, c.company_name
    """
    return _get_conn().query(query, ttl=600)


@st.cache_data(ttl=600)
def get_peer_groups() -> pd.DataFrame:
    """Return the list of peer groups with member counts + benchmark flags."""
    query = """
        SELECT pg.peer_group_name,
               COUNT(*)                                  AS member_count,
               SUM(CASE WHEN pg.is_benchmark = 1 THEN 1 ELSE 0 END) AS benchmark_count,
               GROUP_CONCAT(pg.company_id)              AS members
        FROM peer_groups pg
        GROUP BY pg.peer_group_name
        ORDER BY pg.peer_group_name
    """
    return _get_conn().query(query, ttl=600)


@st.cache_data(ttl=600)
def get_peers(group_name: str) -> pd.DataFrame:
    """Return all members of a peer group with latest-year ratios and percentiles."""
    query = """
        SELECT pg.company_id                              AS ticker,
               c.company_name,
               pg.is_benchmark,
               fr.year,
               fr.return_on_equity_pct                    AS roe_pct,
               fr.roce_pct                                AS roce_pct,
               fr.net_profit_margin_pct                   AS npm_pct,
               fr.debt_to_equity                          AS de,
               fr.interest_coverage                       AS icr,
               fr.free_cash_flow_cr                       AS fcf_cr,
               fr.cfo_pat_ratio                           AS cfo_pat,
               fr.revenue_cagr_5yr                        AS rev_cagr_5yr,
               fr.pat_cagr_5yr                            AS pat_cagr_5yr,
               fr.eps_cagr_5yr                            AS eps_cagr_5yr,
               fr.composite_quality_score                 AS composite,
               mc.pe_ratio,
               mc.pb_ratio,
               mc.dividend_yield_pct,
               mc.market_cap_crore
        FROM peer_groups pg
        JOIN companies c ON c.id = pg.company_id
        LEFT JOIN financial_ratios fr
            ON fr.company_id = pg.company_id
           AND fr.year = (SELECT MAX(year) FROM financial_ratios)
        LEFT JOIN market_cap mc
            ON mc.company_id = pg.company_id
           AND mc.year = CAST(SUBSTR(fr.year, 1, 4) AS INTEGER)
        WHERE pg.peer_group_name = :group_name
        ORDER BY fr.composite_quality_score DESC NULLS LAST
    """
    return _get_conn().query(query, params={"group_name": group_name}, ttl=600)


@st.cache_data(ttl=600)
def get_peer_percentiles(group_name: str, year: str | None = None) -> pd.DataFrame:
    """Return percentile-rank rows for one peer group."""
    if year is None:
        query = """
            SELECT * FROM peer_percentiles
            WHERE peer_group_name = :group_name
            ORDER BY metric, percentile_rank DESC
        """
        return _get_conn().query(query, params={"group_name": group_name}, ttl=600)
    query = """
        SELECT * FROM peer_percentiles
        WHERE peer_group_name = :group_name AND year = :year
        ORDER BY metric, percentile_rank DESC
    """
    return _get_conn().query(query, params={"group_name": group_name, "year": year}, ttl=600)


@st.cache_data(ttl=600)
def get_valuation(ticker: str) -> pd.DataFrame:
    """Return market-cap/valuation history for ``ticker`` joined to FCF."""
    query = """
        SELECT mc.year,
               mc.market_cap_crore,
               mc.enterprise_value_crore,
               mc.pe_ratio,
               mc.pb_ratio,
               mc.ev_ebitda,
               mc.dividend_yield_pct,
               fr.free_cash_flow_cr,
               fr.return_on_equity_pct AS roe_pct,
               fr.earnings_per_share   AS eps,
               CASE WHEN mc.market_cap_crore > 0
                    THEN fr.free_cash_flow_cr * 100.0 / mc.market_cap_crore
                    ELSE NULL END      AS fcf_yield_pct
        FROM market_cap mc
        LEFT JOIN financial_ratios fr
            ON fr.company_id = mc.company_id
           AND CAST(SUBSTR(fr.year, 1, 4) AS INTEGER) = mc.year
        WHERE mc.company_id = :ticker
        ORDER BY mc.year DESC
    """
    return _get_conn().query(query, params={"ticker": ticker}, ttl=600)


@st.cache_data(ttl=600)
def run_sql(query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Escape hatch - run arbitrary read-only SQL (used by the Trends screen)."""
    return _get_conn().query(query, params=params or {}, ttl=600)


def invalidate_cache() -> None:
    """Clear all cached query results (used after a DB refresh).

    Defensive wrapper: under test/unit scenarios ``st.cache_data`` may be
    monkey-patched into a plain decorator without the ``.clear()`` method;
    in that case we silently no-op so the call is always safe.
    """
    clear = getattr(st.cache_data, "clear", None)
    if callable(clear):
        clear()
