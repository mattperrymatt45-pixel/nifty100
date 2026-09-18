"""Unit tests for src.etl.normaliser (Day 41 — 20 tests for normalize_year).

These tests exercise the British-spelling ``src.etl.normaliser`` re-export
shim (which forwards everything to ``src.etl.normalizers``).  They focus
specifically on ``normalize_year()`` covering every variant mentioned in
the spec §23 ETL Edge Cases table plus boundary and error cases.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.etl.exceptions import YearParseError
from src.etl.normaliser import YEAR_PARSE_ERROR, normalize_year, normalize_year_safe


class TestNormaliseYearCanonical:
    """Spec §23 canonical Mar-23 → 2023-03 examples."""

    def test_mar23_hyphen_short(self) -> None:
        """'Mar-23' → '2023-03'."""
        assert normalize_year("Mar-23") == "2023-03"

    def test_mar_23_space_separator(self) -> None:
        """'Mar 23' (space) → '2023-03'."""
        assert normalize_year("Mar 23") == "2023-03"

    def test_march_2023_full_name(self) -> None:
        """'March-2023' → '2023-03'."""
        assert normalize_year("March-2023") == "2023-03"


class TestNormaliseYearBareYears:
    """Bare 2-digit / 4-digit year defaults to March FY close."""

    def test_bare_integer_2023(self) -> None:
        assert normalize_year(2023) == "2023-03"

    def test_bare_string_2023(self) -> None:
        assert normalize_year("2023") == "2023-03"

    def test_bare_two_digit_string_23(self) -> None:
        assert normalize_year("23") == "2023-03"

    def test_bare_float_2024_0(self) -> None:
        """Excel sometimes delivers years as floats (2024.0)."""
        assert normalize_year(2024.0) == "2024-03"


class TestNormaliseYearFYPrefix:
    """FY-prefixed variants."""

    def test_fy23(self) -> None:
        assert normalize_year("FY23") == "2023-03"

    def test_fy_space_2024(self) -> None:
        assert normalize_year("FY 2024") == "2024-03"

    def test_fy2023_nosep(self) -> None:
        assert normalize_year("FY2023") == "2023-03"

    def test_fy_dotted(self) -> None:
        """'F.Y.24' variant sometimes seen in old annual reports."""
        assert normalize_year("F.Y.24") == "2024-03"


class TestNormaliseYearNonMarchYearEnds:
    """Non-March closes (banks use June; some multinationals use Dec)."""

    def test_dec22_december_close(self) -> None:
        assert normalize_year("Dec-22") == "2022-12"

    def test_jun23_june_close(self) -> None:
        assert normalize_year("Jun-23") == "2023-06"


class TestNormaliseYearAlreadyNormalised:
    """Already-canonical YYYY-MM inputs."""

    def test_already_yyyy_mm_passthrough(self) -> None:
        assert normalize_year("2023-03") == "2023-03"

    def test_datetime_object_input(self) -> None:
        """Excel can surface year cells as datetime objects."""
        assert normalize_year(datetime(2023, 3, 31)) == "2023-03"


class TestNormaliseYearTwoDigitPivot:
    """Pivot rule: ≤ 50 → 20xx, > 50 → 19xx."""

    def test_50_maps_to_2050(self) -> None:
        assert normalize_year(50) == "2050-03"

    def test_51_maps_to_1951(self) -> None:
        assert normalize_year(51) == "1951-03"


class TestNormaliseYearErrors:
    """Error cases must raise YearParseError; safe wrapper returns sentinel."""

    def test_none_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year(None)

    def test_garbage_string_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year("not-a-year")

    def test_safe_wrapper_returns_sentinel_on_error(self) -> None:
        assert normalize_year_safe("garbage") == YEAR_PARSE_ERROR
