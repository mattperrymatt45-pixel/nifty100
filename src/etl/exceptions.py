"""Custom exception types for the ETL pipeline.

Having dedicated exception classes lets the loader, validators, and DB
loader stages distinguish parse failures from I/O errors and from
validation errors, so each can be logged and handled appropriately.
"""

from __future__ import annotations


class ETLError(Exception):
    """Base class for all ETL pipeline errors."""


class YearParseError(ETLError):
    """Raised when normalize_year() cannot convert a raw year label to YYYY-MM.

    Attributes:
        raw_value: The original value that could not be parsed.
        sentinel:  Canonical sentinel string ('PARSE_ERROR') used in logs/rejects.
    """

    sentinel: str = "PARSE_ERROR"

    def __init__(self, raw_value: object) -> None:
        self.raw_value = raw_value
        super().__init__(f"Unable to parse year label: {raw_value!r}")


class TickerParseError(ETLError):
    """Raised when normalize_ticker() rejects a missing/invalid ticker."""

    def __init__(self, raw_value: object) -> None:
        self.raw_value = raw_value
        super().__init__(f"Invalid company_id / ticker: {raw_value!r}")


class LoaderError(ETLError):
    """Raised when an Excel file cannot be located or read."""


class SchemaError(ETLError):
    """Raised when a loaded DataFrame fails basic schema checks."""
