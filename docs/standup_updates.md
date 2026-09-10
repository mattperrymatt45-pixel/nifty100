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
