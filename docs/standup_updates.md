# Sprint 1 & 2 — Standup Updates (Days 1–14)

Ten daily-style standup sections partitioning the complete Ratio Engine +
Data Foundation build, in chronological order.

---

## 1. Project Scaffolding & Developer Toolchain (Day 1)

Bootstrapped the **Nifty 100 Financial Intelligence Platform** repository at
`/home/user/nifty100/` on top of Python 3.13.14 with a production-grade
toolchain: Black (line-length 100), Ruff, and Pytest wired into the `Makefile`
via `make test`, `make lint`, and `make format` targets. Committed the
`pyproject.toml`, `requirements.txt`/`requirements-dev.txt`, a frozen `Settings`
dataclass (loaded from `.env`), a Loguru-based `get_logger`, the standard
cookie-cutter directory layout (`src/{etl,analytics,api,dashboard,utils}`,
`tests/`, `scripts/`, `data/{raw,processed,interim}`, `db/`, `output/`,
`docs/`, `reports/`, `config/`, `logs/`, `notebooks/`), and 53 smoke tests that
verify every directory, core dependency (pandas, numpy, sqlalchemy, openpyxl,
streamlit, fastapi, scikit-learn, pymupdf, …), and the logger/config
contract. Pushed the initial scaffold to `origin/main` on GitHub and
established the `[SprintN-DayM] feat: …` commit-message convention that every
subsequent day follows.

---

## 2. Excel Loader & Ticker/Year Normalization (Day 2)

Built the Excel ingestion layer in `src/etl/loader.py` around a `DatasetSpec`
registry that knows the header row (`header=1` for the 7 core Screener
exports, `header=0` for the 5 supplementary files), sheet name, and
ticker/year columns for all 12 datasets. The loader strips column whitespace,
drops empty rows/trailing empty columns, and routes supplementary datasets
through `data/raw/supporting datasets/` with a `data/raw/` fallback.
Implemented `normalize_ticker()` (uppercase, trims, collapses internal
double-spaces, hyphens and ampersands preserved, rejects non-strings/empty/
over-long inputs) and `normalize_year()` which handles ten different Indian
FY formats — `Mar-23`, `Mar 23`, `March 2023`, `mar_23`, `Mar/23`, `FY23`,
`FY 2024`, `Dec-22`, `Jun-21`, bare `2023`, two-digit pivot (50→2050,
51→1951), `YYYY-MM`, and `datetime` objects — returning a `YEAR_PARSE_ERROR`
sentinel for garbage input instead of raising. British-spelling shims
(`src/etl/normaliser.py`, `src/etl/validator.py`) re-export the American
modules so either spelling works. Shipped with 87 loader/normalizer unit
tests, all green.

---

## 3. Data Quality Rule Framework (Day 3)

Implemented a 16-rule DQ engine in `src/etl/validation.py` using a
`@register_rule` decorator that populates an ordered registry; each rule
returns a list of `DQFailure(severity, table, company_id, year, column,
reason)` records. The rules cover duplicate-PK detection on `companies`
(DQ-01), duplicate `(company_id, year)` on time-series tables (DQ-02),
FK-orphan detection (DQ-03), balance-sheet balancing with ±1% tolerance
(DQ-04), P&L cross-check between `operating_profit` and `opm_percentage`
(DQ-05), zero/negative sales (DQ-06 — later refined with a bank carve-out on
Day 6), year-validity including `YEAR_PARSE_ERROR` sentinel (DQ-07), ticker
regex `^[A-Z0-9&.-]{2,12}$` (DQ-08), cash-flow reconciliation
CFO+CFI+CFF ≈ net_cash_flow (DQ-09), non-negative fixed assets (DQ-10),
effective tax-rate sanity −5% to 70% (DQ-11), dividend payout ≤200% (DQ-12),
URL-syntax check (DQ-13), plus aggregate counters. `validate_all()` runs the
full rulebook across loaded tables and emits `validation_failures.csv`.
Came in at 56 rule tests, including the spec-mandated `test_dq04_bs_balance`
(assets=1000, liab=1020 → WARNING).

---

## 4. SQLite Schema, Idempotent Merge Upsert & Audit Trail (Day 4)

