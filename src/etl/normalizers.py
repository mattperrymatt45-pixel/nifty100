"""Field normalisation utilities for the ETL pipeline.

These pure functions convert raw Excel cell values into the canonical
platform formats described in §5 and §23 of the project spec:

* ``normalize_ticker`` -- company_id → stripped uppercase NSE ticker.
* ``normalize_year``   -- Indian FY label ("Mar-23", "FY24", "2023", ...)
                         → "YYYY-MM" (always March-FY unless the raw
                         label explicitly indicates another close month,
                         e.g. "Dec-22" → "2022-12").

Both functions raise dedicated exceptions (see ``exceptions.py``) on
invalid input so callers can route rejects to a failure log rather
than silently mangling data.
"""

from __future__ import annotations

import re
from datetime import datetime

from src.etl.exceptions import TickerParseError, YearParseError

# ---------------------------------------------------------------------------
# Public sentinel (used in logs / failure CSV when we want a string marker)
# ---------------------------------------------------------------------------
YEAR_PARSE_ERROR: str = YearParseError.sentinel  # "PARSE_ERROR"

# Type alias for inputs we accept (Excel cells can be str / int / float / None)
YearInput = str | int | float | None
TickerInput = str | None

# ---------------------------------------------------------------------------
# Month-name resolution -- supports both 3-letter abbreviations ("Mar") and
# full English names ("March").  Case-insensitive.
# ---------------------------------------------------------------------------
_MONTH_MAP: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

# Regex to recognise and strip an optional "FY" / "F.Y." / "FY-" / "FY " prefix
_FY_PREFIX = re.compile(r"^\s*(?:f\.?y\.?\s*[-_/ ]*)+", re.IGNORECASE)

# Regex to split "Mar-23", "Mar 23", "March-2023", "Dec_22", "Mar/23"
_MONTH_YEAR_SPLIT = re.compile(r"^\s*([A-Za-z]+)\s*[\-_/ ]\s*(\d{2,4})\s*$")

# Regex for an already-normalised "YYYY-MM" string
_YYYY_MM = re.compile(r"^\s*(\d{4})-(\d{1,2})\s*$")

# Regex for a bare 2- or 4-digit year (e.g. "23", "2023")
_BARE_YEAR = re.compile(r"^\s*(\d{2,4})\s*$")


# ---------------------------------------------------------------------------
# normalize_ticker
# ---------------------------------------------------------------------------
def normalize_ticker(value: TickerInput) -> str:
    """Normalise an NSE ticker / company_id to canonical form.

    Rules (per spec §23):
      * ``None`` / empty / whitespace-only  → raises ``TickerParseError``.
      * Whitespace stripped on both sides.
      * Converted to UPPER CASE.
      * Hyphens (``BAJAJ-AUTO``) and ampersands (``M&M``) preserved.
      * Embedded internal whitespace is collapsed (screener.in occasionally
        emits "BAJAJ  AUTO" with double space).

    Args:
        value: Raw cell value from Excel.

    Returns:
        Canonical ticker string, e.g. ``"TCS"``, ``"BAJAJ-AUTO"``, ``"M&M"``.

    Raises:
        TickerParseError: If value is missing/empty/non-string.
    """
    if value is None:
        raise TickerParseError(value)
    if not isinstance(value, str):
        # Numeric tickers don't exist on NSE; reject fast.
        raise TickerParseError(value)

    cleaned = value.strip()
    if not cleaned:
        raise TickerParseError(value)

    # Collapse any internal runs of whitespace into a single space
    cleaned = re.sub(r"\s+", " ", cleaned)

    return cleaned.upper()


