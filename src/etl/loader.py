"""Excel file loader for the Nifty 100 ETL pipeline.

Provides two public entry points:

* :func:`load_excel` -- load a single Excel file into a normalized
  ``pandas.DataFrame`` with correct header row, stripped column names,
  and ``company_id`` / ``year`` fields normalised via
  :func:`normalize_ticker` / :func:`normalize_year`.
* :func:`load_dataset` -- convenience wrapper that looks up a dataset
  by logical name (e.g. ``"companies"``, ``"profitandloss"``) and applies
  the correct header/sheet configuration as defined in the spec (§5).

Day 2 scope is intentionally narrow: this module **only** reads Excel
files and applies field-level normalisation. Schema validation,
deduplication, DQ checks, and SQLite loading are added on subsequent
days (Days 3-7).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.etl.exceptions import LoaderError, TickerParseError
from src.etl.normalizers import YEAR_PARSE_ERROR, normalize_ticker, normalize_year_safe
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Per-dataset configuration (derived from spec §5, pages 10-14)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DatasetSpec:
    """Static metadata describing one Excel source file.

    Attributes:
        name:          Logical name used by :func:`load_dataset` (no extension).
        filename:      Actual filename under ``data/raw/``.
        sheet:         Sheet name to read. ``None`` → first sheet.
        header:        0-indexed row to use as columns. Core files use 1
                       (Row 0 = metadata, Row 1 = actual headers, per spec §5);
                       supplementary files use 0.
        normalize_id:  Which column holds the NSE ticker (normalised to
                       uppercase stripped form). ``None`` if the dataset
                       has no company_id column.
        normalize_year_col: Column holding the financial-year label
                            (normalised to ``YYYY-MM``). ``None`` for
                            snapshot tables.
        is_supplementary: True for the 5 supplementary files that ship in
                          ``data/raw/supporting datasets/`` (per spec §6).
    """

    name: str
    filename: str
    sheet: str | None = None
    header: int = 1
    normalize_id: str | None = "company_id"
    normalize_year_col: str | None = "year"
    is_supplementary: bool = False


#: Canonical registry of all 12 datasets. Order matches the spec.
DATASET_SPECS: dict[str, DatasetSpec] = {
    # --- 7 core datasets (header=1) ---
    "companies": DatasetSpec(
        name="companies",
        filename="companies.xlsx",
        sheet="Companies",
        header=1,
        normalize_id="id",  # companies uses 'id', not 'company_id'
        normalize_year_col=None,  # snapshot table
    ),
    "profitandloss": DatasetSpec(
        name="profitandloss",
        filename="profitandloss.xlsx",
        sheet="Profit & Loss",
        header=1,
        normalize_id="company_id",
        normalize_year_col="year",
    ),
    "balancesheet": DatasetSpec(
        name="balancesheet",
        filename="balancesheet.xlsx",
        sheet="Balance Sheet",
        header=1,
        normalize_id="company_id",
        normalize_year_col="year",
    ),
    "cashflow": DatasetSpec(
        name="cashflow",
        filename="cashflow.xlsx",
        sheet="Cash Flow",
        header=1,
        normalize_id="company_id",
        normalize_year_col="year",
    ),
    "analysis": DatasetSpec(
        name="analysis",
        filename="analysis.xlsx",
        sheet="Analysis",
        header=1,
        normalize_id="company_id",
        normalize_year_col=None,  # multi-period text, no single year column
    ),
    "documents": DatasetSpec(
        name="documents",
        filename="documents.xlsx",
        sheet="Documents",
        header=1,
        normalize_id="company_id",
        normalize_year_col=None,  # 'Year' is a calendar-year INT, not an FY label
    ),
    "prosandcons": DatasetSpec(
        name="prosandcons",
        filename="prosandcons.xlsx",
        sheet="Pros & Cons",
        header=1,
        normalize_id="company_id",
        normalize_year_col=None,  # snapshot text
    ),
    # --- 5 supplementary datasets (header=0) ---
    "sectors": DatasetSpec(
        name="sectors",
        filename="sectors.xlsx",
        sheet=None,
        header=0,
        normalize_id="company_id",
        normalize_year_col=None,
        is_supplementary=True,
    ),
    "stock_prices": DatasetSpec(
        name="stock_prices",
        filename="stock_prices.xlsx",
        sheet=None,
        header=0,
        normalize_id="company_id",
        normalize_year_col=None,  # date column handled separately in Day 3+
        is_supplementary=True,
    ),
    "market_cap": DatasetSpec(
        name="market_cap",
        filename="market_cap.xlsx",
        sheet=None,
        header=0,
        normalize_id="company_id",
        normalize_year_col=None,  # 'year' is calendar-year INT (2019-2024)
        is_supplementary=True,
    ),
    "financial_ratios": DatasetSpec(
        name="financial_ratios",
        filename="financial_ratios.xlsx",
        sheet=None,
        header=0,
        normalize_id="company_id",
        normalize_year_col="year",
        is_supplementary=True,
    ),
    "peer_groups": DatasetSpec(
        name="peer_groups",
        filename="peer_groups.xlsx",
        sheet=None,
        header=0,
        normalize_id="company_id",
        normalize_year_col=None,
        is_supplementary=True,
    ),
}


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def _candidate_paths(spec: DatasetSpec, raw_root: Path) -> list[Path]:
    """Return ordered list of candidate paths for ``spec`` under ``raw_root``."""
    candidates: list[Path] = []
    if spec.is_supplementary:
        # Preferred location per spec §6: data/raw/supporting datasets/<file>
        candidates.append(raw_root / "supporting datasets" / spec.filename)
        # Tolerant fallback: supplementary sitting directly in raw root
        candidates.append(raw_root / spec.filename)
    else:
        candidates.append(raw_root / spec.filename)
    return candidates


def _resolve_path(spec: DatasetSpec, data_dir: Path | str | None = None) -> Path:
    """Return the absolute path to the Excel file for ``spec``.

    Resolution rules:
      * If ``data_dir`` is ``None`` we use ``settings.RAW_DATA_DIR`` (which
        points to ``<project-root>/data/raw``).
      * If ``data_dir`` is given we accept it in two forms for convenience:
          (a) a project root that contains a ``data/raw/`` subtree;
          (b) a direct raw-data directory (e.g. a test temp dir).
        We probe both and pick the first that contains the file.
    """
    if data_dir is None:
        search_roots = [settings.RAW_DATA_DIR]
    else:
        given = Path(data_dir)
        search_roots = []
        # (a) given root → data/raw subtree (if it exists)
        dr = given / "data" / "raw"
        if dr.is_dir():
            search_roots.append(dr)
        # (b) given is itself a raw directory (or any directory)
        if given.is_dir():
            search_roots.append(given)

    # De-duplicate while preserving order
    seen: set[Path] = set()
    for root in search_roots:
        if root in seen:
            continue
        seen.add(root)
        for candidate in _candidate_paths(spec, root):
            if candidate.exists():
                return candidate

    # If nothing exists, return the preferred path for a clear error msg
    preferred = _candidate_paths(spec, search_roots[0])[0]
    return preferred


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_dataset(
    name: str,
    *,
    data_dir: Path | str | None = None,
    normalize: bool = True,
) -> pd.DataFrame:
    """Load a known dataset by logical name.

    Looks up the dataset in :data:`DATASET_SPECS` and delegates to
    :func:`load_excel`. Raises :class:`LoaderError` for unknown dataset
    names or missing files.

    Args:
        name:      Dataset key (e.g. ``"companies"``, ``"profitandloss"``).
        data_dir:  Override ``RAW_DATA_DIR`` (useful for tests).
        normalize: If True (default), run ticker/year normalisation.

    Returns:
        A cleaned pandas DataFrame.
    """
    if name not in DATASET_SPECS:
        raise LoaderError(f"Unknown dataset '{name}'. Valid names: {sorted(DATASET_SPECS)}")
    spec = DATASET_SPECS[name]
    path = _resolve_path(spec, data_dir)
    if not path.exists():
        raise LoaderError(f"Source file not found: {path}")
    return load_excel(
        path,
        sheet=spec.sheet,
        header=spec.header,
        ticker_col=spec.normalize_id if normalize else None,
        year_col=spec.normalize_year_col if normalize else None,
    )


def load_excel(
    path: Path | str,
    *,
    sheet: str | int | None = 0,
    header: int = 0,
    ticker_col: str | None = "company_id",
    year_col: str | None = "year",
) -> pd.DataFrame:
    """Read one Excel file and return a cleaned, normalised DataFrame.

    Post-load processing steps (all optional, controlled by kwargs):

    1. Column headers are stripped of surrounding whitespace.
    2. Empty rows / fully-null columns are dropped.
    3. The ticker column (if present) is normalised via
       :func:`normalize_ticker`. Rows with missing/invalid tickers are
       dropped and their count is logged.
    4. The year column (if present) is normalised via the *safe* wrapper
       of :func:`normalize_year`; unparseable cells become the sentinel
       ``"PARSE_ERROR"`` so callers can count/reject them downstream.

    Args:
        path:       Path to ``.xlsx`` file.
        sheet:      Sheet name or index. Pass ``None`` to read the first
                    sheet by default.
        header:     0-indexed header row. Core Screener.in exports use
                    ``header=1``; supplementary datasets use ``header=0``.
        ticker_col: Column holding the NSE ticker, or ``None`` to skip
                    ticker normalisation.
        year_col:   Column holding the financial-year label, or ``None``
                    to skip year normalisation.

    Returns:
        Cleaned DataFrame with normalised columns.

    Raises:
        LoaderError: If the file cannot be read.
    """
    path = Path(path)
    if not path.exists():
        raise LoaderError(f"Excel file not found: {path}")

    logger.debug(f"Loading Excel file: {path} (sheet={sheet!r}, header={header})")

    try:
        # openpyxl is the engine required by the project spec
        df = pd.read_excel(path, sheet_name=sheet, header=header, engine="openpyxl")
    except ValueError as exc:
        # Sheet name not found — fall back to the first sheet if we had
        # asked for a named sheet. Screener.in exports sometimes vary the
        # sheet name (e.g. trailing spaces, language differences).
        if isinstance(sheet, str) and "not found" in str(exc).lower():
            logger.warning(
                f"Sheet '{sheet}' not found in {path.name}; falling back to first sheet."
            )
            df = pd.read_excel(path, sheet_name=0, header=header, engine="openpyxl")
        else:
            raise LoaderError(f"Failed to read {path}: {exc}") from exc
    except Exception as exc:
        raise LoaderError(f"Failed to read {path}: {exc}") from exc

    # When a sheet name is specified and pandas returns a dict (e.g. for
    # multi-sheet reads), guard against it.
    if isinstance(df, dict):  # pragma: no cover - defensive
        if not df:
            raise LoaderError(f"No sheets found in {path}")
        df = next(iter(df.values()))

    # ---- basic hygiene ----
    # Strip column headers
    df.columns = [str(c).strip() for c in df.columns]
    # Drop rows where every value is NaN (common in trailing Excel rows)
    df = df.dropna(how="all").reset_index(drop=True)
    # Drop columns that are entirely empty (screener.in sometimes exports a
    # trailing "Unnamed: N" column)
    df = df.dropna(axis=1, how="all")

    # ---- ticker normalisation ----
    if ticker_col is not None:
        if ticker_col not in df.columns:
            raise LoaderError(
                f"Ticker column '{ticker_col}' not found in {path.name}. "
                f"Available columns: {list(df.columns)}"
            )
        df = _normalise_ticker_column(df, ticker_col, source=path.name)

    # ---- year normalisation (safe: PARSE_ERROR sentinel for failures) ----
    if year_col is not None:
        if year_col not in df.columns:
            raise LoaderError(
                f"Year column '{year_col}' not found in {path.name}. "
                f"Available columns: {list(df.columns)}"
            )
        df = _normalise_year_column(df, year_col, source=path.name)

    logger.info(f"Loaded {path.name}: {len(df)} rows x {len(df.columns)} columns")
    return df


# ---------------------------------------------------------------------------
# Column-level helpers
# ---------------------------------------------------------------------------
def _normalise_ticker_column(df: pd.DataFrame, col: str, *, source: str) -> pd.DataFrame:
    """Apply :func:`normalize_ticker` to ``col``; drop rows that fail."""
    before = len(df)
    normalised: list[str | None] = []
    dropped = 0
    for raw in df[col].tolist():
        try:
            normalised.append(normalize_ticker(raw if not pd.isna(raw) else None))
        except TickerParseError:
            normalised.append(None)
            dropped += 1

    df[col] = normalised
    if dropped:
        df = df.dropna(subset=[col]).reset_index(drop=True)
        logger.warning(
            f"{source}: dropped {dropped}/{before} rows with missing/invalid "
            f"ticker in column '{col}'"
        )
    # Ensure string dtype (pandas may infer object from mixed None/str)
    df[col] = df[col].astype(str)
    return df


def _normalise_year_column(df: pd.DataFrame, col: str, *, source: str) -> pd.DataFrame:
    """Apply :func:`normalize_year_safe` to ``col`` and log parse failures."""
    normalised = [normalize_year_safe(None if pd.isna(v) else v) for v in df[col].tolist()]
    bad = sum(1 for v in normalised if v == YEAR_PARSE_ERROR)
    df[col] = normalised
    if bad:
        logger.warning(
            f"{source}: {bad} row(s) in column '{col}' could not be parsed as "
            f"a year (marked with sentinel '{YEAR_PARSE_ERROR}')"
        )
    return df


# ---------------------------------------------------------------------------
# Convenience: list dataset names
# ---------------------------------------------------------------------------
def available_datasets() -> list[str]:
    """Return the sorted list of all known logical dataset names."""
    return sorted(DATASET_SPECS.keys())


def dataset_spec(name: str) -> DatasetSpec:
    """Return the :class:`DatasetSpec` for a given dataset name."""
    if name not in DATASET_SPECS:
        raise LoaderError(f"Unknown dataset '{name}'")
    return DATASET_SPECS[name]


__all__ = [
    "DATASET_SPECS",
    "DatasetSpec",
    "LoaderError",
    "available_datasets",
    "dataset_spec",
    "load_dataset",
    "load_excel",
]
