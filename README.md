# Nifty 100 Financial Intelligence Platform

A production-grade Python data platform for ingesting, validating, analysing, and
visualising financial data for the **Nifty 100** universe.  The platform follows a
modular, scalable architecture spanning ETL pipelines, analytics, an interactive
Streamlit dashboard, and a FastAPI layer, developed over a 45-day sprint plan.

---

## Project Overview

The **Nifty 100 Financial Intelligence Platform** is designed to:

- **Ingest** 12 financial datasets covering equities, fundamentals, sectors, and
  macro indicators.
- **Validate** incoming data for quality, schema conformance, and referential
  integrity.
- **Load** cleansed data into a SQLite relational warehouse (`db/nifty100.db`)
  covering 92 Nifty-100 companies and up to 14 years of history.
- **Analyse** data using ratio engines, peer-group comparisons, composite
  quality scores, capital-allocation pattern detection, and sector-relative
  valuation flags.
- **Visualise** insights through an 8-screen Streamlit dashboard with Plotly
  charts, live screeners, and drill-downs.
- **Export** formatted Excel and CSV deliverables (`valuation_summary.xlsx`,
  `valuation_flags.csv`, `screener_output.xlsx`, `peer_comparison.xlsx`).

The codebase follows modern Python standards: type hints, modular packages,
Loguru-structured logging, python-dotenv configuration, Black/Ruff/Pytest gates,
and a 600+ test suite.

---

## Folder Structure

```
nifty100/
├── config/                # Static YAML/JSON configuration
├── data/                  # Raw, processed, and interim datasets
├── db/
│   └── nifty100.db        # Production SQLite warehouse (~12,800 ratios rows, 92 companies)
├── docs/                  # Standup updates, sprint retros, task board
├── logs/                  # Rotating Loguru logs + dashboard runtime log
├── notebooks/             # Exploration / prototyping
├── output/                # Generated deliverables
│   ├── valuation_summary.xlsx   # 92 companies × 11 columns (colour-coded flags)
│   ├── valuation_flags.csv      # Caution + Discount rows only
│   ├── screener_output.xlsx
│   ├── peer_comparison.xlsx
│   └── capital_allocation.csv
├── reports/               # Radar chart PNGs and generated artefacts
├── scripts/               # CLI utilities (ETL, valuation, ratio population)
├── src/
│   ├── etl/               # Extract-Transform-Load pipelines + validation
│   ├── analytics/         # Ratios, peers, composite scoring, valuation engine
│   ├── screener/          # Screener engine and Excel/CSV exporter
│   ├── dashboard/         # Streamlit multi-page UI
│   │   ├── app.py         # Entry point (sidebar nav, wide layout, KPI header)
│   │   ├── pages/         # 8 screens: 01_home … 08_reports
│   │   └── utils/db.py    # @st.cache_data SQLite loaders (10-min TTL)
│   └── utils/             # Config, logging, helpers
├── tests/                 # Pytest suite (etl/kpi/screener/visuals/analytics/dashboard)
├── pyproject.toml         # Black/Ruff/Pytest configuration
├── requirements.txt
├── requirements-dev.txt
├── Makefile
└── README.md
```

---

## Installation

### Prerequisites

- **Python 3.12+** (developed on Python 3.13)
- **pip** (latest)
- **git**

### Setup

```bash
git clone https://github.com/mattperrymatt45-pixel/nifty100.git
cd nifty100

python3.13 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements-dev.txt

cp .env.example .env             # edit paths/ports if needed
```

### Database

The production database ships at `db/nifty100.db` with 92 Nifty-100 companies,
12,800+ financial-ratio rows, and market-cap data for CY 2019–2024.  To rebuild
from raw data, run:

```bash
python scripts/populate_ratios.py
python scripts/day26_valuation.py    # regenerates output/valuation_summary.xlsx
```

---

## Running the Dashboard

From the project root:

```bash
streamlit run src/dashboard/app.py
```

By default Streamlit binds to `http://localhost:8501`.  For headless / container
deployments:

```bash
streamlit run src/dashboard/app.py \
    --server.headless true \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --browser.gatherUsageStats false
```

A `make run-dashboard` shortcut is also provided.  All database reads go through
`src/dashboard/utils/db.py` which caches queries for 600 seconds
(`@st.cache_data(ttl=600)`), so repeated navigation is instant.  The Company
Profile screen renders in under 0.1 seconds per ticker on production data.

### Running other services

```bash
make run-api          # FastAPI via Uvicorn (future endpoint surface)
make test             # Full pytest suite with coverage
make lint             # Ruff
make format           # Black + Ruff --fix
```

### Running the FastAPI REST API

```bash
uvicorn src.api.main:app --port 8000 --host 0.0.0.0
```

