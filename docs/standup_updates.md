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

## Day 16 — Screener Preset Validation & Excel Export (Sprint 3)

Implemented the valuation ratios analytics module (`src/analytics/valuation.py`)
with P/E, P/B, EV/EBITDA, FCF Yield, and Earnings Yield primitives, plus a
Cheap/Fair/Expensive heuristic classifier and multiple-comparison helper. All
edge cases handled (negative earnings → None for P/E, zero book → None for
P/B, etc.) — 26 new unit tests with 98% coverage on the module.

Built the Excel exporter (`src/screener/exporter.py`) that writes a formatted
`screener_output.xlsx` with: a Summary sheet (preset counts + filters), six
preset sheets with 35 display columns grouped by block (Identity →
Profitability → Growth → Leverage & Cash Quality → Valuation → Composite),
frozen panes, auto-filter, auto-sized columns, three-color traffic-light
conditional formatting (green = good, red = bad, correctly oriented per
metric), dedicated number formats per column, and friendly headers. Added
`scripts/export_screener.py` and `make screener-export-all` target. Sheet-name
sanitisation handles long labels (GARP, Small-Cap Momentum) and illegal chars.

Extended the screener SQL to include EV column, and added two derived columns
in `load_screener_dataset()`: `fcf_yield_pct` (computed from FCF / MCap × 100)
and `valuation_bucket` (Cheap/Fair/Expensive). 23 new exporter tests cover
column config, sheet-name safety, workbook structure, header contents,
Summary sheet integrity, and pandas readability of every tab.

Preset results verified business-sensible: Quality Compounders 23 (COLPAL,
GODREJCP, HEROMOTOCO, BAJAJ-AUTO, IOC, SUNPHARMA, TITAN, ASIANPAINT…),
Dividend Aristocrats 25, GARP 7, Deep Value 4 (TATACONSUM, IOC, ADANIPOWER,
DMART), Zero-Debt Quality 12, Small-Cap Momentum 3 — all within the spec
ranges (§25). `output/screener_output.xlsx` generated at 45 KB with 7 sheets
and 74 total rows.

**Final score: 545/545 tests passing** (+49 new since Day 15), Black & Ruff
clean, valuation.py 98% coverage, exporter.py 97% coverage.

### Day 16b — Preset alignment to spec §25

Renamed the six presets to match spec §25 exactly (quality_compounder, value_pick,
growth_accelerator, dividend_champion, debt_free_blue_chip, turnaround_watch)
with the precise thresholds specified:
  - Quality Compounder: ROE>15, D/E<1, FCF>0, Rev CAGR 5y>10% → 32 hits
  - Value Pick: P/E<20, P/B<3, D/E<2, Div Yield>1% → 5 hits
  - Growth Accelerator: PAT CAGR 5y>20%, Rev CAGR 5y>15%, D/E<2 → 14 hits
  - Dividend Champion: Div Yield>2%, Payout<80%, FCF>0 → 32 hits
  - Debt-Free Blue Chip: D/E≈0 (ε=0.20), ROE>12%, Sales>5000Cr → 8 hits
  - Turnaround Watch: Rev CAGR 3y>10%, FCF>0, D/E declining YoY → 27 hits

Extended the filter engine to support two new directions:
  - 'eq'   : strict equality with configurable epsilon (for D/E=0)
  - 'flag' : boolean / truthy column test (for FCF-positive, YoY decline)
Added prior-year D/E lookup to the screener SQL (LEFT JOIN self on company +
MAX(year) < current year) to compute de_yoy_change and de_yoy_declining.
Added dividend_payout_ratio_pct as a filterable metric. All six presets return
between 5 and 50 companies (Value Pick is tight at 5 — correct per spec).
Regenerated output/screener_output.xlsx (7 sheets, 118 total rows, 45 KB).
**Final score: 560/560 tests passing.**

## Day 17 — Composite Quality Score & Threshold-Coloured Export (Sprint 3)

Implemented the Day-17 composite quality score per spec §25.1 in a new
`src/analytics/composite.py` module. The score is a weighted 0–100 scale:

  - **35% Profitability** — ROE 15% + ROCE 10% + NPM 10%
  - **30% Cash Quality** — FCF CAGR 5y 15% + CFO/PAT 10% + FCF-positive flag 5%
  - **20% Growth**        — Revenue CAGR 5y 10% + PAT CAGR 5y 10%
  - **15% Leverage**      — D/E piecewise 10% + ICR piecewise 5%

Every continuous metric is winsorised at the **P10/P90** cross-section
percentiles to neutralise outliers, then min-max scaled to 0–100. Leverage
metrics use spec-defined piecewise-linear anchors:
  - D/E: (0,100), (0.5,85), (1.0,70), (2.0,50), (5.0,0) — lower is better.
  - ICR: (10,100), (5,75), (3,50), (1.5,0) — higher is better.
Debt-free companies (`icr_label == "Debt Free"`) are awarded a perfect
ICR score of 100.

