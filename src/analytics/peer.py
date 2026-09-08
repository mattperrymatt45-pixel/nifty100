"""Peer Percentile Rankings — Sprint 3 Day 18.

Computes PERCENT_RANK for 10 key metrics within each of the 11 defined peer
groups (from ``peer_groups.xlsx`` / the ``peer_groups`` table). For every
company that is assigned to at least one peer group we emit one row per
(company, peer_group, metric, year) into the ``peer_percentiles`` SQLite
table.

Metrics ranked (spec §26 Day 18):

    1. Return on Equity        (``return_on_equity_pct``)  higher = better
    2. ROCE                    (``roce_pct``)              higher = better
    3. Net Profit Margin       (``net_profit_margin_pct``) higher = better
    4. Debt-to-Equity          (``debt_to_equity``)        *lower* = better → inverted
    5. Free Cash Flow          (``fcf_cr``)                higher = better
    6. PAT CAGR 5y             (``pat_cagr_5yr``)          higher = better
    7. Revenue CAGR 5y         (``revenue_cagr_5yr``)      higher = better
    8. EPS CAGR 5y             (``eps_cagr_5yr``)          higher = better
    9. Interest Coverage       (``interest_coverage``)     higher = better
   10. Asset Turnover          (``asset_turnover``)        higher = better

PERCENT_RANK semantics
---------------------
For *higher-is-better* metrics the percentile rank is computed with
``Series.rank(pct=True, method='average')``, i.e. the fraction of peers with
value strictly less than the company's value plus half the fraction with
equal value (standard SQL ``PERCENT_RANK`` convention with average tie
handling). A rank of 1.0 means "best in peer group"; 0.0 means "worst".

For D/E, where lower leverage is better, we invert: ``percentile_rank =
1 - rank(pct=True)`` so that the company with the lowest D/E in its peer
group scores 1.0.

Companies not assigned to any peer group receive an informational message
("No peer group assigned") rather than raising — callers can decide how to
surface that to the user. The populate function also simply skips such
companies without error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.etl.database import get_connection
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Metric registry — maps the 10 spec metrics to (db_column, higher_is_better).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PeerMetric:
    """One metric to be percentile-ranked within each peer group."""

    key: str  # short canonical metric key stored in `metric` column
    label: str  # human-friendly label for reports
    column: str  # SQL column in financial_ratios
    higher_is_better: bool = True

    def rank(self, series: pd.Series) -> pd.Series:
        """Return 0-1 SQL-style ``PERCENT_RANK``.

        Uses the standard SQL definition ``(rank - 1) / (n - 1)`` where
        ``rank`` is the 1-based row number in the ordered partition (ties
        get the *same* rank — :pandas:`rank(method='min')`). This guarantees
        the "worst" peer scores 0.0 and the "best" peer scores 1.0, with
        linear spacing in between (except where ties compress the range).

        When ``higher_is_better`` is False (D/E) the order is reversed so
        that the **lowest** value scores 1.0. NaN values remain NaN.
        """
        # Count valid peers (n in the PERCENT_RANK denominator).
        valid = series.notna()
        n = int(valid.sum())
        if n <= 1:
            # Solo peer: neutral 0.5, NaN stays NaN.
            out = pd.Series(np.nan, index=series.index, dtype=float)
            out.loc[valid] = 0.5
            return out

        # Use method='min' to match SQL's PERCENT_RANK() tie semantics.
        ascending = True  # higher-is-better → ascending rank: smallest=rank1
        r = series.rank(method="min", ascending=ascending)
        pr = (r - 1.0) / (n - 1.0)
        if not self.higher_is_better:
            pr = 1.0 - pr
        # NaNs propagate: pandas rank leaves NaN positions as NaN.
        return pr


PEER_METRICS: tuple[PeerMetric, ...] = (
    PeerMetric("roe", "Return on Equity (%)", "return_on_equity_pct"),
    PeerMetric("roce", "ROCE (%)", "roce_pct"),
    PeerMetric("npm", "Net Profit Margin (%)", "net_profit_margin_pct"),
    PeerMetric(
        "de", "Debt-to-Equity (inverted, lower=better)", "debt_to_equity", higher_is_better=False
    ),
    PeerMetric("fcf", "Free Cash Flow (Rs Cr)", "free_cash_flow_cr"),
    PeerMetric("pat_cagr_5yr", "PAT CAGR 5y (%)", "pat_cagr_5yr"),
    PeerMetric("rev_cagr_5yr", "Revenue CAGR 5y (%)", "revenue_cagr_5yr"),
    PeerMetric("eps_cagr_5yr", "EPS CAGR 5y (%)", "eps_cagr_5yr"),
    PeerMetric("icr", "Interest Coverage (x)", "interest_coverage"),
    PeerMetric("asset_turnover", "Asset Turnover (x)", "asset_turnover"),
)

NO_PEER_GROUP_MSG = "No peer group assigned"


# ---------------------------------------------------------------------------
# Schema migration for peer_percentiles table
# ---------------------------------------------------------------------------
_PEER_PERCENTILES_DDL = """
CREATE TABLE IF NOT EXISTS peer_percentiles (
    company_id       TEXT    NOT NULL,
    peer_group_name  TEXT    NOT NULL,
    metric           TEXT    NOT NULL,
    value            REAL,
    percentile_rank  REAL,
    year             TEXT    NOT NULL,
    computed_at      TEXT,
    PRIMARY KEY (company_id, peer_group_name, metric, year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, peer_group_name)
        REFERENCES peer_groups(company_id, peer_group_name) ON DELETE CASCADE
);
"""

_PEER_PERCENTILES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_pp_group_metric
    ON peer_percentiles(peer_group_name, metric, year);
"""


