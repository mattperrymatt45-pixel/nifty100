"""Sprint 5 Day 32 — Tests for Capital Allocation Report module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.analytics import capital_allocation_report as car

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


# ---------------------------------------------------------------------------
# Unit tests — pure helpers
# ---------------------------------------------------------------------------
class TestConstants:
    def test_all_eight_patterns_defined(self) -> None:
        assert len(car.ALL_EIGHT_PATTERNS) == 8
        assert car.PATTERN_SHAREHOLDER_RETURNS in car.ALL_EIGHT_PATTERNS
        assert car.PATTERN_REINVESTOR in car.ALL_EIGHT_PATTERNS
        assert car.PATTERN_GROWTH_FUNDED_BY_DEBT in car.ALL_EIGHT_PATTERNS
        assert car.PATTERN_DISTRESS_SIGNAL in car.ALL_EIGHT_PATTERNS
        assert car.PATTERN_LIQUIDATING_ASSETS in car.ALL_EIGHT_PATTERNS
        assert car.PATTERN_CASH_ACCUMULATOR in car.ALL_EIGHT_PATTERNS
        assert car.PATTERN_PRE_REVENUE in car.ALL_EIGHT_PATTERNS
        assert car.PATTERN_MIXED in car.ALL_EIGHT_PATTERNS


class TestPatternDistribution:
    def test_distribution_covers_all_eight_patterns_even_if_zero(self) -> None:
        # Build a minimal CA dataframe
        df = pd.DataFrame(
            {
                "company_id": ["A", "B", "C"],
                "year": ["2024-03", "2024-03", "2024-03"],
                "cfo_sign": ["+", "+", "+"],
                "cfi_sign": ["-", "-", "-"],
                "cff_sign": ["+", "-", "-"],
                "pattern_label": [
                    car.PATTERN_MIXED,
                    car.PATTERN_REINVESTOR,
                    car.PATTERN_SHAREHOLDER_RETURNS,
                ],
            }
        )
        dist = car.build_pattern_distribution(df)
        # All 8 patterns present as rows
        present_labels = set(dist["pattern_label"].tolist())
        for p in car.ALL_EIGHT_PATTERNS:
            assert p in present_labels, f"Missing pattern {p}"
        # Counts sum to total companies (3)
        assert dist["company_count"].sum() == 3
        # Verify specific counts. In this fixture:
        #   A's max year = 2024 -> Mixed (+,-,+)
        #   B's max year = 2024 -> Reinvestor (+,-,-)
        #   C's max year = 2024 -> Shareholder Returns (+,-,-)
        # Note: build_pattern_distribution reads pattern_label as-is (no re-classify).
        label_counts = dict(zip(dist["pattern_label"], dist["company_count"], strict=True))
        # A is Mixed (latest)
        assert label_counts[car.PATTERN_MIXED] == 1
        # B is Reinvestor (we hardcoded pattern_label for B as Reinvestor in latest)
        assert label_counts[car.PATTERN_REINVESTOR] == 1
        # C is Shareholder Returns
        assert label_counts[car.PATTERN_SHAREHOLDER_RETURNS] == 1
        assert label_counts[car.PATTERN_DISTRESS_SIGNAL] == 0
        assert label_counts[car.PATTERN_GROWTH_FUNDED_BY_DEBT] == 0
        assert label_counts[car.PATTERN_LIQUIDATING_ASSETS] == 0
        assert label_counts[car.PATTERN_CASH_ACCUMULATOR] == 0
        assert label_counts[car.PATTERN_PRE_REVENUE] == 0

    def test_distribution_counts_latest_year_per_company(self) -> None:
        """Company with multiple years — only latest year counted."""
        df = pd.DataFrame(
            {
                "company_id": ["A", "A", "B"],
                "year": ["2023-03", "2024-03", "2024-03"],
                "cfo_sign": ["+", "+", "+"],
                "cfi_sign": ["-", "-", "-"],
                "cff_sign": ["-", "+", "-"],
                "pattern_label": [
                    car.PATTERN_SHAREHOLDER_RETURNS,  # 2023 — old
                    car.PATTERN_MIXED,  # 2024 — latest for A
                    car.PATTERN_REINVESTOR,
                ],
            }
        )
        dist = car.build_pattern_distribution(df)
        label_counts = dict(zip(dist["pattern_label"], dist["company_count"], strict=True))
        assert label_counts[car.PATTERN_MIXED] == 1  # A's latest
        assert label_counts[car.PATTERN_SHAREHOLDER_RETURNS] == 0  # old
        assert label_counts[car.PATTERN_REINVESTOR] == 1  # B
        assert dist["company_count"].sum() == 2


class TestPatternChangeDetection:
    def test_detects_changes_between_latest_two_years(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["A", "A", "B", "B", "C"],
                "year": ["2023-03", "2024-03", "2023-03", "2024-03", "2024-03"],
                "cfo_sign": ["+", "+", "+", "+", "+"],
                "cfi_sign": ["-", "-", "-", "-", "-"],
                "cff_sign": ["-", "+", "-", "-", "-"],
                "pattern_label": [
                    car.PATTERN_REINVESTOR,
                    car.PATTERN_MIXED,  # A changes
                    car.PATTERN_SHAREHOLDER_RETURNS,
                    car.PATTERN_SHAREHOLDER_RETURNS,  # B stays
                    car.PATTERN_MIXED,  # C only one year
                ],
            }
        )
        # Use an in-memory SQLite with companies + sectors tables for detection
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE companies (id TEXT PRIMARY KEY, company_name TEXT);
            CREATE TABLE sectors (company_id TEXT, broad_sector TEXT);
            INSERT INTO companies VALUES ('A','Alpha'),('B','Bravo'),('C','Charlie');
            INSERT INTO sectors VALUES ('A','S1'),('B','S2'),('C','S3');
            """)
        changes = car.detect_pattern_changes(df, conn)
        conn.close()

        assert len(changes) == 1
        row = changes.iloc[0]
        assert row["company_id"] == "A"
        assert row["prev_pattern"] == car.PATTERN_REINVESTOR
        assert row["latest_pattern"] == car.PATTERN_MIXED
        assert row["prev_year"] == "2023-03"
        assert row["latest_year"] == "2024-03"

    def test_no_change_when_pattern_same_yoy(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["A", "A"],
                "year": ["2023-03", "2024-03"],
                "cfo_sign": ["+", "+"],
                "cfi_sign": ["-", "-"],
                "cff_sign": ["-", "-"],
                "pattern_label": [car.PATTERN_SHAREHOLDER_RETURNS, car.PATTERN_SHAREHOLDER_RETURNS],
            }
        )
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE companies (id TEXT PRIMARY KEY, company_name TEXT);
            CREATE TABLE sectors (company_id TEXT, broad_sector TEXT);
            INSERT INTO companies VALUES ('A','Alpha');
            """)
        changes = car.detect_pattern_changes(df, conn)
        conn.close()
        assert len(changes) == 0


class TestPatternChangeRow:
    def test_as_dict_round_trip(self) -> None:
        row = car.PatternChangeRow(
            company_id="RELIANCE",
            company_name="Reliance Industries Ltd",
            sector="Energy",
            prev_year="2023-03",
            prev_pattern=car.PATTERN_REINVESTOR,
            latest_year="2024-03",
            latest_pattern=car.PATTERN_SHAREHOLDER_RETURNS,
        )
        d = row.as_dict()
        assert d["company_id"] == "RELIANCE"
        assert d["latest_pattern"] == car.PATTERN_SHAREHOLDER_RETURNS
        assert set(d.keys()) == set(car.PATTERN_CHANGES_COLUMNS)


# ---------------------------------------------------------------------------
# Integration tests against production DB
# ---------------------------------------------------------------------------
class TestAgainstProductionDB:
    @pytest.fixture()
    def ca_df(self) -> pd.DataFrame:
        return pd.read_csv(PROJECT_ROOT / "output" / "capital_allocation.csv")

    def test_db_file_exists(self) -> None:
        assert DB_PATH.exists(), f"DB not found at {DB_PATH}"

    def test_completeness_verification_passes(self, ca_df: pd.DataFrame) -> None:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            result = car.verify_capital_allocation_completeness(ca_df, conn)
        finally:
            conn.close()
        assert result["is_complete"] is True
        assert result["total_companies_db"] == 92
        assert result["total_companies_csv"] == 92
        assert result["total_rows_csv"] == result["total_rows_expected"]
        assert result["missing_company_ids"] == []
        assert result["missing_rows"] == []

    def test_distribution_covers_92_companies(self, ca_df: pd.DataFrame) -> None:
        dist = car.build_pattern_distribution(ca_df)
        assert dist["company_count"].sum() == 92

    def test_run_capital_allocation_report_produces_outputs(self, tmp_path: Path) -> None:
        """Full end-to-end run into a temp dir produces expected files."""
        import shutil

        # Copy DB to tmp_path (read-only use is fine too but keep test hermetic)
        tmp_db = tmp_path / "nifty100.db"
        shutil.copy(DB_PATH, tmp_db)
        # Need a capital_allocation.csv in output dir; copy it
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        shutil.copy(
            PROJECT_ROOT / "output" / "capital_allocation.csv", out_dir / "capital_allocation.csv"
        )
        # Pass explicit paths so no settings.PROJECT_ROOT dependency needed.
        completeness, _dist, _ch, xlsx_path = car.run_capital_allocation_report(
            db_path=tmp_db, output_dir=out_dir
        )
        assert completeness["is_complete"] is True
        assert (out_dir / "pattern_changes.csv").exists()
        assert xlsx_path.exists()
        # pattern_changes.csv has expected columns
        out_csv = pd.read_csv(out_dir / "pattern_changes.csv")
        assert set(out_csv.columns) == set(car.PATTERN_CHANGES_COLUMNS)
