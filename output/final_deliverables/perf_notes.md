# Performance Notes — Day 43

Generated: 2026-09-18 10:48:12
Python: 3.13.14
Database: SQLite @ db/nifty100.db (92 companies)

## 1. Screener concurrency — 10 concurrent calls
Target: all 10 complete within 10 seconds.

* Wall-clock time for 10 concurrent calls: **70 ms** (0.07s)
* Per-request times (ms): 40, 45, 47, 47, 47, 40, 51, 56, 54, 55
* Max single request: **56 ms**
* Mean single request: **48 ms**
* Result: **PASS** (under 10s target).

## 2. Company Profile screen latency (5 tickers, target <3s each)
Each profile loads: companies/{TICKER}, pl, bs, cashflow, ratios,
market-cap, peers/compare — 7 HTTP calls per ticker.

| Ticker | Time (ms) |
|--------|-----------|
| TCS | 27 |
| RELIANCE | 27 |
| HDFCBANK | 25 |
| INFY | 25 |
| ITC | 25 |

* Average profile load: **26 ms**
* Worst ticker: **RELIANCE = 27 ms**
* Result: **PASS** (all under 3s).

## 3. End-to-end server startup
* FastAPI (uvicorn) on :8000 — binds and serves `/api/v1/health` within ~1s.
* Streamlit on :8501 — binds and serves `/` within ~5-7s.
* No port conflict observed; both servers run concurrently.

## 4. SQLite indexes
Verified indexes present on large tables:

| Table              | Index                       | Purpose                            |
|--------------------|-----------------------------|------------------------------------|
| profitandloss      | idx_pl_company_year         | (company_id, year) lookups         |
| balancesheet       | idx_bs_company_year         | (company_id, year) lookups         |
| cashflow           | idx_cf_company_year         | (company_id, year) lookups         |
| financial_ratios   | idx_ratios_year             | year-range scans                   |
| stock_prices       | idx_prices_date             | date-based price scans             |
| market_cap         | idx_mcap_year               | year-based market-cap scans        |
| documents          | idx_documents_company       | per-company document lookup        |
| sectors            | idx_sectors_broad           | broad_sector filter                |
| peer_groups        | idx_peers_group             | peer-group membership queries      |
| peer_percentiles   | idx_pp_group_metric         | per-group metric scans             |

All companies.* tables have AUTOINCREMENT primary-key indexes (PK `id`).

## 5. Bottlenecks observed
* Single-threaded SQLite handles 10 concurrent screener calls comfortably
  (~100-200 ms wall time for 10 parallel requests at this data volume
  of 89-92 companies).
* The slowest per-request component is the screener join (companies x
  sectors x financial_ratios x market_cap) which reads ~92 rows per call.
  At production scale (hundreds/thousands of tickers) a covering index
  on `(return_on_equity_pct, debt_to_equity, composite_quality_score)`
  could further accelerate filtered queries, but at 92 rows this is not
  necessary.
* Streamlit startup (5-7s) is dominated by streamlit's own boot sequence
  (compiling pages, starting tornado), not data loading. Data fetches
  from the API are sub-100ms once the server is up.
* No optimisation applied beyond verifying existing indexes — queries are
  already sub-second on the 92-company dataset.