def ensure_schema(db_path: Path | str | None = None) -> None:
    """Create the ``peer_percentiles`` table and its index if missing.

    Idempotent — safe to call multiple times.
    """
    with get_connection(db_path) as conn:
        conn.execute(_PEER_PERCENTILES_DDL)
        conn.execute(_PEER_PERCENTILES_INDEX)


# ---------------------------------------------------------------------------
# Percentile computation
# ---------------------------------------------------------------------------
def _load_peer_dataset(
    db_path: Path | str | None = None,
    year: str | None = None,
) -> pd.DataFrame:
    """Load the wide dataset of (company_id, peer_group_name, + 10 metric cols).

    Only companies with a peer-group assignment are included; companies in
    multiple peer groups appear once per group. If ``year`` is None, the
    latest year in ``financial_ratios`` is used.
    """
    metric_cols = ", ".join(f"fr.{m.column}" for m in PEER_METRICS)
    if year is None:
        where_year = "fr.year = (SELECT MAX(year) FROM financial_ratios)"
    else:
        where_year = f"fr.year = '{year}'"

    sql = f"""
        SELECT
            fr.company_id,
            co.company_name,
            pg.peer_group_name,
            pg.is_benchmark,
            fr.year,
            {metric_cols}
        FROM financial_ratios fr
        JOIN companies co ON co.id = fr.company_id
        JOIN peer_groups pg ON pg.company_id = fr.company_id
        WHERE {where_year}
        ORDER BY pg.peer_group_name, fr.company_id
    """
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn)
    return df


