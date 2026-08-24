-- =============================================================================
-- Nifty 100 Financial Intelligence Platform — SQLite Schema
-- All monetary values are in Indian Rupees (₹ Crore) unless stated otherwise.
-- Tickers are uppercase, stripped NSE symbols (e.g. TCS, BAJAJ-AUTO, M&M).
-- Years/periods are stored as 'YYYY-MM' strings (financial-year close month).
-- Run once at project bootstrap; re-runnable (IF NOT EXISTS on every object).
-- Always enable foreign keys before writing:  PRAGMA foreign_keys = ON;
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- 1. companies — master company reference (snapshot, 92 rows)
--    PK: id (NSE ticker)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id               TEXT    PRIMARY KEY,                 -- NSE ticker, e.g. 'TCS'
    company_logo     TEXT,                                -- URL to logo
    company_name     TEXT    NOT NULL,                    -- Full legal name
    chart_link       TEXT,                                -- TradingView URL
    about_company    TEXT,                                -- Business description
    website          TEXT,                                -- Corporate website
    nse_profile      TEXT,                                -- NSE India profile URL
    bse_profile      TEXT,                                -- BSE India page URL
    face_value       REAL    NOT NULL DEFAULT 1,          -- ₹; common 1/2/5/10
    book_value       REAL,                                -- ₹ per share (display)
    roce_percentage  REAL,                                -- pre-computed ROCE % (display)
    roe_percentage   REAL                                 -- pre-computed ROE % (display)
);

