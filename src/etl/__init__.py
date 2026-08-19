"""ETL pipeline package (Sprint 1, Days 2-7).

Public API for Day 2 (Excel loader & normalisers):

    from src.etl import normalize_ticker, normalize_year, load_excel, load_dataset
"""

from src.etl.exceptions import (
    ETLError,
    LoaderError,
    SchemaError,
    TickerParseError,
    YearParseError,
)
from src.etl.loader import (
    DATASET_SPECS,
    available_datasets,
    dataset_spec,
    load_dataset,
    load_excel,
)
from src.etl.normalizers import (
    YEAR_PARSE_ERROR,
    normalize_ticker,
    normalize_ticker_safe,
    normalize_year,
    normalize_year_safe,
)

__all__ = [
    "DATASET_SPECS",
    "YEAR_PARSE_ERROR",
    "ETLError",
    "LoaderError",
    "SchemaError",
    "TickerParseError",
    "YearParseError",
    "available_datasets",
    "dataset_spec",
    "load_dataset",
    "load_excel",
    "normalize_ticker",
    "normalize_ticker_safe",
    "normalize_year",
    "normalize_year_safe",
]