Interactive docs at `http://localhost:8000/docs` (Swagger) and
`http://localhost:8000/redoc`. All endpoints are versioned under `/api/v1/`:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Server + DB row counts |
| `GET /api/v1/companies/` | List/filter 92 companies (sector, market-cap, search) |
| `GET /api/v1/companies/{ticker}` | Company profile + latest KPIs + valuation |
| `GET /api/v1/companies/{ticker}/pl|bs|cashflow` | Financial-statement history |
| `GET /api/v1/companies/{ticker}/ratios` | Ratio history |
| `GET /api/v1/companies/{ticker}/tearsheet` | Download 2-page PDF tearsheet |
| `GET /api/v1/companies/{ticker}/peers/compare` | Radar chart data vs peers |
| `GET /api/v1/screener/` | Multi-factor filter (min_roe, max_de, sector, …) |
| `GET /api/v1/sectors/` | 11 broad sectors with median KPIs |
| `GET /api/v1/sectors/{sector}/companies` | Per-sector company list |
| `GET /api/v1/peers/{group}` | Peer-group members with percentile ranks |
| `GET /api/v1/market-cap/{ticker}` | 6-year market-cap / valuation history |
| `GET /api/v1/portfolio/stats` | P10/P25/P50/P75/P90/Mean/Std KPIs |
| `GET /api/v1/portfolio/clusters` | KMeans cluster labels (5 archetypes) |
| `GET /api/v1/companies/{ticker}/documents` | Annual-report URL list |
| `GET /export/openapi.json` | Live OpenAPI 3 schema |
| `GET /export/postman.json` | Postman v2.1 collection |

Example: quality compounders in IT
```bash
curl "http://localhost:8000/api/v1/screener/?min_roe=18&sector=Information+Technology"
```

### Running the test suite

```bash
pytest tests/ -q       # unit + integration + API + performance tests
pytest tests/api -q    # API tests only
pytest tests/perf -v   # performance (10 concurrent screener calls, profile latency, end-to-end server startup)
pytest tests/ --html=reports/pytest_report.html --self-contained-html
```

Before committing:
```bash
python -m black src/ tests/ scripts/
python -m ruff check src/ tests/ scripts/ --fix
```

---

## Dashboard Screens

The dashboard ships with **8 screens** accessed from an always-expanded sidebar
under the title "Nifty 100 Analytics".  The layout uses `st.set_page_config`
with `layout="wide"` and an expanded sidebar by default.

### 1. Home
- **Purpose:** Landing-page executive summary for the selected financial year.
- **Contents:** 6 KPI tiles (companies covered, median ROE, median ROCE, median
  P/E, median D/E, FCF-positive count), a sector-distribution donut chart, a
  top-5 companies table by market cap/quality score, and a financial-year
  selector.
- **Data source:** `get_kpis_for_year()`, `get_latest_ratios()`.

### 2. Company Profile
- **Purpose:** Deep-dive single-company view with search/select.
- **Contents:** Company card (logo, sector, about, website, BSE/NSE links), 6
  key-metric tiles (market cap, P/E, ROCE, ROE, D/E, dividend yield), a grouped
  Revenue vs PAT bar chart (10 years), a dual-axis ROE/ROCE line chart, and a
  pros/cons panel (with a "No data" caption when pros/cons are unavailable).
- **Edge cases handled:** tickers with fewer than 10 years of history drop NaN
  rows and display a "partial data available" note; missing metrics show **N/A**
  instead of crashing.
- **Performance:** Loads in 0.03–0.08 s per ticker (3-second budget met).

### 3. Screener
- **Purpose:** Multi-factor filter across the Nifty 100 universe.
- **Contents:** 10 metric sliders (ROCE, ROE, D/E, P/E, P/B, dividend yield,
  FCF yield, 3y/5y/10y PAT CAGR), 6 preset buttons (quality_compounder,
  value_pick, growth_accelerator, dividend_champion, debt_free_blue_chip,
  turnaround_watch) per spec §25, a live result table, a CSV download button
  (`screener_output.xlsx` schema), and a result-count badge.
- **Edge cases handled:** extreme slider combinations (all-min, all-max) return
  the full universe or an empty state without error.

### 4. Peers
- **Purpose:** Company vs peer-group benchmarking.
- **Contents:** Peer-group dropdown (11 groups), an 8-axis Plotly
  `Scatterpolar` radar comparing the selected company against the peer-group
  average, and a KPI table with the sector/peer benchmark highlighted in gold.

### 5. Trends
- **Purpose:** Multi-metric time-series exploration.
- **Contents:** Multi-select metric picker, dual-Y-axis line chart, year-
  over-year annotations on key inflection points, and company/ticker compare.

### 6. Sectors
- **Purpose:** Cross-sector overview and relative valuation.
- **Contents:** Plotly bubble chart (X = Revenue, Y = ROE, size = market cap,
  colour = sector), median-KPI bar charts per sector, and sector selector.