Wrote `db/schema.sql` with 12 business tables + 2 audit tables, FKs with
`ON DELETE CASCADE`, `CHECK` constraints (e.g. `total_assets > 0`), and 10
indexes on the hot join/filter columns. The tricky problem of the day was
pandas `to_sql`'s lack of native upsert, compounded by SQLite's
`SQLITE_MAX_EXPR_DEPTH=1000` (which blew up on 1500+ row deletes using OR
tuples) and the fact that `to_sql` bypasses column `DEFAULT` expressions
(meaning `loaded_at` would be NULL if not stamped client-side). Solved with
a TEMP-table + correlated `EXISTS` DELETE pattern chunked at 900 PKs per
batch, client-side UTC ISO `loaded_at` stamps, and an idempotent
`load_dataframe(..., merge=True)` helper that dedupes incoming rows by PK
before insert. Added `write_load_audit()` for per-table runtime stats and a
`_resolve_db_path()` that honours explicit args → `NIFTY100_DB_PATH` env
var → frozen `settings.DB_PATH`, with `:memory:` sentinel support for tests.
25 DB tests cover schema creation, FK enforcement, dedup, merge-update,
idempotency, and all 10 indexes.

---

## 5. Deterministic Synthetic Data, Full Load & DQ Manual Review (Days 5–7)

Because real Screener.in Excel exports were not yet available, built
`scripts/generate_data.py` with `SEED=42` to deterministically synthesise
all 12 files — 92 Nifty-100 tickers across 11 macro sectors, realistic P&L
(both non-bank and bank P&L structures), balance sheets that plug
`other_asset`/`other_liabilities` to balance exactly, cash flows, market
cap, stock prices (92×60 months = 5,520 rows), documents, peer groups with
benchmark flags, pros/cons, and analysis text. `scripts/run_etl.py` ties
everything together in parent-first `LOAD_ORDER`, running post-process
hooks, a `_reject_critical_rows` step that strips `YEAR_PARSE_ERROR`/
bad-ticker rows *before* insert (writing them to `output/parse_failures.csv`),
then the DQ validator, then audit CSV emission. Day 6 added the bank/NBFC
sector carve-out for DQ-06 so private banks with interest-not-sales income
don't get flagged for zero sales; Day 7 shipped 17 ready-to-run exploratory
SQL queries (row counts, FK integrity, coverage, sector mix, peer
benchmarks, stock performance) plus `scripts/demo_db.py` for a DB health
snapshot. End of Sprint 1: **258 tests passing**, 12,845 business rows
loaded, 0 FK orphans, 0 CRITICAL DQ failures, `docs/sprint1_retro.md`
written, `make load` fully idempotent in ~2 seconds.

---

## 6. Profitability & Leverage Ratio Engines (Days 8–9)

Kicked off Sprint 2 (the Ratio Engine) with `src/analytics/ratios.py`
implementing Net Profit Margin, Operating Profit Margin, EBIT Margin,
Return on Equity, ROCE, and Return on Assets, all returning a frozen
`ProfitabilityResult` dataclass with a tuple-of-warnings channel. ROCE is
`EBIT/(equity + reserves + borrowings) × 100` with EBIT = `operating_profit
- depreciation + other_income` and borrowings defaulted to 0 when missing;
OPM is cross-checked against the source `opm_percentage` column and
attaches a delta for logging. Day 9 added `src/analytics/leverage.py`
covering debt-to-equity (returns `None` on negative equity, `0.0` for truly
debt-free companies), interest coverage ratio (returns `None` when interest
≤ 0 and emits an `icr_label="Debt Free"`), a high-leverage flag at D/E > 5
**suppressed for banks/NBFCs** because high leverage is structurally normal
in financials, an ICR warning flag for 0 < ICR < 1.5, net debt
(`borrowings - investments`), and asset turnover. Financial-sector detection
uses the `_FINANCIAL_SECTOR_KEYWORDS` keyword match against
`broad_sector`. 86 unit tests across the two modules (46 profitability,
40 leverage) cover zero-sales, negative-equity, debt-free, zero-interest,
bank carve-outs, negative-ICR warnings, and result-contract frozenness.