def compute_peer_percentiles(
    db_path: Path | str | None = None,
    year: str | None = None,
) -> pd.DataFrame:
    """Compute peer percentiles for the given year (default: latest).

    Returns a long-form DataFrame with columns::

        company_id, company_name, peer_group_name, is_benchmark,
        year, metric, value, percentile_rank

    Companies with no peer-group assignment are NOT included in the result
    (they receive no rows). The caller may detect this case separately via
    :func:`companies_without_peer_group`.
    """
    df = _load_peer_dataset(db_path=db_path, year=year)
    if df.empty:
        logger.warning("Peer percentiles: no rows returned (no peer-group data for year?)")
        return pd.DataFrame(
            columns=[
                "company_id",
                "company_name",
                "peer_group_name",
                "is_benchmark",
                "year",
                "metric",
                "value",
                "percentile_rank",
            ]
        )

    target_year = df["year"].iloc[0]

    # Pre-allocate a long-form frame with explicit columns/dtypes to avoid
    # FutureWarnings on concat when some columns are all-NA.
    n_companies = len(df)
    n_metrics = len(PEER_METRICS)
    long_df = pd.DataFrame(
        {
            "company_id": np.tile(df["company_id"].to_numpy(), n_metrics),
            "company_name": np.tile(df["company_name"].to_numpy(), n_metrics),
            "peer_group_name": np.tile(df["peer_group_name"].to_numpy(), n_metrics),
            "is_benchmark": np.tile(df["is_benchmark"].astype(bool).to_numpy(), n_metrics),
            "year": np.tile(df["year"].to_numpy(), n_metrics),
            "metric": np.repeat([m.key for m in PEER_METRICS], n_companies),
            "value": np.nan,
            "percentile_rank": np.nan,
        }
    )

    for i, metric in enumerate(PEER_METRICS):
        col = metric.column
        start = i * n_companies
        end = start + n_companies
        # Bind the bound method outside the lambda to avoid closure-over-loop-var.
        rank_fn = metric.rank
        ranked = df.groupby("peer_group_name")[col].transform(lambda s, fn=rank_fn: fn(s))
        long_df.loc[start : end - 1, "value"] = df[col].to_numpy()
        long_df.loc[start : end - 1, "percentile_rank"] = ranked.to_numpy()

    # Clip ranks to [0, 1] defensively (floating-point tolerance). NaN values
    # (where the underlying metric is null) remain NaN and will be stored as
    # SQL NULL.
    mask = long_df["percentile_rank"].notna()
    long_df.loc[mask, "percentile_rank"] = long_df.loc[mask, "percentile_rank"].clip(0.0, 1.0)

    logger.info(
        f"Computed peer percentiles for year {target_year}: "
        f"{long_df['company_id'].nunique()} companies in "
        f"{long_df['peer_group_name'].nunique()} peer groups, "
        f"{len(PEER_METRICS)} metrics → {len(long_df)} rows"
    )
    return long_df


def companies_without_peer_group(
    db_path: Path | str | None = None,
    year: str | None = None,
) -> list[str]:
    """Return a list of company_ids present in ``financial_ratios`` for the
    given year that have no entry in ``peer_groups`` (i.e. the "No peer
    group assigned" cohort). Does NOT raise; just returns the list so
    callers can log or surface the message.
    """
    if year is None:
        sql = """
            SELECT DISTINCT fr.company_id
            FROM financial_ratios fr
            WHERE fr.year = (SELECT MAX(year) FROM financial_ratios)
              AND fr.company_id NOT IN (SELECT company_id FROM peer_groups)
            ORDER BY fr.company_id
        """
        params: dict[str, str] = {}
    else:
        sql = """
            SELECT DISTINCT fr.company_id
            FROM financial_ratios fr
            WHERE fr.year = :year
              AND fr.company_id NOT IN (SELECT company_id FROM peer_groups)
            ORDER BY fr.company_id
        """
        params = {"year": year}
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [r[0] for r in rows]


def peer_percentile_for_company(
    company_id: str,
    db_path: Path | str | None = None,
    year: str | None = None,
) -> pd.DataFrame | str:
    """Return peer-percentile rows for a single company.

    Returns either:
      - A DataFrame (columns: peer_group_name, metric, value, percentile_rank,
        year) with one row per (peer_group, metric) if the company is in at
        least one peer group.
      - The string ``"No peer group assigned"`` if the company has no peer
        group membership (no error raised, per spec).
    """
    # First check membership.
    with get_connection(db_path) as conn:
        groups = conn.execute(
            "SELECT peer_group_name FROM peer_groups WHERE company_id = ?",
            (company_id,),
        ).fetchall()
    if not groups:
        return NO_PEER_GROUP_MSG

    # Compute percentiles (across the whole universe for the year) and
    # filter to the requested company.
    full = compute_peer_percentiles(db_path=db_path, year=year)
    sub = full[full["company_id"] == company_id][
        ["peer_group_name", "metric", "value", "percentile_rank", "year"]
    ].reset_index(drop=True)
    return sub