- **Bug-fix Day 27:** corrected `company_id` vs `ticker` column name from
  `get_full_ratios_with_pl()` so bubbles render for all companies.

### 7. Capital Allocation
- **Purpose:** Visualise how companies deploy cash (CFO/CFI/CFF patterns).
- **Contents:** Plotly treemap grouped by `capital_allocation_pattern`
  (Shareholder Returns, Mixed, Reinvestor, Growth Funded by Debt, …) with
  pattern-specific colour coding; drill-down by pattern to view constituent
  companies; quality-score hover tooltips.

### 8. Reports
- **Purpose:** One-stop hub for BSE filings and project artefact downloads.
- **Contents:** BSE annual-report link checker with green (200) / red (404)
  status badges, quick links to NSE/BSE profiles, and downloads for
  `valuation_summary.xlsx`, `valuation_flags.csv`, `peer_comparison.xlsx`, and
  `screener_output.xlsx`.
- **Performance:** HEAD probes to BSE use a 2-second timeout so the page stays
  responsive when BSE is slow; unknown tickers (e.g. `__GHOST__`) skip the probe
  cleanly.

---

## Valuation Module (Sprint 4)

`src/analytics/valuation.py` implements a sector-relative valuation engine:

| Column | Description |
|---|---|
| `company_id` / `company_name` / `sector` | Identifiers and broad sector |
| `pe_ratio`, `pb_ratio`, `ev_ebitda` | Trailing multiples from market-cap table |
| `fcf_yield_pct` | `free_cash_flow_cr / market_cap_crore × 100` |
| `5yr_median_PE` | 5-year median P/E per company (pandas median; SQLite lacks MEDIAN()) |
| `sector_median_PE` | Median P/E per broad sector (positive-P/E rows only) |
| `PE_vs_sector_median_pct` | `P/E ÷ sector_median × 100` |
| `flag` | **Caution** (>1.5× sector median), **Discount** (<0.7×), **Fair** |

Thresholds: `SECTOR_PREMIUM_MULTIPLIER = 1.5`, `SECTOR_DISCOUNT_MULTIPLIER = 0.7`.
Loss-makers (PE ≤ 0 or NaN) default to Fair.  Outputs are colour-coded in Excel
(red = Caution, green = Discount, yellow = Fair) with frozen header and auto-
sized columns; the CSV contains only flagged (Caution + Discount) names.

**Current run on FY 2024-03 data:** 92 companies, 53 Fair / 14 Caution /
25 Discount, 39 flagged names exported to `output/valuation_flags.csv`.

Regenerate via:

```bash
python scripts/day26_valuation.py                # default DB + output/
python scripts/day26_valuation.py --year 2023    # earlier CY
```

---

## Testing

```bash
# Full suite (no coverage, fast feedback)
python -m pytest tests/ -q --no-cov

# With coverage
make test
```

The suite currently stands at **752 passing tests** across ETL, KPI, screener,
visuals, analytics, and dashboard integration (including the Day-27 smoke test
that renders all 8 screens across 10 cross-sector tickers plus extreme-screener
slider values).

Code-quality gates (enforced pre-commit):

```bash
python -m black src/ tests/ scripts/ -q
python -m ruff check src/ tests/ scripts/ --fix -q
```

---

## Sprint 4 Retrospective

Sprint 4 (Days 22–28) shipped the Streamlit dashboard and the sector-relative
valuation engine.

### UX decisions
- **Wide layout + expanded sidebar** by default — analysts need room for
  Plotly charts and the multi-screen flow benefits from the sidebar always
  being visible.
- **Consistent KPI tile pattern** (6 tiles per page, `st.columns([1,1,1,1,1,1]`)
  so Home / Profile / Screens feel unified.
- **Gold benchmark highlighting** on the Peers KPI table and green/red status
  badges on the Reports page — instant visual cue without colour-only encoding.
- **Colour-coded valuation flags** (red Caution / green Discount / yellow Fair)
  applied identically in `valuation_summary.xlsx` and in any future screen
  that displays the flag, to avoid user re-learning.
- **NaNs display as N/A** (not zero, not a blank crash) per accessibility and
  data-honesty principles; partial-data (<10 years) charts get an explicit
  caption note.

### Data edge cases discovered
- **Late filers in FY 2024-03:** NHPC, TORNTPHARM, BANDHANBNK were missing
  `financial_ratios` rows for `2024-03` even though market_cap and
  profitandloss/balancesheet had data.  Fixed `load_valuation_panel()` to use
  LEFT JOIN and fall back to each company's latest available FY fundamentals
  so the panel returns all 92 companies (was 89 on Day 26).