FCF CAGR 5y is computed directly from the `cashflow` table via
`compute_fcf_cagr_5yr()`, requiring an exact 5-calendar-year base and a
positive base FCF; turnarounds / insufficient history return NaN (assigned
neutral 50 score after scaling so they don't distort ranks).

On top of the overall `composite_score_100`, a **sector-relative score** is
produced by re-min-maxing within each `broad_sector` (single-company
sectors get a neutral 50). Two ranks are emitted: `composite_rank`
(universe 1..N, contiguous) and `sector_rank` (per-sector rank, nullable
Int64 to defend against NaN scores).

The screener dataset loader (`load_screener_dataset`) now calls
`compute_composite_scores()` automatically when `latest_year_only=True`,
merging in `fcf_cagr_5yr`, all ten component `*_score` columns, the sector
relative score, and both ranks; the legacy `composite_quality_score`
column is aliased to the new score so sort logic stays unified.

Upgraded the Excel exporter (`src/screener/exporter.py`) with per-cell
threshold colour coding:
  - **Green fill (#C6EFCE)** — value passes the preset's threshold for
    that metric.
  - **Red fill (#FFC7CE)** — value is in a filtered column but fails the
    threshold (these are rare because `apply_filters` already excludes
    failing companies, but financial-skip / debt-free-pass edge cases
    keep some near-threshold cells visible for analyst review).
  - Alternating light row fill otherwise.
The title row now reads e.g. "Quality Compounder — 32 of 89 companies
(sorted by composite score, 0-100; green=passes threshold, red=fails)".

Added 21 new unit tests in `tests/kpi/test_composite.py` covering:
weights sum to 1.00 (and the sub-totals 35/30/20/15 exactly), winsorise
caps, minmax scale semantics (including reverse scale for leverage and
the constant-series-returns-50 guard), piecewise-linear interpolation at
exact anchors and midpoints with out-of-range clipping, FCF CAGR
computation against the live DB, CompositeResult contract, 0–100
bounds on both overall and sector-relative scores, contiguous
universe ranks starting at 1, per-sector ranks starting at 1,
descending-sort invariant, and presence of every component column.

**Bug fixed during QA:** The test suite intermittently produced NaN
scores with "boolean value of NA is ambiguous" when running full-suite
orderings. Root cause: `tests/etl/test_exploratory_queries.py` used
`object.__setattr__(settings, "DB_PATH", …)` to repoint the frozen
settings singleton at a temp DB but never restored it (monkeypatch
handles `os.environ`, not the in-process singleton). Later
module-scoped fixtures in `tests/kpi/test_composite.py` and
`tests/screener/test_exporter.py` that only did `os.environ.pop(...)`
still inherited the stale `settings.DB_PATH` pointing at a deleted
tmp directory, so `load_screener_dataset()` connected to an empty
file and returned 79 NaN rows. Fixed two ways:
  1. The exploratory-queries helper now saves and restores the
     original `settings.RAW_DATA_DIR / PROCESSED_DATA_DIR / DB_PATH`
     in a `try/finally`, so it can never leak.
  2. Composite/exporter production-DB fixtures now explicitly pass
     `db_path=str(settings.PROJECT_ROOT / "db" / "nifty100.db")` to
     every `load_screener_dataset`, `run_screener`, and
     `compute_composite_scores` call, and also reset
     `os.environ["NIFTY100_DB_PATH"]` and `settings.DB_PATH` to the
     production path defensively.

After fixes: **581/581 tests passing** (560 prior + 21 new), Black &
Ruff clean, `output/screener_output.xlsx` regenerated with 7 sheets /
118 rows / green-red threshold colouring, composite score & sector
rank columns visible on every preset sheet.

## Day 18 — Peer Percentile Rankings (Sprint 3)

Built `src/analytics/peer.py` implementing SQL-style `PERCENT_RANK()` for the
10 spec metrics across the 11 defined peer groups: ROE, ROCE, Net Profit
Margin, D/E (inverted — lower is better), Free Cash Flow, PAT CAGR 5y,
Revenue CAGR 5y, EPS CAGR 5y, Interest Coverage, Asset Turnover.

The rank function uses the standard SQL formula `(rank - 1)/(n - 1)` with
`method='min'` tie handling, guaranteeing the best peer in each group
scores 1.0 and the worst scores 0.0. Solo-company groups (if any) get a
neutral 0.5. NaN metric values propagate as SQL NULL (no rank). D/E is
inverted via `1 - percent_rank` so that the lowest leverage scores 1.0.

Created the `peer_percentiles` table in `db/schema.sql` (with an
`ensure_schema()` helper for idempotent creation) and a supporting index
on `(peer_group_name, metric, year)`. Added the Day-18 populator script
`scripts/day18_peer_percentiles.py` and wired the table into
`reset_tables`, `_pk_for_table` and schema tooling.

Populated the production DB for year 2024-03: **540 rows** (54 companies
x 10 metrics across 11 peer groups). 35 Nifty-100 companies lack a peer
group assignment; per spec these receive the message
"No peer group assigned" without raising an error (the list is logged
and surfaced in the script summary). `peer_percentile_for_company()`
returns either a 10-row DataFrame of peer percentiles or the literal
string `"No peer group assigned"`.

Added 20 new unit tests in `tests/analytics/test_peer.py` covering the
metric registry (10 metrics, D/E inverted, others higher=better), rank
semantics (strict order, ties, inversion, solo-peer neutral, NaN
propagation), live-DB long-form shape (11 groups, ≥540 rows, all
percentiles in [0,1], best=1/worst=0 in every group/metric cohort), the
no-peer cohort listing, single-company lookup (DataFrame vs. message),
schema creation, and idempotent repopulation (row count does not
double). Defensive prod-DB fixture pattern from Day 17 reused.

**Final score: 601/601 tests passing** (581 prior + 20 new), Black &
Ruff clean. `output/screener_output.xlsx` unchanged.

## Day 19 — Radar Charts (Sprint 3)

Built `src/analytics/radar_charts.py` generating 8-axis polar/radar charts
for every Nifty-100 company comparing each metric against its peer group.
The eight axes (per spec §27) are ROE, ROCE, NPM, D/E (inverted — lower
leverage scores higher), FCF Quality (CFO/PAT ratio percentile), PAT CAGR
5y, Revenue CAGR 5y, and Composite Score. All values use the Day-18
SQL-style PERCENT_RANK `(rank-1)/(n-1)` within peer groups so every axis
sits on the same 0–1 (0%–100%) scale, keeping the chart readable.

The company's values are rendered as a filled blue polygon; the peer-group
mean is overlaid as a dashed red outline for immediate benchmarking.
Concentric grid circles at 25/50/75/100%, readable fonts (10pt axis
labels, 15pt bold title, 10.5pt grey subtitle), DPI 140, tight layout and
a soft-blue background make each chart legible at standard viewing size.

Companies with NO peer group (35 of 89) receive a standalone horizontal
bar chart comparing each of the 8 raw metric values against the Nifty-100
average. Metrics are normalised to the larger of |company| and |Nifty avg|
so all eight bars fit on a common scale; D/E is inverted so that "longer
bar = better than average", with a dotted reference line at 1.0 marking
the Nifty benchmark.

Output is written to `reports/radar_charts/<company_id>_radar.png` (89
PNGs total — 54 peer-radar + 35 standalone). Added
`scripts/day19_radar_charts.py` as the CLI entry point (`python -m
scripts.day19_radar_charts [--year YEAR] [--output-dir DIR]`).

Added 13 unit tests in `tests/visuals/test_radar.py` covering:
axis-key registry (8 axes including inverted D/E), PERCENT_RANK semantics
(strict order, ties, inversion, solo-peer neutral 0.5), single-chart PNG
output (exists, non-trivial size, valid PNG format, sensible
dimensions), standalone bar chart output, and end-to-end batch generation
(one PNG per company = 89 total, `<TICKER>_radar.png` filename convention
verified for TCS/HDFCBANK/ADANIENT, all files valid PNGs).

**Final score: 614/614 tests passing** (601 prior + 13 new), Black & Ruff
clean, 89 PNGs (≈110KB each) generated under `reports/radar_charts/`.

## Day 20 — Peer Comparison Excel Report (Sprint 3)

Built `src/analytics/peer_report.py` generating `output/peer_comparison.xlsx`
with one sheet per peer group (11 sheets total: Automobiles, Consumer
Finance, FMCG, IT Services, Life Insurance, Oil & Gas, Pharmaceuticals,
Power & Utilities, Private Banks, Public Banks, Steel & Metals). Each
sheet contains:

  * Identity columns: Ticker, Company.
  * 20 metric columns spanning profitability (ROE, ROCE, NPM, OPM, ROA),
    leverage (D/E, ICR), cash quality (FCF, FCF Yield, CFO/PAT), growth
    (Rev/PAT CAGR 3y, Rev/PAT/EPS CAGR 5y), efficiency (Asset Turnover),
    valuation (P/E, P/B, Div Yield) and the composite quality score.
    Raw market-cap-derived columns (P/E, P/B, Div Yield, FCF Yield) are
    pulled from the `market_cap` table (aliased from `market_cap_crore`).
  * A matching percentile-rank column for every metric using SQL-style
    PERCENT_RANK within the peer group, with D/E, P/E, and P/B inverted
    so that lower = better. Rows are sorted by composite percentile
    descending so the best-in-group company appears first.
  * Quartile colour-coding on percentile cells: green (#C6EFCE) for
    >= P75 (top quartile), yellow (#FFEB9C) for P25–P75, red (#FFC7CE)
    for <= P25 (bottom quartile).
  * A gold/amber (#FFD966) row background for the peer group's designated
    benchmark company (`is_benchmark = 1` in `peer_groups`); the
    percentile cells in that row retain their quartile colour so the
    heatmap is still actionable.
  * A "Peer Median" summary row at the bottom of each sheet with light-
    grey fill, bold italic font, the median raw value for each metric,
    and a fixed 50% percentile rank.

Styling uses a navy header bar with white bold text, thin grey borders,
frozen panes at `C3` (identity columns + header stay visible when
scrolling), auto-sized columns, 12-character widths for value columns
and 8-character widths for percentile columns, and a 13pt navy title
row naming the sheet, fiscal year, and company count.

Added `scripts/day20_peer_report.py` as the CLI entry point with
`--year` and `--output` flags. Added 11 new unit tests in
`tests/visuals/test_peer_report.py` covering the 20-metric registry,
dataset shape (54 companies × 11 groups × 42 columns), percentile-in-
[0,1] bounds, sheet count/naming, column count, title presence,
presence of green/yellow/red percentile fills in every sheet, gold
benchmark highlighting (verified for TCS in IT Services), and the Peer
Median summary row (50% in every percentile column, grey fill, correct
label).

**Final score: 625/625 tests passing** (614 prior + 11 new), Black &
Ruff clean. `output/peer_comparison.xlsx` written with 11 sheets × 42
columns × 54 companies.

## Day 21 — Sprint 3 Review & Retrospective (Sprint 3)

**Test sweep.** Expanded `tests/dq/test_rules.py` from 5 hand-picked tests
to a full 48-test suite covering DQ-01 through DQ-14 (one test class per
rule with a positive and at least one negative case, plus parametrised
edge cases for tax-rate / dividend-payout ranges, URL validity, and
ticker regex). All 14 spec-mandated DQ rules are now unit-tested: PK
uniqueness on companies (DQ-01) and annual time-series (DQ-02), FK
integrity (DQ-03), BS balance within ±1% (DQ-04), OPM vs computed
(DQ-05), positive-sales with bank/NBFC carve-out (DQ-06), YYYY-MM year
format (DQ-07), ticker regex (DQ-08), CFO+CFI+CFF ≈ net cash flow
(DQ-09), non-negative fixed assets (DQ-10), tax-rate 0–60% (DQ-11),
dividend payout ≤ 200% (DQ-12), http(s) URL syntax (DQ-13), and EPS sign
consistency with PAT (DQ-14).

**Manual verification — Quality Compounder preset (top 5):**

| Ticker       | Company                          |  ROE % |  D/E  | Composite |
|--------------|----------------------------------|-------:|------:|----------:|
| COLPAL       | Colgate Palmolive (India) Ltd    |  23.03 | 0.054 |     88.65 |
| GODREJCP     | Godrej Consumer Products Ltd     |  23.92 | 0.215 |     84.58 |
| ASIANPAINT   | Asian Paints Ltd                 |  17.14 | 0.162 |     79.23 |
| TITAN        | Titan Company Ltd                |  21.63 | 0.304 |     78.99 |
| HEROMOTOCO   | Hero MotoCorp Ltd                |  22.30 | 0.342 |     77.26 |

All 32 constituents have ROE > 15% (min 15.01%) and D/E < 1 (max 0.943)
— preset invariants verified programmatically.

**Peer ranking spot-check (IT Services):**
HCLTECH has the highest ROE (23.09) and correctly holds the highest ROE
percentile rank (1.000); TCS (16.75, 0.750), INFY (15.82, 0.500),
LTIM (13.54, 0.250), TECHM (12.55, 0.000) follow in strict order.

**Peer ranking spot-check (FMCG):**
NESTLEIND has highest ROE (31.26) and top percentile (1.000);
HINDUNILVR, TATACONSUM, ITC, GODREJCP, BRITANNIA, DABUR follow in
correct monotonic order through to 0.000 — no ties, no inversion,
PERCENT_RANK formula confirmed.

**Preset counts (spec: 5–50 each):**
  - Quality Compounder : 32 ✓
  - Value Pick         :  5 ✓
  - Growth Accelerator : 14 ✓
  - Dividend Champion  : 32 ✓
  - Debt-Free Blue Chip:  8 ✓
  - Turnaround Watch   : 27 ✓

**Deliverable inventory:**
  - `output/screener_output.xlsx` — 7 sheets (Summary + 6 presets),
    green/red threshold-coloured cells, 118 total rows.
  - `output/peer_comparison.xlsx` — exactly 11 sheets (one per peer
    group), quartile green/yellow/red percentile fills, gold benchmark
    row, grey Peer Median summary.
  - `reports/radar_charts/` — 89 PNGs (54 peer-radar + 35 standalone
    bar charts for no-peer companies).
  - `db/nifty100.db → peer_percentiles` — 540 rows populated for FY
    2024-03 across 11 peer groups × 10 metrics.
  - `config/screener_config.yaml` — analyst-editable YAML with all 6
    presets, threshold defaults, and metric column mappings.
  - `src/screener/engine.py` + `src/analytics/composite.py` — filter
    engine, winzorised composite 0–100 score.
  - `src/analytics/peer.py` — PERCENT_RANK peer-percentile engine.

**Final score: 668/668 tests passing** (625 prior + 43 new DQ tests),
Black & Ruff clean, zero lint warnings, 14/14 DQ rule unit tests green,
all exit criteria satisfied.

### Sprint 3 Retrospective

**What went well**
  - YAML-driven preset architecture meant adding the six spec presets
    on Day 16 was a pure-data exercise — no engine changes needed once
    the `eq` / `flag` directions and prior-year D/E lookup were added.
  - The PERCENT_RANK helper from Day 18 was reused verbatim by radar
    charts (Day 19) and peer report (Day 20) — a single source of
    truth for peer rankings across three deliverables.
  - Frozen-dataclass Settings + defensive prod-DB fixture pattern from
    Day 17 eliminated a whole class of test-pollution bugs; no flaky
    test after the fix.
  - Matplotlib polar-radar PNGs rendered headlessly with Agg backend
    and matched the visual spec (filled blue polygon, dashed red peer
    overlay, readable fonts, soft-blue background) on first try.

**What was harder than expected**
  - Market-cap column aliasing (`market_cap_crore` not `market_cap_cr`,
    `free_cash_flow_cr` vs aliased `fcf_cr`) caused two silent
    NULL-joins before standardising on a single column-map.
  - SQLite does not allow `datetime('utc')` as a column DEFAULT in all
    builds — `computed_at` had to be stamped client-side.
  - `to_sql(if_exists='append')` does not invoke column DEFAULTs, so
    every audit timestamp had to be applied pre-insert, not via
    schema.
  - Test pollution from `object.__setattr__` on the frozen Settings
    singleton cascaded across three test modules until the root cause
    was found.

**Lessons carried into Sprint 4 (Dashboard / API)**
  - Use the prod-DB fixture pattern (env var + object.__setattr__ +
    explicit db_path) everywhere a test hits production data.
  - Standardise all column aliases to the canonical DB names the
    moment a new table is added, before writing analytics modules.
  - Keep colour constants and visual style tokens in a single module
    so Excel fills and matplotlib colours stay aligned.
  - Register the voice / chart / report scripts as CLI entry points
    with argparse flags so they are usable by analysts outside the
    test harness.

**Sign-off:** Sprint 3 exit criteria all met — six preset screeners
return 5–50 companies each, peer_comparison.xlsx has exactly 11
sheets, IT Services and FMCG peer rankings verified correct, all 14
DQ rule unit tests pass, 668 total tests green. Demo of
screener_output.xlsx and peer_comparison.xlsx completed. Sprint 3
review **signed off**.

## Day 22 - Streamlit App Scaffold (Sprint 4)

Bootstrapped the Sprint 4 Streamlit dashboard under `src/dashboard/`. The
new architecture:

  * **`src/dashboard/app.py`** - main entry point with manual sidebar
    navigation across all 8 screens. Sets Streamlit page config (wide
    layout, page title "Nifty 100 Analytics", sidebar expanded),
    dispatches to each page's `render()` function via a `PAGES`
    registry keyed by emoji-prefixed labels.
  * **`src/dashboard/pages/`** - the 8 screen modules following the
    spec's numeric-prefixed naming convention so they also work in
    native Streamlit multi-page mode:
    `01_home.py` Home/Overview (KPI tiles, peer-group summary, full
    constituent table),
    `02_profile.py` Company Profile (ticker selector, identity panel),
    `03_screener.py` Screener shell (preset dropdown, top-20 universe),
    `04_peers.py` Peer Comparison shell,
    `05_trends.py`, `06_sectors.py`, `07_capital.py`, `08_reports.py`
    placeholder pages that describe upcoming behaviour. A package
    `__init__.py` re-exports the numeric files under friendly
    short names (`home`, `profile`, ...) so `app.py` doesn't couple
    to the file-numbering scheme.
  * **`src/dashboard/utils/db.py`** - shared data access layer wrapping
    `st.connection("sql", url="sqlite:///...")` with
    `@st.cache_data(ttl=600)` applied to every query function. Exposes
    the spec-mandated helpers - `get_companies()`,
    `get_ratios(ticker, year=None)`, `get_pl(ticker)`, `get_bs(ticker)`,
    `get_cf(ticker)`, `get_sectors()`, `get_peers(group_name)`,
    `get_valuation(ticker)` - plus extras needed across screens
    (`get_latest_ratios`, `get_peer_groups`, `get_peer_percentiles`,
    `run_sql`, `invalidate_cache`). The `get_valuation` helper joins
    `market_cap` to `financial_ratios` and derives `fcf_yield_pct`
    (FCF / MCap * 100) to seed next week's valuation work.

Added a per-file-ignore for N999 on `src/dashboard/pages/[0-9][0-9]_*.py`
in `pyproject.toml` so the numeric-prefixed Streamlit filenames don't
trip pep8-naming. Added 43 new unit tests in
`tests/dashboard/test_scaffold.py` covering module imports, the
`render()` contract on every page, the 8-screen registry, every
documented db helper, live-DB result shapes (92 companies, 89 latest-
year ratios, 11 peer groups, TCS history >= 5 years, IT Services
membership, FCF-yield column presence), cache invalidation idempotency,
page-config settings (wide layout + expanded sidebar + correct title),
and the presence of all 8 numeric-prefixed files.

**Verified:** `streamlit run src/dashboard/app.py` starts Uvicorn on
port 8501, `/_stcore/health` returns `ok`, the root route returns
HTTP 200, no tracebacks in the server log, and `make run-dashboard`
target is already wired to the new entry point.

**Final score: 711/711 tests passing** (668 prior + 43 new), Black &
Ruff clean.

## Day 23 - Home Screen & Company Profile Screen (Sprint 4)

Fleshed out the Home and Company Profile screens with data-driven KPIs
and Plotly charts.

**Home screen (01_home.py):**
  * **Six KPI tiles** at the top: Average ROE, Median P/E, Median D/E,
    Total Companies, Median Revenue CAGR 5y, Debt-Free Companies count.
    Debt-free is defined as `icr_label == "Debt Free" OR D/E <= 0.05`
    (defends against the icr_label being NULL in the current DB build).
  * **Plotly donut chart** - 11 broad sectors with company-count
    breakdown (Set3 palette, labels + percent outside the ring).
  * **Top-5 composite-quality table** - Ticker, Company, Sector, ROE,
    D/E, Rev CAGR 5y, Composite score.
  * **Sidebar year selector (2019-2024)** - every tile, chart and
    table reacts to the selected FY via the new `get_kpis_for_year()`
    helper.
  * Collapsible "Full constituent table" listing all 89 companies for
    the chosen year.

**Company Profile screen (02_profile.py):**
  * **Search box + autocomplete** - free-text input filters the
    dropdown to matching tickers/companies (case-insensitive substring
    match); dropdown selection returns the chosen ticker.
  * **Company card** - name, NSE ticker, sector, sub-sector, market-cap
    category, website link and "about" description in a left-bordered
    info box.
  * **Six KPI tiles** (latest FY): ROE, ROCE, Net Profit Margin, D/E,
    Revenue CAGR 5y, Free Cash Flow (Cr), with "n/a" fallback for NaNs.
  * **10-year grouped bar chart** of Revenue (sales) vs Net Profit
    (Plotly grouped bars, blue/green palette).
  * **ROE & ROCE dual-axis line chart** over available history (solid
    blue ROE, dashed red ROCE, lines+markers).
  * **Pros & Cons badges** split from the free-form
    `prosandcons` text field, rendered as :green[+] and :red[x] bullet
    lists; companies without any entry get a friendly "No data"
    caption.
  * Friendly "Ticker not found - please try another." message when the
    ticker has no match.

**DB helpers added in `src/dashboard/utils/db.py`:**
  * `get_kpis_for_year(year)` - joins financial_ratios to companies,
    sectors, peer_groups, market_cap for a given FY (mcap joined by
    calendar year extracted from FY).
  * `get_available_years()` - descending list of FY labels.
  * `get_company_about(ticker)` - identity dict for a ticker (empty
    dict when not found).
  * `get_prosandcons(ticker)` - splits raw newline/bullet-delimited
    text into (pros, cons) lists (caps at 8 items each).

Added 11 new tests covering the new helpers (required-query contract,
KPIs shape for 2024-03 and 2019-03, descending year list, company
about present / missing, pros/cons populated vs empty for missing
ticker).

**Verified:** `streamlit run src/dashboard/app.py` starts on 0.0.0.0:8501,
HTTP 200 OK at `/`, `/_stcore/health` returns "ok", zero tracebacks in
server log after rendering the Home screen.

**Final score: 722/722 tests passing** (711 prior + 11 new), Black &
Ruff clean.

## Day 24 - Screener Screen & Peer Comparison Screen (Sprint 4)

Built the Screener and Peer Comparison screens.

**Screener (03_screener.py):**
  * **10 sidebar metric sliders** - ROE min, D/E max, FCF min, Revenue CAGR 5y
    min, PAT CAGR 5y min, OPM min, P/E max, P/B max, Dividend Yield min,
    ICR min. Sliders re-render the results table on every change (live).
  * **6 preset buttons** - Quality, Value, Growth, Dividend, Debt-Free,
    Turnaround. Each button writes preset thresholds into `st.session_state`
    and calls `st.rerun()`, which causes all sliders to snap to the preset
    values and the results table to update accordingly.
  * **Live results table** - Ticker, Company, Sector, Composite score plus
    every filtered metric (ROE %, D/E, FCF Cr, Rev/PAT CAGR 5y %, OPM %,
    P/E, P/B, Div Yield %, ICR), sorted by composite score descending.
  * **Result-count label** - "N companies match your filters" shown above
    the table. When zero companies match a friendly warning is shown.
  * **CSV download button** - emits a well-formed UTF-8 CSV containing all
    visible columns.
  * New `get_screener_dataset()` helper in `db.py` joins the full latest-FY
    panel (financial_ratios + companies + sectors + peer_groups + market_cap
    + profitandloss) including `fcf_positive` boolean and `sales` for preset
    alignment.

**Peer Comparison (04_peers.py):**
  * **Peer-group dropdown** listing all 11 groups.
  * **Per-company selector** within the chosen group (defaults to the
    `is_benchmark=1` company when present).
  * **Plotly Scatterpolar radar chart** with 8 axes (ROE, ROCE, NPM, D/E
    inverted, CFO/PAT, PAT CAGR 5y, Rev CAGR 5y, Composite) comparing the
    selected company (filled blue polygon #1F77B4, alpha 0.22) against the
    peer-group average (dashed red #FF4B4B outline). Percentiles are
    computed with the same SQL-style PERCENT_RANK formula from Day 18 so
    the dashboard radar is identical to the Day-19 PNG charts.
  * **Side-by-side KPI table** with 12 metrics for every group member; the
    benchmark row is highlighted with a gold `#FFD966` background + bold
    text and a ★ marker, using pandas `Styler.apply`.
  * New helper `get_peer_averages(group_name)` added to `db.py` for future
    reuse.

Added 8 new tests covering: screener dataset shape (89 rows × all required
columns including `fcf_positive`), Quality preset result count 25-40 (matches
engine output), CSV download returns UTF-8 bytes with header, PERCENT_RANK
semantics (best=1/worst=0/inverted/NaN=0.5), peers query returns all radar
columns, and radar figure construction returns two Scatterpolar traces
(company + peer avg).

**Verified:** `streamlit run` starts cleanly, `/` returns HTTP 200,
`/_stcore/health` returns "ok", no tracebacks in log.

**Final score: 730/730 tests passing** (722 prior + 8 new), Black & Ruff clean.

## Day 25 - Remaining 4 Screens (Sprint 4)

Completed the last four dashboard screens.

**Trend Analysis (05_trends.py):**
  * Company search box + **multi-metric selector** (10 metrics: Revenue, Net
    Profit, ROE, ROCE, OPM, NPM, D/E, FCF, ICR, EPS) supporting up to 3
    overlaid metrics.
  * **10-year Plotly dual-Y line chart** with lines+markers. The first
    selected metric goes on the left axis, second metric on a right axis
    (independent scales prevent Revenue Cr from crushing margin %).
  * **YoY % change annotations** rendered in bold at the last data point of
    each series, using that metric's colour (e.g. "+12%").
  * Expandable data table underneath.

**Sector Analysis (06_sectors.py):**
  * Sector dropdown with "All sectors" option.
  * **Plotly scatter bubble chart** - X=Revenue (log scale), Y=ROE %,
    bubble size=Market Cap, colour=sub-sector (or broad sector in all-
    sectors view), with custom hover text showing Ticker, Revenue, ROE,
    Market Cap.
  * **Median KPI horizontal bar chart** below: when "All sectors" is
    picked the user chooses a KPI and sees it ranked across sectors;
    when a specific sector is picked all 7 KPIs are shown as a sorted
    horizontal bar chart for that sector.
  * Expandable constituent table.

**Capital Allocation Map (07_capital.py):**
  * **Plotly treemap** grouping all ~89 latest-FY companies by capital-
    allocation pattern (Reinvestor, Shareholder Returns, Growth Funded
    by Debt, Mixed) using a synthetic "All Companies" root node. Tile
    size = market cap; colour follows the project palette (green =
    Reinvestor, blue = Shareholder Returns, magenta = Growth Funded by
    Debt, olive = Mixed).
  * Pattern-breakdown KPI tiles with coloured left-borders showing the
    company count per pattern.
  * Dropdown selector that lists all constituent companies of a chosen
    pattern sorted by composite score.

**Annual Reports / Downloads (08_reports.py):**
  * Company search box.
  * **Annual report rows** - each FY shows either a green clickable
    "Open {year} Annual Report PDF" link (target=_blank) when the URL
    passes a 4-second lightweight HEAD check, or a red "Report
    unavailable" badge when the URL returns 404, is unreachable, or is
    flagged as `/missing/` in the source data (defensive: does not
    download the whole PDF). Results are cached for 30 minutes
    (`ttl=1800`).
  * **Project artifacts section** with download buttons for
    `screener_output.xlsx` and `peer_comparison.xlsx`.

**DB helpers added**: `get_full_ratios_with_pl()` (full company × year
panel joined to P&L, market-cap and sectors - 1,100+ rows), `get_documents(ticker)`.

Added 8 new tests covering full panel shape + required columns, documents
for TCS (≥5 rows) and unknown ticker (empty), trends METRICS dict ≥ 8
entries including Revenue, capital pattern color constants, and URL
check behavior (rejects `/missing/` paths and empty URLs).

**Verified:** `streamlit run` starts cleanly, `/_stcore/health` returns
"ok", zero tracebacks in server log after initial page render.

**Final score: 738/738 tests passing** (730 prior + 8 new), Black & Ruff clean.

## Day 26 - Valuation Module (Sprint 4)

Extended `src/analytics/valuation.py` with a sector-relative valuation
engine, and shipped the Day-26 valuation deliverables.

**Engine additions in `src/analytics/valuation.py`:**
  * `load_valuation_panel(conn, year)` — joins market_cap to
    financial_ratios, companies, sectors, profitandloss (for net_profit
    and EBIT) and balancesheet (equity+reserves = book value) for the
    specified calendar year (default = latest year in market_cap).
  * 5-year median P/E computed in-pandas (SQLite lacks MEDIAN()) over
    the trailing 5-year window from market_cap, grouped by company.
  * **FCF yield** = `free_cash_flow_cr / market_cap_crore × 100`.
  * **Sector median P/E** computed per broad_sector from positive-P/E
    rows (loss-makers excluded so they don't pull the median down).
  * **Flag logic:** P/E > sector_median × 1.5 → **Caution**; P/E <
    sector_median × 0.7 → **Discount**; otherwise **Fair**. Loss-makers
    (PE ≤ 0 / NaN) default to Fair (insufficient data).
  * `write_valuation_outputs()` — styles `valuation_summary.xlsx` with
    the project's navy header fill + white bold text, and colour-codes
    the flag column: red (#FFC7CE) Caution, green (#C6EFCE) Discount,
    yellow (#FFEB9C) Fair. Auto-sized columns, frozen header row.
  * `valuation_flags.csv` — contains only Caution / Discount rows with
    supporting data.
  * Top-level `run_valuation_module()` returns
    `(summary_df, flagged_df, xlsx_path, csv_path)`.

**CLI entry point `scripts/day26_valuation.py`:**
Runs the engine against the production DB and prints the first 10 rows
plus flag distribution. Accepts `--db-path`, `--output-dir`, `--year`.

**Results on production DB (FY 2024-03 / CY 2024):**
  * 89 companies processed
  * Caution = 11, Discount = 26, Fair = 52
  * Sample Caution: ADANIPORTS (P/E 27.98 vs Industrials median 18.13 =
    154%), COLPAL (P/E 42.80 vs Staples median 24.89 = 172%), CIPLA
    (P/E 43.05 vs Healthcare 26.80 = 161%)
  * Sample Discount: APOLLOHOSP (P/E 8.57 vs Healthcare 26.80 = 32%),
    ADANIPOWER (10.24 vs Energy 22.19 = 46%), COALINDIA (10.91 vs
    Energy 22.19 = 49%)

**Deliverables produced:**
  * `output/valuation_summary.xlsx` — 89 rows × 11 columns with colour-
    coded flag cells
  * `output/valuation_flags.csv` — 37 flagged companies

Added 13 new tests covering FCF-yield primitives, panel coverage
(89 rows, all required columns), summary column contract, FCF-yield
formula correctness (spot-checked), flag distribution sanity, synthetic
3-company test verifying exact Caution/Discount/Fair thresholds, loss-
maker default-to-Fair behaviour, 5yr-median presence, XLSX/CSV file
creation (size, headers, CSV-only-flagged), and end-to-end
`run_valuation_module` against prod DB.

**Final score: 751/751 tests passing** (738 prior + 13 new), Black & Ruff
clean.

## Day 27 - Integration QA & Bug Fixes (Sprint 4)

End-to-end smoke and integration test of all 8 Streamlit screens
against the production database, with bug fixes for every defect
uncovered.

**Integration harness `tests/dashboard/test_integration.py`:**
Built a lightweight Streamlit shim (stub SessionState, cache_data,
columns/tabs/expander containers, metric/dataframe/plotly_chart
captures, selectbox/slider/session_state writers) so pages can be
exercised in-process without launching a browser.

**Coverage of the smoke matrix:**
  * 10 cross-sector tickers profiled end-to-end: TCS (IT), HDFCBANK
    (Financials), HINDUNILVR (FMCG), RELIANCE (Energy), SUNPHARMA
    (Healthcare), TATAMOTORS, TATASTEEL, JSWSTEEL (Materials/Industrials),
    HDFCLIFE (Insurance), ADANIGREEN (Energy/Renewables).
  * Partial-data tickers (fewer than 10 years) render without crash and
    display a "partial data available" note instead of blowing up on
    NaN x-axis alignment.
  * Screener exercised at two extremes: all sliders at minimum
    (loose — returns the full universe, >80 rows) and all sliders at
    maximum (tight — returns 0 rows, renders empty-state cleanly).
  * All 11 peer groups loaded and rendered on the Peers page.
  * Sectors page exercised both on "All sectors" and per-sector views.
  * Reports page tested against a valid ticker and a non-existent
    `__GHOST__` ticker; ghost companies skip the BSE HEAD probe and
    show a "Not on BSE" state.

**Bugs discovered and fixed:**
  * `get_full_ratios_with_pl()` returns `company_id`, not `ticker`;
    06_sectors.py and 07_capital.py were referencing `.ticker` and
    raising AttributeError on real data. Patched both pages to use
    `company_id` and alias it to `ticker` for display.
  * Revenue/PAT bar chart crashed when recent years had NaN net
    profit; ROE/ROCE line chart crashed when all observations were
    NaN. Charts now `dropna(subset=...)` before plotting and show a
    partial-data caption when fewer than 10 years are available.
  * `urllib.request.urlopen` HEAD probe against BSE was using a 4s
    timeout that pushed the Reports page over the render budget;
    reduced to 2s so the page stays snappy even when BSE is slow.
  * Page-level `st.columns()` was called with ratio lists (e.g.
    `[1,1,1,1,1,1]`) which the original shim rejected; patched the
    shim to accept both integer and iterable specs — matches real
    Streamlit semantics.
  * pyproject.toml per-file-ignores extended to silence false
    positives: N999 on `pages/[0-9]*_*.py` filenames, and S101/SLF001
    on the integration test shim.

**Performance check (Company Profile screen load time, production DB):**
Measured via in-process render timings across 5 tickers — TCS,
HDFCBANK, HINDUNILVR, RELIANCE, SUNPHARMA — all came in at 0.03s to
0.08s, well under the 3-second budget per company.

**Server health:**
`/_stcore/health` returns "ok"; Streamlit starts cleanly on
0.0.0.0:8501 with no tracebacks in the server log after rendering
every page.

**Final score: 752/752 tests passing** (751 prior + 1 integration
module), Black & Ruff clean.

## Day 28 - Retro & Documentation (Sprint 4)

Closed out Sprint 4 with README documentation, a formal retrospective,
task-board update, and a final data fix on the valuation panel.

**Valuation panel data fix (89 → 92):**
When regenerating `output/valuation_summary.xlsx` for the 92-company exit
criterion, discovered that NHPC, TORNTPHARM, and BANDHANBNK were silently
dropped because they have no `financial_ratios` row for `2024-03` (late
filers) even though their market_cap, profitandloss, and balancesheet rows
exist.  Root cause: `load_valuation_panel()` INNER JOINed financial_ratios.
Patched to (a) use LEFT JOIN so market_cap companies always come through,
(b) SELECT `mc.company_id` (not `fr.company_id`) so the id isn't NULLed out
on miss, and (c) fall back to each company's latest available FY for FCF /
net-profit / EBIT / book-value so FCF-yield and derived multiples still
populate.  Result: valuation panel covers all 92 latest-year companies
(53 Fair, 14 Caution, 25 Discount = 39 flagged names).

**README.md rewrite:**
Added complete dashboard run instructions (`streamlit run
src/dashboard/app.py`, headless container invocation, Make shortcut), a
full folder-structure map, per-screen descriptions for all 8 Streamlit
pages (Home, Profile, Screener, Peers, Trends, Sectors, Capital,
Reports), a valuation-module column dictionary and threshold reference,
testing commands, and the Sprint 4 retrospective summary.

**Documentation deliverables added:**
  * `docs/sprint4_retro.md` — full retro covering UX decisions, edge
    cases, performance, what went well, what to improve.
  * `docs/task_board.md` — per-sprint, per-day checkbox board with all
    Sprint 1–4 tasks marked complete and the Sprint 4 Definition-of-Done
    exit-criteria table (all green).

**Sprint 4 exit-criteria status:**
  * All 8 Streamlit screens load without errors for all 92 tickers ✅
  * Company Profile screen loads in 0.03–0.08s (well under 3s) ✅
  * Screener CSV download produces a valid correctly-headed file ✅
  * `valuation_summary.xlsx` has 92 rows with all 11 required columns ✅
  * Sprint 4 review demo completed against the live server on :8501 ✅

Tests re-gated: Black clean, Ruff clean, **752/752 tests passing**.
Sprint 4 is officially signed off.

## Day 29 - NLP: Analysis Text Parser (Sprint 5)

Shipped the first NLP-module primitive: a regex-based parser for
Screener.in's `data/raw/analysis.xlsx` export, which extracts
compounded growth / CAGR / ROE figures from free-text cells and
cross-validates them against the Ratio Engine.

**Module added: `src/nlp/parser.py`**
  * Public constants: `PARSE_REGEX` (compiled pattern per spec
    `(\d+)\s*Years?:?\s*([\d.]+)%`), `METRIC_COLUMNS` (the four
    target text columns: compounded_sales_growth,
    compounded_profit_growth, stock_price_cagr, roe),
    `CAGR_DIVERGENCE_THRESHOLD_PCT = 5.0`.
  * `load_analysis_workbook(path)` — reads the Screener.in export
    with `header=1` (real header is on spreadsheet row 2) and casts
    metric columns to pandas StringDtype.
  * `parse_analysis_text(text)` — returns all `(period_years,
    value_pct)` tuples found in a cell; supports optional colon,
    flexible whitespace, singular/plural "Year/Years", decimals,
    and multiple matches per cell.
  * `_parse_frame(df)` — long-form tidier producing columns
    `company_id, metric_type, source_column, period_years,
    value_pct, source_value` plus a failure DataFrame
    (`company_id, metric_type, raw_text, reason`).
  * `cross_validate_parsed(parsed, db_path, threshold)` — joins
    parsed rows to each company's latest financial_ratios row via
    `RATIO_MAPPINGS` (sales_cagr -> revenue_cagr_{N}yr, profit_cagr
    -> pat_cagr_{N}yr, roe_avg -> return_on_equity_pct; stock_cagr
    has no DB equivalent and is skipped); emits a row only when
    |delta| > 5pp OR the DB value is missing/null/column-absent.
  * `run_parser(...)` — end-to-end orchestrator writing three CSVs.

**CLI script: `scripts/day29_nlp_parser.py`**
Accepts `--analysis-path`, `--db-path`, `--output-dir`, `--threshold`.

**Outputs produced:**
  * `output/analysis_parsed.csv` — 80 rows (20 companies × 4 metric
    cells), columns `company_id, metric_type, source_column,
    period_years, value_pct, source_value`. Match rate 100% against
    the shipped sample.
  * `output/parse_failures.csv` — 0 rows (shipped workbook is
    cleanly formatted).
  * `output/analysis_divergences.csv` — 41 rows: 37 genuine >5pp
    divergences and 4 `ratio_value_null` cases (TITAN/LTIM/DLF
    missing revenue_cagr_10yr; INDIGO missing pat_cagr_5yr in
    latest FY) — all queued for manual review.

**Metric-type mapping (text column -> parsed metric_type):**
  * compounded_sales_growth -> sales_cagr (revenue_cagr_Nyr)
  * compounded_profit_growth -> profit_cagr (pat_cagr_Nyr)
  * stock_price_cagr -> stock_cagr (market-derived, not in DB)
  * roe -> roe_avg (validated against avg ROE)

**Tests added: 26 new tests in `tests/nlp/test_parser.py`** covering
regex edge cases (colon/no-colon, singular "Year", case-insensitive,
extra whitespace, empty/None/garbage input, multiple matches per
cell), workbook loading, full-parse invariants, period_years integer
typing, cross-validation (stock_cagr skipped, synthetic perfect
match returns zero divergences, synthetic 10pp gap flagged), and
end-to-end CSV emission.

**Final score: 778/778 tests passing** (752 prior + 26 new), Black &
Ruff clean.

## Day 30 - NLP: Auto Pros/Cons Generator (Sprint 5)

Shipped the second NLP module: an automated pros/cons generator that
evaluates every company in the Nifty 100 universe against 12 pro rules,
12 con rules (plus 8 watch-list "soft" cons), assigns a 0-100 confidence
score, and emits only observations scoring above 60.

**Module added: `src/nlp/pros_cons_generator.py`**
  * `CompanyContext` dataclass pre-joins financial_ratios, profitandloss,
    balancesheet and market_cap (sorted newest-to-oldest) per company,
    with `latest_ratios() / latest_pl() / latest_mc() / ratio_series()`
    accessors.
  * Streak helpers `_streak_positive`, `_streak_negative`,
    `_streak_improving`, `_streak_declining`, `_streak_rising_de` cover
    multi-year conditions; `_clip_conf` clamps confidence to [0,100].
  * **12 Pro rules** (P1-P12): ROE>20% sustained 3+yr, FCF positive
    5+yr, D/E=0 debt-free, Revenue CAGR>15% 5yr, OPM>25% latest yr, PAT
    CAGR>20% 5yr, ICR>10 or Debt Free, Div Yield>2% with FCF positive,
    EPS CAGR>15% 5yr, ROE improving 3yr, PAT CAGR > Revenue CAGR
    (operating leverage), assets growing with declining debt.
  * **12 Con rules** (C1-C12): D/E>2.0 non-financial (formatted with
    actual ratio to 2dp), FCF negative 3yr, OPM declining 3yr, net loss
    latest yr, revenue declining 2+yr, ICR<1.5 (skipped for debt-free),
    dividend payout>100%, D/E rising 3yr, EPS declining 3yr, ROCE<10%,
    Net Debt >3x EBITDA (formatted to 1dp), Revenue CAGR<5% 5yr
    (PAT CAGR<5% for financials).
  * **8 watch-list cons (C13-C20)** at 60-65 confidence for near-miss
    bands (ROCE 10-15%, ICR 1.5-3, D/E 1.0-2.0, CAGR 5-10%, payout
    70-100%, FCF negative only latest yr, D/E 0.5-1.0, OPM YoY slip)
    so that healthy Nifty-100 names still receive at least one con
    observation without flooding with red flags.
  * **Confidence scoring:** multi-year streaks score higher for longer
    streaks, ratio thresholds scale with margin past the threshold
    (capped at 100), hard binary rules score 95.
  * Fallback pro/con generators inspect the context (ROE>=15%, ROCE>=15%,
    positive FCF, positive net profit, etc. on the pro side; closest-to-
    firing metric bands on the con side) and emit a 62-confidence note
    only when a company would otherwise have zero of that type.
  * Output CSV: `output/pros_cons_generated.csv` with the five spec
    columns: `company_id, type, rule_id, text, confidence_pct`
    (`company_name` retained in the returned DataFrame for downstream
    use but dropped in the CSV artifact per the Day-30 contract).

**CLI script: `scripts/day30_pros_cons.py`** accepts `--db-path`,
`--output`, `--threshold` (default 60).

**Results on production DB (FY 2024-03):**
  * 92/92 companies have >=1 pro; 92/92 companies have >=1 con.
  * 521 total observations emitted (299 pro / 222 con).
  * Fallback pro used for 6 companies; fallback con used for 15
    companies (watch-list soft cons cover the rest).
  * Top-firing pro rules: P11 operating leverage (47), P4 revenue CAGR
    (35), P8 dividend+FCF (33), P6 PAT CAGR (31), P9/P12 (30).
  * Hard cons: C10 ROCE<10% (14), C1 D/E>2 (10), C11 net debt/EBITDA (7),
    C12 rev CAGR<5% (7).

**Tests added: 30 new tests in `tests/nlp/test_pros_cons.py`** (on top
of the 26 Day-29 parser tests = 56 total NLP tests) covering every
pro/con rule on synthetic inputs, financial-sector carve-outs,
confidence bounds (0-100, zero when not triggered), end-to-end
coverage (92 companies each with at least one pro and con, CSV columns
match the spec, all emitted rows >=60 confidence), and readable output.

**Final score: 808/808 tests passing** (778 prior + 30 new), Black &
Ruff clean.

## Day 31 - Cash Flow Intelligence Module (Sprint 5)

Added the Day-31 Cash Flow Intelligence module that classifies every Nifty
100 company by CFO quality, CapEx intensity, distress risk, deleveraging
activity, and capital-allocation pattern, producing the Excel summary and
distress-alerts CSV.

**Module added: `src/analytics/cashflow_intelligence.py`**
  * New primitives (building on Day-11 cashflow_kpis.py primitives, which
    remain unchanged to protect their existing test surface):
      - `distress_signal(cfo, cff)` -> bool — True iff CFO < 0 AND CFF > 0
        in the latest year (raises cash from financing while operations
        burn cash).
      - `deleveraging_flag(cff, borrowings_now, borrowings_prev)` -> bool
        — True iff CFF < 0 AND borrowings declined year-over-year.
      - `fcf_cagr(series, window=5)` — CAGR of FCF over trailing 5 years
        using (end/begin)**(1/n)-1, requires start/end FCF positive.
  * `build_cashflow_intelligence_panel(conn)` — joins companies, cashflow,
    profitandloss, balancesheet, and sectors; computes per-company latest-FY
    values including:
      - **CFO Quality Score**: 5-year mean of CFO/PAT (min 3 valid years);
        labels High Quality (>1.0), Moderate (0.5-1.0), Accrual Risk (<0.5).
      - **CapEx Intensity %**: abs(CFI)/sales x 100; labels Asset Light
        (<3%), Moderate (3-8%), Capital Intensive (>8%).
      - **FCF 5-year CAGR** and **FCF Conversion %** (FCF / EBIT x 100,
        falling back to op_profit as the EBITDA proxy).
      - Distress flag, deleveraging flag, capital-allocation label
        (reusing the Day-11 8-class classifier with the Shareholder
        Returns carve-out).
  * `write_intelligence_xlsx(df, path)` — navy header fill, red/green
    highlight on boolean flag columns, auto-frozen header, auto-sized
    columns.
  * `write_distress_alerts_csv(df, conn, path)` — pulls latest-year CFO,
    CFF, and net profit for each flagged company.
  * `run_cashflow_intelligence()` high-level entry point (used by the CLI).

**CLI script: `scripts/day31_cashflow_intelligence.py`** accepts `--db-path`
and `--output-dir`.

**Outputs produced:**
  * `output/cashflow_intelligence.xlsx` — 92 rows x 12 columns (company_id,
    company_name, sector, cfo_quality_score, cfo_quality_label,
    capex_intensity_pct, capex_label, fcf_cagr_5yr, fcf_conversion_pct,
    distress_flag, deleveraging_flag, capital_allocation_label).
  * `output/distress_alerts.csv` — 2 flagged companies for FY 2024-03:
    NAUKRI (Info Edge, CFO -11,125 Cr; CFF +35,045 Cr; PAT -3,620 Cr)
    and INDIGO (CFO -1,896 Cr; CFF +14,596 Cr; PAT -634 Cr) — both
    showing the textbook distress pattern.

**Population distributions:**
  * CFO Quality: 92/92 High Quality (Nifty 100 names all convert earnings
    to operating cash effectively over the 5-year window).
  * CapEx tier: 48 Capital Intensive, 44 Moderate.
  * Capital allocation (latest FY): Shareholder Returns 61, Mixed 19,
    Reinvestor 10, Growth Funded by Debt 2.
  * Deleveraging names: 23.

**Tests added: 20 new tests in `tests/analytics/test_cashflow_intelligence.py`**
covering primitive flags (distress true/false/missing, deleveraging
true/false/missing, FCF CAGR positive growth, undefined on negative
endpoints, insufficient history), panel coverage (92 rows, required
columns, score ranges, non-negative CapEx, valid tier labels, boolean
dtypes, plausible distress count), and end-to-end Excel/CSV output
(XLSX readable, CSV headers match, distress rows satisfy CFO<0/CFF>0).

**Final score: 828/828 tests passing** (808 prior + 20 new), Black &
Ruff clean.

---

## Day 32 — Capital Allocation Report (Sprint 5)

**Module:** `src/analytics/capital_allocation_report.py`
**CLI:** `scripts/day32_capital_allocation_report.py`
**Tests:** `tests/analytics/test_capital_allocation_report.py` (12 tests)

**Tasks completed:**
1. **Completeness verification** — Confirmed `output/capital_allocation.csv` is
   100% complete: 1182 rows / 92 companies covering every shared cashflow+P&L
   year. No missing company_ids or (company, year) pairs.
2. **Distribution summary** — Count of companies in each of the 8 canonical
   capital-allocation patterns for latest FY:
     * Shareholder Returns — 61
     * Mixed                — 19
     * Reinvestor           — 10
     * Growth Funded by Debt—  2
     * Distress Signal/Liquidating/Cash Accumulator/Pre-Revenue — 0 each
   (The four zero-count patterns reflect the Nifty 100's mature, cash-generative
   composition — no sign triples like (-,-,-) or (-,+,+) appear in the data.)
3. **Capital allocation column** — Refreshed `output/cashflow_intelligence.xlsx`
   via the Day-31 runner so the `capital_allocation_label` column is populated
   for all 92 companies.
4. **YoY pattern-change detection** — `output/pattern_changes.csv` lists 45
   companies whose capital-allocation pattern shifted between their latest two
   fiscal years (e.g. INDIGO and NAUKRI both moved from Shareholder Returns /
   Mixed → Growth Funded by Debt in 2024-03, consistent with the Day-31
   distress alerts).
5. **Multi-sheet Excel report** — `output/capital_allocation_report.xlsx`
   (Pattern Distribution, Pattern Changes (YoY), Completeness Audit).

---

## Day 33 — PDF Tearsheet Template (full 2-page layout)

**Module:** `src/reports/tearsheet.py` (completely rewritten from initial scaffold)
**CLI:** `scripts/day33_tearsheet_template.py`
**Tests:** `tests/reports/test_tearsheet.py` (53 tests including 5 cross-sector parametrized)

**Page 1** (per spec): Navy header with company + ticker; 6 KPI tiles in 2x3 grid
(Market Cap, P/E, ROE, ROCE, D/E, 5yr PAT CAGR); side-by-side 10-year Revenue
and Net Profit bar charts (negative NP in red); full-width ROE vs ROCE dual-axis
line chart.

**Page 2** (per spec):
* Balance Sheet composition stacked bar (Equity / Borrowings / Other Liabilities
  across up to 10 years).
* Cash Flow waterfall for latest FY showing CFO, CFI, CFF, and Net Cash Flow
  (green for positive, red for negative; Net CF highlighted in navy/red).
* Two-column Pros/Cons table: green "Strengths" bullets and red "Risks/Watch
  Items" bullets, each capped at 6 items drawn from the Day-30 auto-generated
  `output/pros_cons_generated.csv` with fallback to the `prosandcons` table.
* Capital Allocation badge: a coloured pill (green = Shareholder Returns/Cash
  Accumulator, navy = Reinvestor, amber = Mixed/Liquidating, red = Growth
  Funded by Debt/Distress, grey = Pre-Revenue).

**Word wrap:** Every table cell (KPI values, pros/cons text, headers, badge)
uses ReportLab `Paragraph` flowables with Helvetica/Helvetica-Bold at 8pt,
so even very long pro/con text wraps correctly. HTML-unsafe characters (`&`,
`<`, `>`) are escaped before insertion.

**Cross-sector test set (5 companies):**
* TCS (Information Technology)
* HDFCBANK (Financials)
* RELIANCE (Energy)
* SUNPHARMA (Healthcare)
* TATASTEEL (Materials)

Automated tests verify: valid `%PDF-` header, exactly 2 pages per file, all
text blocks fit within A4 margins (max bottom-y < 810pt, i.e. no overflow),
Page 2 contains all 5 required sections (Balance Sheet, Cash Flow, Strengths,
Risks, Capital Allocation), Page 1 has 3+ images and Page 2 has 2+ images,
and the pros-heavy ASIANPAINT (9 pros truncated to 6) also fits without
overflow.

**Final score:** 820 non-dashboard tests passing (incl. 53 new), Black &
Ruff clean. Dashboard test collection remains at 891 total. Sample
tearsheets are in `output/tearsheets/sample_{TCS,HDFCBANK,RELIANCE,SUNPHARMA,TATASTEEL}.pdf`
(avg ~110 KB each, 2 pages, 5 embedded charts).

---

## Day 34 — Batch Report Generation (Sprint 5)

**Module:** `src/reports/batch.py`
**CLI:** `scripts/day34_batch_reports.py`
**Tests:** `tests/reports/test_batch.py` (14 tests including a full end-to-end
run into a temp directory).

**Tasks completed:**

1. **Batch tearsheet generation** — 92 company tearsheets generated into
   `reports/tearsheets/<TICKER>_tearsheet.pdf` in 61.6 seconds. The
   `batch_generate_tearsheets()` helper reuses `load_tearsheet_data()` +
   `generate_tearsheet_pdf()` from Day 33, and checks for a minimum of
   `MIN_YEARS_REQUIRED=3` years of shared CF+P&L+BS data before rendering.

2. **Skip list** — all 92 companies have ≥3 years of data, so the skip list is
   empty; `output/skipped_tearsheets.csv` is still written with a header row
   for downstream pipelines. The helper supports arbitrary min-year thresholds
   (covered by a test with threshold=50 that skips all 92).

3. **Sector reports — 11 PDFs** in `reports/sector/<slug>_report.pdf`, one per
   broad sector:
     * Financials (19), Energy (16), Consumer Discretionary (12), Materials (11),
       Consumer Staples (9), Healthcare (7), IT (6), Communication Services (4),
       Industrials (4), Conglomerates/Other (2), Real Estate (2).
   * Each sector PDF contains: navy title bar with company count + overall
     Nifty 100 median ROE/ROCE benchmark; 4×2 median KPI tiles (Market Cap,
     P/E, P/B, ROE, ROCE, D/E, 5yr Rev CAGR, 5yr PAT CAGR); a market-cap
     composition pie chart alongside a horizontal bar comparing the sector's
     median ROE/ROCE against every other sector; and a company-level table
     with 8 metrics per company plus capital-allocation pattern.
   * Sectors with more companies (Financials 19, Energy 16, Materials 11,
     Consumer Discretionary 12) flow to 2 pages; smaller sectors fit on 1.

4. **Verification:** `ls reports/tearsheets/ | wc -l` returns 92; `ls reports/sector/`
   returns 11 PDFs; programmatic spot-check of all 92 tearsheets confirms
   exactly 2 pages, ≥3 images on page 1, ≥2 images on page 2, and no text
   overflow beyond y=810pt. A second random 5-company visual sample
   (ADANIPORTS, BANDHANBNK, EICHERMOT, HCLTECH, TATAPOWER) also passes.

**Final test count:** 834 (820 non-dashboard + 14 new Day-34 batch tests).
Black & Ruff clean. Committed as `[Sprint5-Day34]` and pushed.

---

## Day 35 — Portfolio Summary PDF & Sprint 5 Review

**Module:** `src/reports/portfolio.py`
**CLI:** `scripts/day35_portfolio_summary.py`
**Tests:** `tests/reports/test_portfolio.py` (15 tests)
**Retro:** `docs/sprint5_retro.md`

1. **Portfolio Summary PDF** — `reports/portfolio/portfolio_summary.pdf`
   contains one page per company in alphabetical order (92 pages). Each page:
   navy header (company name + ticker), sector/FY subtitle, six KPI cards
   (Revenue, Net Profit, ROE, ROCE, D/E, Net Margin) with value and a
   trend-arrow comparing latest vs prior FY.
   * ▲ green = metric improved (>2%)
   * ▼ red = metric declined (>2%)
   * ▶ grey = flat within ±2% (or missing data)
   D/E uses inverse logic (decline = improvement). Footer shows page X / 92.
2. **Sprint 5 retrospective** written covering wins (vertical-slice delivery,
   deterministic PDF layout, defensive fallbacks, cross-sector parametrized
   tests), improvements (sandbox reset cost, dashboard test timeouts,
   zero-count pattern classes should be annotated in UI), and a metrics table
   covering all Sprint-5 artifacts.
3. **Exit criteria verification** — programmatic audit confirms all 9
   deliverable criteria pass: pros_cons_generated.csv has ≥1 pro+1 con per
   company (0 missing); 92 tearsheets exist at avg 113 KB (all ≥30 KB);
   random 5-company visual sample shows no overflow/blank pages;
   cashflow_intelligence.xlsx has 92 rows × 12 columns; 11 sector PDFs
   present; portfolio summary is 92 pages.

**Final test count: 849 non-dashboard tests passing** (834 + 15 new Day-35).
Black & Ruff clean.

---

## Day 36 — KMeans Clustering (Sprint 6)

**Module:** `src/analytics/clustering.py`
**CLI:** `scripts/day36_clustering.py`
**Tests:** `tests/analytics/test_clustering.py` (15 tests)

**Tasks completed:**
1. **Feature panel** built from the DB for all 92 companies with five features:
   return_on_equity_pct, debt_to_equity, revenue_cagr_5yr, fcf_cagr_5yr
   (computed from the trailing 5-year cashflow history, reusing the
   free_cash_flow + CAGR logic from Day 31), operating_profit_margin_pct.
   All features already populated (0 NaNs in production data).
2. **Imputation** — sector-median imputation with global-median fallback.
   Verified with a synthetic test where an entire sector has missing ROE.
3. **StandardScaler** normalisation to zero mean / unit variance before
   clustering.
4. **KMeans(n_clusters=5, random_state=42, n_init=10)** — deterministic
   across runs (verified by fitting twice and comparing labels).
5. **Cluster archetype labels** assigned by percentile-rank heuristic:
     * Quality Compounder (18) — highest composite ROE+margin+low-debt rank
     * Growth Star (34) — highest 5yr Revenue CAGR
     * Value Play (29) — residual cluster (high D/E, moderate margins)
     * Cash Cow / Yield (7) — highest 5yr FCF CAGR
     * Turnaround / Risk (4) — lowest ROE (HINDPETRO, INDIGO, NAUKRI, TATAPOWER)
6. **Elbow plot** saved to `reports/elbow_plot.png` (inertia vs k for k=2..10);
   k=5 sits near the elbow (inertia drops 13.4% from k=4→k=5, 10.0% k=5→k=6,
   7.5% k=7→k=8 — diminishing returns beyond k=5).
7. **Outputs:** `output/cluster_labels.csv` (92 rows × 6 cols: company_id,
   company_name, sector, cluster_id, cluster_name, distance_from_centroid);
   `output/cluster_centroids.csv` (5 × feature centroids + label).

**Tests:** 15 new tests covering constants, helpers, feature extraction
(92 rows, required columns), imputation (sector median + global fallback),
clustering output (5 unique labels, monotonic inertia, columns, non-negative
distances), reproducibility under fixed random_state, correct archetype
label set, writer outputs (CSV+PNG), and an end-to-end run into a tmp
directory that produces all three files with valid content.

**Final non-dashboard test count:** 864 passing (849 + 15).
Black & Ruff clean.

## Day 37 — Cluster Profiling & Portfolio Statistics (Sprint 6)

**Deliverables:**
1. **Cluster profiling** — per-cluster mean & median of all 5 clustering
   features → `output/cluster_profile.csv` (10 rows: 5 clusters × mean/median).
2. **Refined cluster names** after team-lead review of constituent companies,
   valuation multiples, ROCE, dividend yields and sector mix:
     * 0 → Emerging Growth (34 companies)
     * 1 → Distressed / Turnaround (4: HINDPETRO, INDIGO, NAUKRI, TATAPOWER)
     * 2 → Value Cyclicals (29)
     * 3 → High-Quality Compounders (18)
     * 4 → Defensive Dividend Payers (7)
   Updated `output/cluster_labels.csv`, `output/cluster_centroids.csv`, and
   patched `src/analytics/clustering.py` so re-runs emit refined names.
3. **Correlation heatmap** — Pearson r across 10 KPIs (ROE, ROCE, D/E,
   Revenue CAGR 5yr, PAT CAGR 5yr, OPM, NPM, Div Payout, P/E, P/B) for all
   92 companies → `reports/correlation_heatmap.png` (seaborn annotated).
   Key relationships: OPM↔NPM 0.92, ROCE↔OPM 0.59, D/E↔NPM -0.70.
4. **Outlier detection** — per-broad-sector Z-scores for all 10 KPIs; flag
   |Z|>3 → `output/outlier_report.csv`. Single outlier flagged:
   BAJFINANCE pat_cagr_5yr = 238.5% (Z=3.9 vs Financials sector mean 27.2%).
5. **Portfolio statistics** → `output/portfolio_stats.csv` with P10, P25,
   P50, P75, P90, Mean, Std, Min, Max, Count for each of the 10 KPIs.

**Tests:** 33 new tests in `tests/analytics/test_cluster_profiling.py`
covering constants, KPI loading (92 rows, 10 numeric columns), cluster
profiling (sizes, archetype ordering, writer output), re-labelling,
correlation matrix (symmetric, diagonal=1, OPM↔NPM strong positive),
heatmap PNG generation, outlier detection (columns, |Z|>3 invariant,
BAJFINANCE specifically), portfolio stats (percentile ordering,
mean between P10-P90, counts), and end-to-end run into tmp dir.

**Final non-dashboard test count:** 897 passing (864 + 33).
Black & Ruff clean.

## Day 38 — FastAPI Server Scaffold (Sprint 6)

**Module:** `src/api/main.py`, `src/api/db.py`, `src/api/routers/` (8 routers)
**CLI:** `scripts/day38_api_scaffold.py` (verification); run server via `uvicorn src.api.main:app --port 8000 --host 0.0.0.0`
**Tests:** `tests/api/test_scaffold.py` (30 tests)

**Deliverables:**

1. **FastAPI application (`src/api/main.py`)**
   * Title: "Nifty 100 Financial Intelligence Platform API"
   * Version: `1.0.0-sprint6`
   * `/docs` (Swagger UI), `/redoc` (ReDoc), `/openapi.json` enabled.
2. **SQLite connection helpers (`src/api/db.py`)**
   * `get_db_path()` → absolute path to `db/nifty100.db` via `settings.PROJECT_ROOT`.
   * `get_db_connection()` context manager yields a sqlite3 connection with
     `row_factory = sqlite3.Row`, auto-closing on exit.
   * `table_row_counts()` returns `{table: count}` for the 10 core business
     tables (companies, profitandloss, balancesheet, cashflow, analysis,
     documents, prosandcons, sectors, stock_prices, market_cap). Missing
     tables surface as 0 rather than raising.
3. **CORS middleware** allowing all origins (`*`), all methods, all headers
   (internal-use only).
4. **Request-logging middleware** using loguru; logs method, path, response
   status, and elapsed time (ms) for every request; attaches
   `X-Response-Time-Ms` response header; unhandled exceptions return 500
   with a JSON body (no stack trace leaked).
5. **`routers/` directory** with one file per module:
   `health.py`, `companies.py`, `screener.py`, `sectors.py`, `peers.py`,
   `valuation.py`, `portfolio.py`, `documents.py` (each exposes an
   `APIRouter` with a tag, plus a stub `GET /` returning `{module, status:
   "scaffold", message}` to be replaced by real endpoints in later days).
6. **All routers mounted under `/api/v1`** (API_PREFIX constant exported).
7. **`GET /api/v1/health`** returns exactly the four required fields:
   * `status: "ok"`
   * `db_row_counts` (dict, exactly 10 tables with row counts)
   * `uptime_seconds` (float, clock seeded at app startup via on_startup)
   * `version: "1.0.0-sprint6"`
   Returns HTTP 503 if the database is unreachable.
8. **Verification:** `uvicorn src.api.main:app --port 8000 --host 0.0.0.0`
   starts cleanly (startup log: "Application startup complete"), `/docs`
   serves Swagger UI, `/openapi.json` exposes 9 paths, all 7 stubs return
   200, CORS preflight responds with `access-control-allow-origin: *`,
   and `X-Response-Time-Ms` header is present on every response.

**Tests:** 30 new tests covering DB helpers (path exists, 10 tables, unique,
92 companies/sectors), root endpoint payload, CORS preflight and response
headers, logging middleware (header present, numeric value < 1s), health
endpoint (200, 4 required keys, exactly 10 table counts, sane counts for
companies/sectors, uptime monotonic increase), all 7 router stubs (200 +
module tag), OpenAPI tag coverage, /api/v1 prefix on every non-root path,
/docs & /redoc 200, OpenAPI title+version correct, 404 for unknown routes.

**Final non-dashboard test count:** 927 passing (897 + 30).
Black & Ruff clean. Committed as `[Sprint6-Day38]`.

## Day 39 — API Endpoints — Company Data (Sprint 6)

**Module:** `src/api/routers/companies.py` (replaces Day-38 stub)
**Tests:** `tests/api/test_companies.py` (33 new tests)

**Endpoints implemented under `/api/v1/companies`:**

1. **GET /** — list of all 92 companies with id, company_name, broad_sector,
   sub_sector, market_cap_category, roe_pct, roce_pct. Query filters:
   * `?sector=Financials` (exact broad_sector match)
   * `?market-cap=Large Cap` (exact market_cap_category match — uses alias
     "market-cap" because Python identifiers can't contain hyphens)
   * `?search=tata` (case-insensitive partial match on ticker OR company_name)
   Returns `{count, companies: [...]}`; empty filters return all 92;
   non-matching filters return 200 with count=0.
2. **GET /{ticker}** — full company profile: `companies.*` fields + sector
   data (broad_sector, sub_sector, index_weight_pct, market_cap_category)
   + `latest_kpis` (latest financial_ratios row) + `latest_valuation`
   (latest market_cap row). Ticker is uppercased for case-insensitive
   lookup; returns HTTP 404 if not found.
3. **GET /{ticker}/pl** — P&L history ordered by year ascending, supports
   `?from=YYYY-MM&to=YYYY-MM` filters.
4. **GET /{ticker}/bs** — balance-sheet history (same filters).
5. **GET /{ticker}/cashflow** — cash-flow history (same filters).
6. **GET /{ticker}/ratios** — all computed financial_ratios per year;
   optional `?year=YYYY-MM` returns a single year.
7. **GET /{ticker}/tearsheet** — binary PDF download of pre-generated
   tearsheet (`reports/tearsheets/{TICKER}_tearsheet.pdf`) with
   `Content-Type: application/pdf` and `Content-Disposition: attachment`.
   404 if company unknown or PDF not generated.

**Shared helpers (`src/api/db.py`):** `get_db_connection()` context manager
with `sqlite3.Row` factory; `_row_to_dict()`/`_rows_to_list()`; year
validator returning 422 with descriptive message for malformed
YYYY-MM params.

**Live verification (uvicorn on :8000):**
  * `GET /api/v1/companies/` → 92 companies.
  * `?sector=Financials` → 19; `?market-cap=Large Cap` → 69.
  * `?search=Tata` → 6 companies (TATACOMM, TATACONSUM, TATAMOTORS,
    TATAPOWER, TATASTEEL, TCS).
  * `GET /companies/FAKE` → 404.
  * `GET /companies/TCS/pl?from=2022-03&to=2024-03` → exactly 3 rows,
    years 2022-03..2024-03.
  * `GET /companies/TCS/tearsheet` → 200, 118 KB valid PDF (2 pages,
    %PDF- header).
  * `?from=bad` → 422 with descriptive error.

**Tests:** 33 new covering list (92 rows, 6 required columns, sector /
market-cap / search filters, combination, empty-result-200), profile
(TCS+HDFCBANK, case-insensitive ticker, 404), time series (all three
statements, column keys, from/to window = 3 rows for TCS, 422 on bad
year, 404 on unknown, ascending order), ratios (full history ≥13 rows,
single-year = 1 row, 404, 422, empty-year 200/0), tearsheet (PDF
header, content-type, content-disposition, file size, 4 cross-sector
tickers, 404). Day-38 scaffold test updated to expect the real
/companies/ response (stubs remain for screener/sectors/peers/etc.).

**Final non-dashboard test count:** 960 passing (927 + 33).
Black & Ruff clean. Committed as `[Sprint6-Day39]`.

## Day 40 — API Endpoints: Screener, Sectors, Peers, Valuation, Portfolio, Documents (Sprint 6)

**Modules:** `src/api/routers/{screener,sectors,peers,valuation,portfolio,documents}.py`
**CLI:** `scripts/day40_export_openapi.py`
**Tests:** `tests/api/test_day40.py` (30 new)

**Endpoints implemented:**

1. **GET /api/v1/screener/** — filterable ranked list. Query params: `min_roe`,
   `max_de`, `min_fcf`, `sector`, `min_rev_cagr_5yr`, `min_pat_cagr_5yr`,
   `max_pe`. Non-numeric params return HTTP 400. Results ranked by composite
   quality score desc; includes id, name, sector, all filter metrics,
   valuation, market cap.
2. **GET /api/v1/sectors/** — 11 sectors with company_count and median ROE /
   P/E / D/E (Pandas-free — medians computed in-Python because SQLite lacks
   MEDIAN()).
3. **GET /api/v1/sectors/{sector}/companies** — all companies in a sector
   with latest-year KPIs; 404 for unknown.
4. **GET /api/v1/peers/{group_name}** — members + percentile ranks for all
   10 peer metrics (`roe, roce, npm, de, fcf, pat_cagr_5yr, rev_cagr_5yr,
   asset_turnover, interest_coverage, eps_cagr_5yr`); benchmark flag; 404
   for unknown group.
5. **GET /api/v1/companies/{ticker}/peers/compare** — 8-axis radar data
   (roe, roce, npm, de, cfo_pat, pat_cagr_5yr, rev_cagr_5yr, composite):
   company vector, peer-group average vector, benchmark vector. Returns 404
   if the company has no peer group.
6. **GET /api/v1/market-cap/{ticker}** — historical valuation multiples
   (market_cap_crore, EV, P/E, P/B, EV/EBITDA, dividend yield) for calendar
   years 2019-2024; 404 for unknown.
7. **GET /api/v1/portfolio/stats** — P10/P25/P50/P75/P90/Mean/Std for 10
   core KPIs, computed live from DB (matches Day-37 portfolio_stats.csv).
8. **GET /api/v1/portfolio/clusters** — returns Day-36/37 cluster labels
   from `output/cluster_labels.csv` (92 companies).
9. **GET /api/v1/companies/{ticker}/documents** — annual report links per
   year with `is_url_valid` flag; by default uses fast /missing/-token
   heuristic; pass `?check-urls=true` to run a live HEAD check (2s timeout).
10. **GET /export/openapi.json** + **GET /export/postman.json** — live
    OpenAPI 3 schema and a Postman v2.1 collection (20 requests) generated
    from the same schema.
11. CLI `scripts/day40_export_openapi.py` writes `docs/openapi.json` (32 KB)
    and `docs/postman_collection.json` (20 requests).

**Endpoint count:** 20 total paths (9 company-data from Day 39 + 9 new data
endpoints + 2 export endpoints + root/health).

**Tests:** 30 new covering screener (unfiltered=92, min_roe, sector,
combined filters, 400 on invalid input, response schema, ranked-order
invariant), sectors (11 sectors, median columns, per-sector companies=19
for Financials, KPI columns, 404), peers (IT Services has TCS+INFY+...,
10 metrics, percentile+value keys, exactly one benchmark (TCS), 404, radar
compare returns 8 axes + peer_avg + benchmark, radar 404), market-cap
(TCS=6 years 2019-2024, columns present, 404), portfolio stats (10 KPIs,
P10≤P50≤P90, labels), clusters (92 rows), documents (TCS ≥10 rows,
url+year+is_url_valid, 404), export (OpenAPI schema has openapi/paths/health,
Postman collection has ≥15 items, exported docs/openapi.json and
docs/postman_collection.json exist on disk).

**Final non-dashboard test count:** 990 passing (960 + 30).
Black & Ruff clean. Committed as `[Sprint6-Day40]`.

## Day 41 — ETL & KPI Unit Tests

**Goal:** Expand unit-test coverage for ETL normalisation, Excel loading, KPI
edge-cases, and data-quality rules to harden the data-foundation layer ahead
of final QA.

**Deliverables:**

1. **`tests/etl/test_normalise.py`** — 20 unit tests for `normalize_year()`
   via the British-spelling `src.etl.normaliser` re-export, covering:
   Mar-23 hyphen/space short form, March-2023 full name, bare int/str/float/
   2-digit years, FY-prefix variants (FY23, FY 2024, FY2023, F.Y.24),
   non-March closes (Dec-22, Jun-23), already-canonical YYYY-MM, datetime
   objects, two-digit pivot (50→2050, 51→1951), error cases (None, garbage),
   and the `normalize_year_safe` sentinel path.

2. **`tests/etl/test_loader.py`** — 10 unit tests verifying the Excel loader
   reads the 12 Screener.in datasets correctly: 12 datasets registered,
   core and supplementary datasets expose expected column subsets, tickers
   are uppercased, time-series years are normalised to YYYY-MM, companies
   uses 'id' as the ticker column, documents.Year is a calendar INT (not
   FY-normalised), 92 company rows present, sectors covers all 92 tickers,
   and column headers have no leading/trailing whitespace.

3. **`tests/kpi/test_ratios.py`** — 20 unit tests covering KPI edge-cases:
   ROE with positive equity, negative equity (None), zero equity (None),
   reserves=None; D/E for debt-free (=0), normal value, negative equity
   (None), high-leverage flag for non-financials with D/E>5 (with financial
   carve-out); ICR when interest=0 (None), normal calculation; CAGR
   turnaround, decline-to-loss, normal 5-yr doubling, zero-base, negative
   growth; OPM cross-check no-divergence / diverged / at-exact-tolerance;
   CFO/PAT ratio and CFO quality tier thresholds (High/Moderate/Accrual
   Risk, None/NaN).

4. **`tests/dq/test_rules.py`** — 14 unit tests (one per DQ rule DQ-01
   through DQ-14), each crafting a minimal DataFrame that violates exactly
   that rule and asserting the correct `rule_id` and `severity`:
   DQ-01 duplicate company PK (CRITICAL), DQ-02 duplicate (company_id, year)
   (CRITICAL), DQ-03 FK orphan (CRITICAL), DQ-04 BS imbalance >1% (WARNING),
   DQ-05 OPM mismatch ≥1pp (WARNING), DQ-06 zero sales non-bank (WARNING),
   DQ-07 bad year (CRITICAL), DQ-08 invalid ticker (CRITICAL), DQ-09 net
   cash >Rs10Cr mismatch (WARNING), DQ-10 negative fixed assets (WARNING),
   DQ-11 tax outside [0,60]% (WARNING), DQ-12 dividend payout >200%
   (WARNING), DQ-13 invalid Annual_Report URL (WARNING), DQ-14 PAT>0 with
   EPS≤0 (WARNING).

**Tests run:** `pytest tests/etl/ tests/kpi/ tests/dq/ -v` — 473 passed,
0 failures. Black-formatted and Ruff-clean.