# ---------------------------------------------------------------------------
# Populate peer_percentiles table
# ---------------------------------------------------------------------------
def populate_peer_percentiles(
    db_path: Path | str | None = None,
    year: str | None = None,
    *,
    reset: bool = False,
) -> dict[str, object]:
    """(Re)populate the ``peer_percentiles`` table for the given year.

    Args:
        db_path: Override DB path (defaults to ``settings.DB_PATH``).
        year:    Fiscal year to compute for (default = latest year).
        reset:   If True, DELETE existing rows for the target year before
                 inserting (idempotent refresh). If False, upserts via
                 INSERT OR REPLACE on the PK.

    Returns:
        Dict with summary stats: ``year``, ``rows``, ``companies``,
        ``groups``, ``metrics``, ``no_peer_group`` (list of company_ids that
        exist in the universe but lack peer-group assignment).
    """
    ensure_schema(db_path=db_path)

    long_df = compute_peer_percentiles(db_path=db_path, year=year)
    target_year = long_df["year"].iloc[0] if len(long_df) else year

    if reset and target_year is not None:
        with get_connection(db_path) as conn:
            conn.execute("DELETE FROM peer_percentiles WHERE year = ?", (target_year,))
            logger.info(f"Cleared existing peer_percentiles for year {target_year}")

    # Persist — use INSERT OR REPLACE on the (company_id, peer_group_name,
    # metric, year) primary key so re-runs are idempotent without nuking
    # history for other years.
    write_cols = [
        "company_id",
        "peer_group_name",
        "metric",
        "value",
        "percentile_rank",
        "year",
    ]
    written = 0
    if len(long_df):
        # Replace NaN with None for SQLite NULL semantics; stamp computed_at
        # client-side (SQLite does not allow datetime('utc') as a column
        # DEFAULT expression in all builds).
        now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
        persist_df = long_df[write_cols].where(pd.notna(long_df[write_cols]), None).copy()
        persist_df["computed_at"] = now
        write_cols_with_ts = [*write_cols, "computed_at"]
        with get_connection(db_path) as conn:
            cur = conn.executemany(
                f"""
                INSERT OR REPLACE INTO peer_percentiles
                    ({', '.join(write_cols_with_ts)})
                VALUES ({', '.join('?' for _ in write_cols_with_ts)})
                """,
                [
                    tuple(r)
                    for r in persist_df[write_cols_with_ts].itertuples(index=False, name=None)
                ],
            )
            written = cur.rowcount

    no_peer = companies_without_peer_group(db_path=db_path, year=target_year)
    if no_peer:
        logger.info(
            f"{len(no_peer)} companies have no peer group assigned "
            f"(skipped without error): {', '.join(no_peer[:5])}"
            + ("..." if len(no_peer) > 5 else "")
        )

    stats: dict[str, object] = {
        "year": target_year,
        "rows": written,
        "companies": int(long_df["company_id"].nunique()) if len(long_df) else 0,
        "groups": int(long_df["peer_group_name"].nunique()) if len(long_df) else 0,
        "metrics": len(PEER_METRICS),
        "no_peer_group": no_peer,
    }
    logger.info(
        f"populate_peer_percentiles: {written} rows written for year "
        f"{target_year} ({stats['companies']} companies x {stats['metrics']} metrics "
        f"across {stats['groups']} groups)"
    )
    return stats


__all__ = [
    "NO_PEER_GROUP_MSG",
    "PEER_METRICS",
    "PeerMetric",
    "companies_without_peer_group",
    "compute_peer_percentiles",
    "ensure_schema",
    "peer_percentile_for_company",
    "populate_peer_percentiles",
]