---

## 7. Multi-Horizon CAGR Engine with 6 Edge-Case Flags (Day 10)

Delivered `src/analytics/cagr.py`, a generic single-period CAGR function
that returns a `CAGRResult(value, flag, start, end, n)` with six distinct
edge-case states rather than silent NaNs: **OK** (normal positive-to-
positive growth), **TURNAROUND** (negative base → positive end),
**DECLINE_TO_LOSS** (positive base → negative end), **BOTH_NEGATIVE**
(both endpoints negative — ratio undefined), **ZERO_BASE** (start = 0), and
**INSUFFICIENT** (look-back window exceeds available history). A
`compute_all_cagrs()` batch helper applies the engine across the full
panel for Revenue (sales), PAT (net_profit), and EPS over 3-, 5-, and
10-year windows, yielding 9 CAGR columns plus 9 matching flag columns.
Schema migration added all 18 columns via `ALTER TABLE ADD COLUMN` in
`_migrate_schema()` so existing data survived without a reload. 30 unit
tests cover the exact spec example (base=100, end=161, n=5 → ≈10.0%),
±10%/±20% round trips, flat growth (0%), declines, every flag transition,
and a full-panel `compute_all_cagrs` integration that feeds 15 years of
12% growth and asserts all three windows return ~12%. The spec-named
`test_cagr_normal` was explicitly added on Day 14.

---

## 8. Cash Flow Quality & 8-Class Capital Allocation Classifier (Day 11)

Built `src/analytics/cashflow_kpis.py` to translate the raw CFO/CFI/CFF
signs into investor-actionable signals: free cash flow (`cfo + cfi`), CFO/
PAT ratio (the cash-conversion-quality anchor), a 5-year rolling CFO
quality score with a 3-year minimum (tiered into **High Quality** > 1.0,
**Moderate** ≥ 0.5, **Accrual Risk** below), CapEx intensity
(`|cfi|/sales × 100`) tiered into Asset-Light / Moderate / Capital
Intensive, FCF conversion (`fcf/operating_profit × 100`), and an FCF
concern flag that trips on **three consecutive trailing years** of
negative FCF (a conservative distress signal). The centrepiece is an
8-pattern capital-allocation classifier that reads the three cash-flow
signs and the CFO/PAT ratio: **Reinvestor** (CFO+ CFI− CFF−),
**Shareholder Returns** (CFO+ CFI− CFF− with CFO/PAT ≥ 1.0 — dividend/
buyback funded by operations), **Liquidating Assets** (CFO+ CFI+ CFF−),
**Distress Signal** (CFO− CFI+ CFF+), **Growth Funded by Debt** (CFO− CFI−
CFF+), **Cash Accumulator** (CFO+ CFI+/− CFF+), **Pre-Revenue** (CFO− with
near-zero sales), and **Mixed** for anything else. Shipped
`scripts/generate_capital_allocation_csv.py` which writes 1,182 rows to
`output/capital_allocation.csv`, and 46 unit tests cover each pattern, the
zero-as-positive sign convention, CFO/PAT overrides, and CSV schema.

---

## 9. Financial Ratios Population, Composite Score & Bank ROCE Carve-Out (Days 12–13)

