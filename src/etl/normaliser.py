"""Compatibility shim — normaliser.py re-exports everything from normalizers.py.

The Sprint 1 deliverable list uses British spelling ``normaliser.py``; the
codebase follows the American ``normalizers.py`` convention used since Day 2.
This shim keeps both import paths working.
"""

from src.etl.normalizers import (
    YEAR_PARSE_ERROR,
    TickerInput,
    YearInput,
    normalize_ticker,
    normalize_ticker_safe,
    normalize_year,
    normalize_year_safe,
)

__all__ = [
    "YEAR_PARSE_ERROR",
    "TickerInput",
    "YearInput",
    "normalize_ticker",
    "normalize_ticker_safe",
    "normalize_year",
    "normalize_year_safe",
]