- **`get_full_ratios_with_pl()` returns `company_id`, not `ticker`.**  Sectors
  and Capital pages raised AttributeError until corrected on Day 27.
- **SQLite has no `MEDIAN()` aggregate** — sector- and company-medians are
  computed in pandas, grouped, and merged back.
- **`icr_label` is NULL** for the debt-free cohort; debt-free filtering had to
  fall back to `D/E ≤ 0.05 OR icr_label == "Debt Free"`.
- **`prosandcons` only populated for 16 companies** (e.g. HINDUNILVR,
  ASIANPAINT, PIDILITIND).  TCS and many others legitimately return no rows;
  the Profile page now renders "No data" caption rather than a broken panel.
- **Capital-allocation patterns in latest FY only cover 4 of the 8 pattern
  buckets** (Shareholder Returns 58, Mixed 19, Reinvestor 10, Growth Funded by
  Debt 2).  The treemap renders only populated buckets while retaining all 8
  colour definitions for forward-compatibility.
- **BSE `urlopen` HEAD probes can stall 4+ seconds.**  Tightened to a 2-second
  timeout; pages should never wait on a third-party endpoint for core content.
- **All-NaN ROE/ROCE series** for some partial-history tickers caused Plotly to
  throw; charts now `dropna(how="all")` and plot only non-null traces.

### Performance findings
- `@st.cache_data(ttl=600)` makes intra-session navigation effectively instant
  after first load.
- **Company Profile screen: 0.03–0.08 s per ticker** across the 5 spot-checked
  names (TCS, HDFCBANK, HINDUNILVR, RELIANCE, SUNPHARMA) — well under the 3 s
  budget.
- Heavy Plotly charts (treemap, bubble, radar) render in <200 ms on production
  data; the 5yr-P/E median aggregation is done once per panel load, not per
  company.
- The full pytest suite runs in ~2.5 minutes end-to-end; the Day-27 dashboard
  integration tests (which actually render page modules in-process via a
  Streamlit shim) account for ~60 seconds of that.

### What we would do differently next sprint
- Add a real Streamlit E2E layer (e.g. `streamlit.testing.v1.AppTest`) once
  stable on Python 3.13; the shim is pragmatic but won't catch CSS / layout
  regressions.
- Pre-compute the valuation panel and persist alongside the DB so the Home /
  Screener / Valuation surfaces don't each repeat the join.
- Back-fill `prosandcons` for the remaining 76 companies from a structured
  source (currently only 16 populated).

---

## Project Workflow

The platform is developed across six completed sprints (Day 1 through Day 43):

1. **Sprint 1 — Environment & ETL Foundation (Days 1–7):** Scaffolding,
   dependencies, logging, config, 12-dataset loaders, validators, SQLite
   schema, ratio population.
2. **Sprint 2 — Analytics Engine (Days 8–14):** KPIs, sector analysis, peer
   groups, composite scores, radar charts, capital-allocation patterns,
   screener engine, Excel/CSV exporters.
3. **Sprint 3 — Presets & Screening (Days 15–21):** Six spec-§25 screening
   presets, peer-report PDFs, quality/debt/turnaround labelling, edge-case
   hardening.
4. **Sprint 4 — Dashboard & Valuation (Days 22–28):** 8-screen Streamlit app
   (Home, Profile, Screener, Peers, Trends, Sectors, Capital, Reports),
   sector-relative valuation engine (Caution/Discount/Fair flags), integration
   QA across 92 tickers, README + retro documentation.
5. **Sprint 5 — PDF Reports & Cashflow Intelligence (Days 29–35):** Per-company
   tearsheet PDFs, 92-page portfolio summary, sector reports, cashflow
   intelligence, distress alerts, deleveraging flags, outlier detection.
6. **Sprint 6 — Clustering, REST API & Sign-off (Days 36–43):** KMeans
   clustering into 5 archetypes, 16-endpoint FastAPI layer, OpenAPI + Postman
   export, 607+ pytest tests with an HTML report, performance validation
   (10 concurrent calls under 10s, profile <3s), end-to-end server launch.

See `docs/standup_updates.md` for per-day notes, `docs/analyst_guide.pdf`
for a 10-page analyst user guide, and `docs/task_board.md` for
the sprint backlog status.

---

## Code Quality Standards

- **Black** — deterministic formatting (line length 100).
- **Ruff** — fast linting, import sorting, auto-fixes.
- **Pytest** — 600+ unit, integration, API and performance tests with
  HTML report generation (see `reports/pytest_report.html`).
- **Loguru** — structured, rotating logs in `logs/`.
- **python-dotenv** — environment-based configuration (`.env.example`
  provided).
- **Pre-commit hooks** enforce formatting and linting before every commit.
- **Commit message format:** `[SprintN-DayM] feat: description`.

---

## License

Internal project — all rights reserved.