The two heavy-lift days of the sprint. Day 12's `scripts/populate_ratios.py`
inner-joins P&L, balance sheet, cash flow, companies (face_value), and
sectors, then iterates per company through `_compute_group()` to compute
every KPI family — profitability, leverage, cash flow, book value per
share (equity/shares_outstanding with `face_value` guard), and all 9 CAGRs
using positional look-back (`iloc[i-n]` to mirror the 5-year anchor used
in the spot-check). A cross-sectional `_compute_composite_scores()` then
winsorises each sub-score at P10/P92 (wait P10/P90), scales 0–100, and
combines them with the spec weights (0.30 ROE + 0.25 FCF Conversion +
0.25 ROCE + 0.20 D/E), forcing debt-free companies to D/E=100 and
banks/NBFCs to a neutral D/E=50. The `--spot-check` flag picks 3 seeded
companies with ≥6 years of history (NAUKRI, COALINDIA, SIEMENS under
`random.seed(2024)`) and hand-recomputes ROE and 5-yr Revenue CAGR. Day
13 added `src/analytics/sector_roce.py` with `is_bank_nfc_insurance()`
(extending the sector keyword list to include "insurance"),
`compute_bank_roce()` using the **ROA proxy** `EBIT/total_assets × 100`,
a `roce_for_company()` dispatcher, a `cross_check_vs_source()` routine
that compares every company-year against `companies.roce_percentage`
(>5pp threshold) and `companies.roe_percentage` (>10pp threshold), a
`categorize_anomaly()` function that buckets into `bank_carveout`
(informational for all financial ROCE), `formula_discrepancy` (Δ ≤ 15pp),
`version_difference` (15pp < Δ ≤ 40pp), and `data_source` (Δ > 40pp), plus
`format_anomaly_log()` which writes `output/ratio_edge_cases.log` with
per-category sections, summary counts, and a display-policy note that
Ratio Engine values drive screener/analytics while the companies.xlsx
snapshot is display-only. Schema migration added the 5 carve-out columns
(`roce_sector_adjusted`, `roce_source_value`, `roe_source_value`,
`roce_anomaly_category`, `roe_anomaly_category`). End of Day 13: 1,182
fully-computed financial_ratios rows for 92 companies; 58 tests added
(28 populate + 30 sector_roce).

---

## 10. Day-14 Sign-Off — Test Sweep, Generator Calibration, Screener Preview & Retro (Day 14)

Closed the sprint by finding and fixing three Day-14 issues: (1) the
synthetic generator seeded `random`/`numpy.random` only at module import
time, so any test that consumed RNG state before calling `generate_all()`
produced different data — a flaky spot-check that gave COALINDIA a 6.82pp
CAGR delta depending on test order. Fixed by moving `random.seed(SEED)`
and `np.random.seed(SEED)` inside `generate_all()` so every invocation is
fully deterministic. (2) `scripts/day13_bank_roce.py` originally wrote its
5 carve-out columns back via `load_dataframe(merge=True)`, but merge uses
DELETE+INSERT on primary key — so every column *not* present in the
7-column update DataFrame was silently nulled, wiping ROE/ROCE/every
CAGR/composite across all 1,182 rows. Replaced with a targeted
`executemany` `UPDATE` that touches only the 5 Day-13 columns; added
`--db-path`/`--log-path` flags so unit tests write to temp paths; added a
`test_existing_ratio_columns_preserved` regression test that seeds a row
with non-trivial KPIs, runs the carve-out, and asserts nothing was
clobbered. (3) The balance-sheet reserves formula (`np_ × fy_idx × U(3,7)`)
was producing equity bases ~50–100× annual PAT, crushing all ROE/ROCE
values to ~1–3% and returning 0 hits for the quality-compounder screener;
replaced with a sector-calibrated target-ROE approach (Financials 12–20%,
IT 22–40%, Staples/Healthcare 18–35%, others 12–25%) that produces a
realistic ROE distribution (mean 18.1%, IQR 14.4–21.5%). Also renamed the
spec's `test_spec_example` to `test_cagr_normal` per §27/page-41,
regenerated the production DB, refreshed `output/ratio_edge_cases.log`
(1,669 anomalies — 243 bank_carveout, 554 formula_discrepancy, 793
version_difference, 79 data_source) and `output/capital_allocation.csv`
(1,182 rows), ran the ROE>15% & D/E<1 screener which now returns a
business-sensible list of 47 quality compounders (TATACONSUM, COLPAL,
HDFCBANK, SUNPHARMA, TCS, RELIANCE, HINDUNILVR, KOTAKBANK, NESTLEIND,
ASIANPAINT, TITAN, etc.), demoed 5 companies × all KPI families for the
team lead, and wrote `docs/sprint2_retro.md` documenting the 10 bugs
fixed, watch-list items, and Sprint 3 preview (Screener & Peer
Comparison, Days 15–21). Final score: **479/479 tests passing**, Black &
Ruff clean, spot-check deltas 0.000000 pp, commit `060b98c` pushed to
`origin/main`.