# ---------------------------------------------------------------------------
# normalize_year
# ---------------------------------------------------------------------------
def normalize_year(value: YearInput) -> str:
    """Normalise a financial-year label to canonical ``"YYYY-MM"`` form.

    Supported input formats (see spec §23, ETL Edge Cases table):

    =====================================  ==========  =========================
    Raw                                    Expected    Note
    =====================================  ==========  =========================
    ``"Mar-23"``                           ``2023-03`` Most common (short form)
    ``"Mar 23"``                           ``2023-03`` Space separator
    ``"March-2023"`` / ``"March 2023"``    ``2023-03`` Full month name
    ``"2023"`` / ``"23"`` (int or str)     ``2023-03`` Bare year → March FY
    ``"FY23"`` / ``"FY 2023"`` / "FY2023"  ``2023-03`` FY-prefix removed
    ``"Dec-22"``                           ``2022-12`` December year-end
    ``"Jun-23"``                           ``2023-06`` June year-end (banks)
    ``"2023-03"``                          ``2023-03`` Already normalised
    ``"garbage"``, ``None``, 0, ...        raises      ``YearParseError``
    =====================================  ==========  =========================

    For 2-digit years we use a pivot at 50: values ≤ 50 map to 20xx
    (2000-2050) and values > 50 map to 19xx (1951-1999). This matches
    Screener.in's actual data range (FY 2010 onward) with headroom.

    Args:
        value: Raw cell value (string, int, float, or None).

    Returns:
        Normalised ``"YYYY-MM"`` string.

    Raises:
        YearParseError: If the value cannot be parsed into a valid year/month.
    """
    if value is None:
        raise YearParseError(value)

    # Excel sometimes loads "Mar-23" as a datetime; accept datetime objects.
    if isinstance(value, datetime):
        _validate_ym(value.year, value.month, raw=value)
        return f"{value.year:04d}-{value.month:02d}"

    # Excel sometimes loads year cells as floats (e.g. 2023.0)
    if isinstance(value, (int, float)):
        # Reject NaN / booleans (bool is an int subclass)
        if isinstance(value, bool):
            raise YearParseError(value)
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise YearParseError(value) from None
        if f != f or f <= 0:  # NaN or non-positive
            raise YearParseError(value)
        yi = int(f)
        if yi < 100:
            yi = _expand_two_digit(yi, raw=value)
        _validate_ym(yi, 3, raw=value)
        return f"{yi:04d}-03"

    if not isinstance(value, str):
        raise YearParseError(value)

    raw = value.strip()
    if not raw:
        raise YearParseError(value)

    s = raw

    # 1) Strip FY / F.Y. prefix (case-insensitive)
    s = _FY_PREFIX.sub("", s).strip()
    if not s:
        raise YearParseError(value)

    # 2) Already normalised "YYYY-MM"?
    m = _YYYY_MM.match(s)
    if m:
        year_i, month_i = int(m.group(1)), int(m.group(2))
        _validate_ym(year_i, month_i, raw=value)
        return f"{year_i:04d}-{month_i:02d}"

    # 3) Month-Year form ("Mar-23", "March 2023", "Dec_22", ...)
    m = _MONTH_YEAR_SPLIT.match(s)
    if m:
        month_str, year_str = m.group(1).lower(), m.group(2)
        if month_str not in _MONTH_MAP:
            raise YearParseError(value)
        month_i = _MONTH_MAP[month_str]
        year_i = _parse_year_digits(year_str, raw=value)
        _validate_ym(year_i, month_i, raw=value)
        return f"{year_i:04d}-{month_i:02d}"

    # 4) Bare year (2 or 4 digits) → assume March FY close
    m = _BARE_YEAR.match(s)
    if m:
        year_i = _parse_year_digits(m.group(1), raw=value)
        _validate_ym(year_i, 3, raw=value)
        return f"{year_i:04d}-03"

    # Nothing matched
    raise YearParseError(value)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _parse_year_digits(digits: str, *, raw: object) -> int:
    """Convert 2- or 4-digit year string to a 4-digit year integer."""
    try:
        yi = int(digits)
    except (TypeError, ValueError):
        raise YearParseError(raw) from None
    if len(digits) == 2:
        return _expand_two_digit(yi, raw=raw)
    return yi


def _expand_two_digit(yy: int, *, raw: object) -> int:
    """Two-digit year pivot.

    The project's data window is FY 2010-2024 with modest future headroom.
    We use a fixed pivot at 50: values ≤ 50 map to 20xx (covers 2000-2050),
    values > 50 map to 19xx (covers 1951-1999). This matches common
    financial-data convention and is appropriate for Screener.in exports
    which never emit pre-2000 two-digit years in practice.
    """
    if yy < 0 or yy > 99:
        raise YearParseError(raw)
    if yy <= 50:
        return 2000 + yy
    return 1900 + yy


def _validate_ym(year: int, month: int, *, raw: object) -> None:
    """Reject obviously out-of-range year/month combinations."""
    if month < 1 or month > 12:
        raise YearParseError(raw)
    if year < 1950 or year > 2100:
        raise YearParseError(raw)


# ---------------------------------------------------------------------------
# Convenience: safe wrapper returning sentinel instead of raising
# ---------------------------------------------------------------------------
def normalize_year_safe(value: YearInput) -> str:
    """Like ``normalize_year`` but returns ``'PARSE_ERROR'`` on failure.

    Useful for vectorised application over a DataFrame column where you
    want to keep all rows (and later filter rejects) rather than abort.
    """
    try:
        return normalize_year(value)
    except YearParseError:
        return YEAR_PARSE_ERROR


def normalize_ticker_safe(value: TickerInput) -> str | None:
    """Like ``normalize_ticker`` but returns ``None`` on failure.

    Provided for symmetry with ``normalize_year_safe``; the loader uses
    the raising version so missing tickers produce hard rejects.
    """
    try:
        return normalize_ticker(value)
    except TickerParseError:
        return None