-- -----------------------------------------------------------------------------
-- 2. profitandloss — annual P&L statements (~1,276 rows)
--    PK: (company_id, year)  FK: company_id → companies.id
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profitandloss (
    id                INTEGER,                             -- source row id (not PK)
    company_id        TEXT    NOT NULL,
    year              TEXT    NOT NULL,
    sales             REAL    NOT NULL,
    expenses          REAL    NOT NULL,
    operating_profit  REAL    NOT NULL,                   -- EBITDA
    opm_percentage    REAL    NOT NULL,                   -- OPM %
    other_income      REAL,
    interest          REAL,
    depreciation      REAL,
    profit_before_tax REAL,
    tax_percentage    REAL,
    net_profit        REAL,                                -- PAT
    eps               REAL,                                -- ₹
    dividend_payout   REAL,                                -- %
    PRIMARY KEY (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 3. balancesheet — annual balance sheet (~1,312 rows)
--    PK: (company_id, year)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS balancesheet (
    id                INTEGER,
    company_id        TEXT    NOT NULL,
    year              TEXT    NOT NULL,
    equity_capital    REAL    NOT NULL,
    reserves          REAL,
    borrowings        REAL,                                -- total debt
    other_liabilities REAL,
    total_liabilities REAL    NOT NULL,
    fixed_assets      REAL,
    cwip              REAL,                                -- capital work-in-progress
    investments       REAL,
    other_asset       REAL,
    total_assets      REAL    NOT NULL,
    PRIMARY KEY (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    CHECK (total_assets > 0)
);

-- -----------------------------------------------------------------------------
-- 4. cashflow — annual cash-flow statements (~1,187 rows)
--    PK: (company_id, year)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cashflow (
    id                 INTEGER,
    company_id         TEXT    NOT NULL,
    year               TEXT    NOT NULL,
    operating_activity  REAL,                                -- CFO
    investing_activity  REAL,                                -- CFI (usually negative)
    financing_activity  REAL,                                -- CFF
    net_cash_flow       REAL,                                -- CFO+CFI+CFF
    PRIMARY KEY (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 5. analysis — pre-computed compounded growth metrics (partial, ~20 rows)
--    PK: company_id
--    Columns from §5.5: compounded_sales_growth, compounded_profit_growth,
--    stock_price_cagr, roe — each a text field like "10 Years: 21%".
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis (
    id                       INTEGER,
    company_id               TEXT    PRIMARY KEY,
    compounded_sales_growth  TEXT,                                -- "10 Years: 21%"
    compounded_profit_growth TEXT,                                -- "5 Years: 6%"
    stock_price_cagr         TEXT,                                -- "10 Years: 15%"
    roe                      TEXT,                                -- "10 Years: 17%"
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 6. documents — annual report URLs (~1,585 rows)
--    PK: (company_id, Year)  NOTE: spec uses capital-Y "Year" (calendar year)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER,
    company_id    TEXT    NOT NULL,
    Year          INTEGER NOT NULL,                         -- calendar year
    Annual_Report TEXT,                                     -- URL to PDF
    PRIMARY KEY (company_id, Year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 7. prosandcons — qualitative pros/cons (partial, ~16 rows)
--    PK: id (auto-increment surrogate)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prosandcons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  TEXT    NOT NULL,
    pros        TEXT,
    cons        TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 8. sectors — sector mapping (92 rows)
--    PK: company_id
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sectors (
    company_id          TEXT    PRIMARY KEY,
    broad_sector        TEXT    NOT NULL,                    -- 11 macro sectors
    sub_sector          TEXT,                                -- ~33 sub-sectors
    index_weight_pct    REAL,                                -- estimated Nifty 100 weight
    market_cap_category TEXT,                                -- 'Large Cap' / 'Mid Cap'
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 9. stock_prices — monthly OHLCV (5,520 rows, Jan 2020 – Dec 2024)
--    PK: (company_id, date)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_prices (
    company_id     TEXT    NOT NULL,
    date           TEXT    NOT NULL,                         -- 'YYYY-MM-DD'
    open_price     REAL,
    high_price     REAL,
    low_price      REAL,
    close_price    REAL,
    volume         INTEGER,
    adjusted_close REAL,
    PRIMARY KEY (company_id, date),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 10. market_cap — annual valuation multiples (552 rows, 2019–2024)
--     PK: (company_id, year)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_cap (
    company_id            TEXT    NOT NULL,
    year                  INTEGER NOT NULL,                  -- calendar year
    market_cap_crore      REAL,
    enterprise_value_crore REAL,
    pe_ratio              REAL,
    pb_ratio              REAL,
    ev_ebitda             REAL,
    dividend_yield_pct    REAL,
    PRIMARY KEY (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 11. financial_ratios — computed KPI table (~1,184 rows)
--     PK: (company_id, year)  Populated in Sprint 2 (Ratio Engine).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_ratios (
    company_id               TEXT    NOT NULL,
    year                     TEXT    NOT NULL,
    net_profit_margin_pct    REAL,
    operating_profit_margin_pct REAL,
    ebit_margin_pct          REAL,
    return_on_equity_pct     REAL,
    roce_pct                 REAL,
    return_on_assets_pct     REAL,
    debt_to_equity           REAL,
    high_leverage_flag       INTEGER NOT NULL DEFAULT 0,  -- 1 if D/E > 5 (non-financial)
    interest_coverage        REAL,
    icr_label                TEXT,                           -- "Debt Free" when interest=0
    icr_warning_flag         INTEGER NOT NULL DEFAULT 0,  -- 1 if 0<ICR<1.5
    net_debt_cr              REAL,                           -- borrowings - investments (₹Cr)
    asset_turnover           REAL,
    free_cash_flow_cr        REAL,
    capex_cr                 REAL,
    earnings_per_share       REAL,
    book_value_per_share     REAL,
    dividend_payout_ratio_pct REAL,
    total_debt_cr            REAL,
    cash_from_operations_cr  REAL,
    -- CAGR columns (Sprint 2 Day 10): revenue/PAT/EPS × 3/5/10yr windows
    revenue_cagr_3yr         REAL,
    revenue_cagr_3yr_flag    TEXT,
    revenue_cagr_5yr         REAL,
    revenue_cagr_5yr_flag    TEXT,
    revenue_cagr_10yr        REAL,
    revenue_cagr_10yr_flag   TEXT,
    pat_cagr_3yr             REAL,
    pat_cagr_3yr_flag        TEXT,
    pat_cagr_5yr             REAL,
    pat_cagr_5yr_flag        TEXT,
    pat_cagr_10yr            REAL,
    pat_cagr_10yr_flag       TEXT,
    eps_cagr_3yr             REAL,
    eps_cagr_3yr_flag        TEXT,
    eps_cagr_5yr             REAL,
    eps_cagr_5yr_flag        TEXT,
    eps_cagr_10yr            REAL,
    eps_cagr_10yr_flag       TEXT,
    -- Cash-flow KPI columns (Sprint 2 Day 11)
    fcf_cr                   REAL,
    cfo_pat_ratio            REAL,
    cfo_quality_score_5yr    REAL,
    cfo_quality_tier         TEXT,
    capex_intensity_pct      REAL,
    capex_tier               TEXT,
    fcf_conversion_pct       REAL,
    capital_allocation_pattern TEXT,
    cfo_sign                 TEXT,
    cfi_sign                 TEXT,
    cff_sign                 TEXT,
    fcf_concern_flag         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 12. peer_groups — manually defined peer group memberships (~56 rows)
--     PK: (company_id, peer_group_name)  M:N relationship.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS peer_groups (
    company_id       TEXT    NOT NULL,
    peer_group_name  TEXT    NOT NULL,
    is_benchmark     INTEGER NOT NULL DEFAULT 0,             -- 1 if benchmark for group
    PRIMARY KEY (company_id, peer_group_name),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- Audit / DQ helper tables
-- -----------------------------------------------------------------------------

-- Per-load audit trail (appended on every ETL run)
CREATE TABLE IF NOT EXISTS load_audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name   TEXT    NOT NULL,
    rows_in      INTEGER NOT NULL DEFAULT 0,
    rows_out     INTEGER NOT NULL DEFAULT 0,
    rows_rejected INTEGER NOT NULL DEFAULT 0,
    runtime_s    REAL,
    status       TEXT    NOT NULL DEFAULT 'OK',             -- OK / FAILED / PARTIAL
    loaded_at    TEXT    NOT NULL DEFAULT (datetime('utc'))
);

-- Data-quality violations (mirror of validation_failures.csv)
CREATE TABLE IF NOT EXISTS validation_failures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id     TEXT    NOT NULL,
    table_name  TEXT    NOT NULL,
    company_id  TEXT,
    year        TEXT,
    column_name TEXT,
    severity    TEXT    NOT NULL,                            -- CRITICAL / WARNING / INFO
    message     TEXT    NOT NULL,
    expected    TEXT,
    actual      TEXT,
    row_index   INTEGER,
    reported_at TEXT    NOT NULL DEFAULT (datetime('utc'))
);

-- -----------------------------------------------------------------------------
-- Indexes — speed up common joins (FK lookups, sector filters, time-series scans).
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_pl_company_year    ON profitandloss(company_id, year);
CREATE INDEX IF NOT EXISTS idx_bs_company_year    ON balancesheet(company_id, year);
CREATE INDEX IF NOT EXISTS idx_cf_company_year    ON cashflow(company_id, year);
CREATE INDEX IF NOT EXISTS idx_documents_company  ON documents(company_id);
CREATE INDEX IF NOT EXISTS idx_sectors_broad      ON sectors(broad_sector);
CREATE INDEX IF NOT EXISTS idx_prices_date        ON stock_prices(date);
CREATE INDEX IF NOT EXISTS idx_mcap_year          ON market_cap(year);
CREATE INDEX IF NOT EXISTS idx_ratios_year        ON financial_ratios(year);
CREATE INDEX IF NOT EXISTS idx_peers_group        ON peer_groups(peer_group_name);
CREATE INDEX IF NOT EXISTS idx_vf_severity        ON validation_failures(severity);
