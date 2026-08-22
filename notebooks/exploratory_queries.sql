-- =============================================================================
-- Nifty 100 Financial Intelligence Platform — Sprint 1, Day 7
-- Exploratory SQL Queries (10+ ready-to-run)
--
-- Run against db/nifty100.db via:
--     sqlite3 db/nifty100.db < db/exploratory_queries.sql
-- Or copy-paste individual statements into DB Browser / DBeaver / Python.
-- All queries are read-only SELECTs; safe to re-run.
-- =============================================================================

.headers on
.mode column
.nullvalue NULL

-- =============================================================================
-- QUERY 01: Row counts across all 12 business tables (sanity/audit)
-- =============================================================================
SELECT 'companies'        AS table_name, COUNT(*) AS rows FROM companies
UNION ALL SELECT 'sectors',           COUNT(*) FROM sectors
UNION ALL SELECT 'analysis',          COUNT(*) FROM analysis
UNION ALL SELECT 'peer_groups',       COUNT(*) FROM peer_groups
UNION ALL SELECT 'prosandcons',       COUNT(*) FROM prosandcons
UNION ALL SELECT 'documents',         COUNT(*) FROM documents
UNION ALL SELECT 'market_cap',        COUNT(*) FROM market_cap
UNION ALL SELECT 'profitandloss',     COUNT(*) FROM profitandloss
UNION ALL SELECT 'balancesheet',      COUNT(*) FROM balancesheet
UNION ALL SELECT 'cashflow',          COUNT(*) FROM cashflow
UNION ALL SELECT 'financial_ratios',  COUNT(*) FROM financial_ratios
UNION ALL SELECT 'stock_prices',      COUNT(*) FROM stock_prices
ORDER BY rows DESC;

-- =============================================================================
-- QUERY 02: FK integrity check (expect 0 orphan rows per child table)
-- =============================================================================
SELECT 'sectors'           AS child_table, COUNT(*) AS orphan_rows FROM sectors          WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'profitandloss',    COUNT(*) FROM profitandloss    WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'balancesheet',     COUNT(*) FROM balancesheet     WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'cashflow',         COUNT(*) FROM cashflow         WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'financial_ratios', COUNT(*) FROM financial_ratios WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'stock_prices',     COUNT(*) FROM stock_prices     WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'documents',        COUNT(*) FROM documents        WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'market_cap',       COUNT(*) FROM market_cap       WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'analysis',         COUNT(*) FROM analysis         WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'prosandcons',      COUNT(*) FROM prosandcons      WHERE company_id NOT IN (SELECT id FROM companies)
UNION ALL SELECT 'peer_groups',      COUNT(*) FROM peer_groups      WHERE company_id NOT IN (SELECT id FROM companies);

-- =============================================================================
-- QUERY 03: Year coverage per company across P&L/BS/CF (DQ-16 diagnostic)
-- =============================================================================
SELECT c.id,
       c.company_name,
       s.broad_sector,
       (SELECT COUNT(DISTINCT year) FROM profitandloss p WHERE p.company_id=c.id) AS pl_years,
       (SELECT COUNT(DISTINCT year) FROM balancesheet  b WHERE b.company_id=c.id) AS bs_years,
       (SELECT COUNT(DISTINCT year) FROM cashflow      cf WHERE cf.company_id=c.id) AS cf_years,
       (SELECT MIN(year) FROM profitandloss p WHERE p.company_id=c.id) AS earliest_pl_year,
       (SELECT MAX(year) FROM profitandloss p WHERE p.company_id=c.id) AS latest_pl_year
FROM companies c
JOIN sectors s ON s.company_id = c.id
ORDER BY pl_years, c.id;

-- =============================================================================
-- QUERY 04: Companies with <5 years of history in any core table (DQ-16 WARNING)
-- =============================================================================
WITH coverage AS (
  SELECT c.id, c.company_name,
    (SELECT COUNT(DISTINCT year) FROM profitandloss p WHERE p.company_id=c.id) AS pl,
    (SELECT COUNT(DISTINCT year) FROM balancesheet  b WHERE b.company_id=c.id) AS bs,
    (SELECT COUNT(DISTINCT year) FROM cashflow      cf WHERE cf.company_id=c.id) AS cf
  FROM companies c
)
SELECT id, company_name, pl, bs, cf
FROM coverage
WHERE pl < 5 OR bs < 5 OR cf < 5;

-- =============================================================================
-- QUERY 05: NULL counts per critical column (data-completeness check)
-- =============================================================================
SELECT 'profitandloss.sales'             AS column_name, COUNT(*) AS nulls FROM profitandloss WHERE sales             IS NULL
UNION ALL SELECT 'profitandloss.operating_profit', COUNT(*) FROM profitandloss WHERE operating_profit  IS NULL
UNION ALL SELECT 'profitandloss.net_profit',       COUNT(*) FROM profitandloss WHERE net_profit        IS NULL
UNION ALL SELECT 'profitandloss.eps',              COUNT(*) FROM profitandloss WHERE eps               IS NULL
UNION ALL SELECT 'balancesheet.total_assets',      COUNT(*) FROM balancesheet  WHERE total_assets      IS NULL
UNION ALL SELECT 'balancesheet.total_liabilities', COUNT(*) FROM balancesheet  WHERE total_liabilities IS NULL
UNION ALL SELECT 'cashflow.net_cash_flow',         COUNT(*) FROM cashflow      WHERE net_cash_flow     IS NULL
UNION ALL SELECT 'companies.company_name',         COUNT(*) FROM companies     WHERE company_name      IS NULL
UNION ALL SELECT 'sectors.broad_sector',           COUNT(*) FROM sectors       WHERE broad_sector      IS NULL
UNION ALL SELECT 'stock_prices.close_price',       COUNT(*) FROM stock_prices  WHERE close_price       IS NULL
UNION ALL SELECT 'documents.Annual_Report',        COUNT(*) FROM documents     WHERE Annual_Report     IS NULL;

-- =============================================================================
-- QUERY 06: Year distribution — company count + avg sales per FY
-- =============================================================================
SELECT year, COUNT(*) AS companies, ROUND(AVG(sales), 2) AS avg_sales_cr
FROM profitandloss
GROUP BY year
ORDER BY year;

-- =============================================================================
-- QUERY 07: Top 10 companies by latest-year sales (revenue leaders)
-- =============================================================================
SELECT p.company_id, c.company_name, s.broad_sector,
       ROUND(p.sales, 2)            AS sales_cr,
       ROUND(p.net_profit, 2)       AS net_profit_cr,
       ROUND(p.operating_profit, 2) AS op_profit_cr,
       ROUND(p.opm_percentage, 2)   AS opm_pct
FROM profitandloss p
JOIN companies c ON c.id = p.company_id
JOIN sectors   s ON s.company_id = c.id
WHERE p.year = (SELECT MAX(year) FROM profitandloss)
ORDER BY p.sales DESC
LIMIT 10;

-- =============================================================================
-- QUERY 08: Top 10 companies by display ROE (companies.roe_percentage)
-- =============================================================================
SELECT c.id, c.company_name, s.broad_sector,
       c.roe_percentage  AS roe_pct,
       c.roce_percentage AS roce_pct
FROM companies c
JOIN sectors s ON s.company_id = c.id
WHERE c.roe_percentage IS NOT NULL
ORDER BY c.roe_percentage DESC
LIMIT 10;

-- =============================================================================
-- QUERY 09: Sector composition — company counts + aggregate index weight
-- =============================================================================
SELECT s.broad_sector,
       COUNT(*)                        AS companies,
       ROUND(SUM(s.index_weight_pct), 2) AS total_weight_pct,
       ROUND(AVG(s.index_weight_pct), 3) AS avg_weight_pct
FROM sectors s
GROUP BY s.broad_sector
ORDER BY companies DESC;

-- =============================================================================
-- QUERY 10: Latest-year market cap — top 15 by mcap
-- =============================================================================
SELECT mc.company_id, c.company_name, s.broad_sector,
       mc.year,
       ROUND(mc.market_cap_crore, 2) AS market_cap_cr,
       ROUND(mc.pe_ratio, 2)         AS pe,
       ROUND(mc.pb_ratio, 2)         AS pb,
       ROUND(mc.dividend_yield_pct, 2) AS div_yield_pct
FROM market_cap mc
JOIN companies c ON c.id = mc.company_id
JOIN sectors   s ON s.company_id = c.id
WHERE mc.year = (SELECT MAX(year) FROM market_cap)
ORDER BY mc.market_cap_crore DESC
LIMIT 15;

-- =============================================================================
-- QUERY 11: Companies with negative reserves (accumulated-losses watch list)
-- =============================================================================
SELECT b.company_id, c.company_name, b.year,
       ROUND(b.reserves, 2)       AS reserves_cr,
       ROUND(b.borrowings, 2)     AS borrowings_cr,
       ROUND(b.total_assets, 2)   AS total_assets_cr
FROM balancesheet b
JOIN companies c ON c.id = b.company_id
WHERE b.reserves < 0
ORDER BY b.year DESC, b.company_id;

-- =============================================================================
-- QUERY 12: Balance-sheet imbalance rows (|assets-liab|/assets >= 1%)
-- Expect 0 rows after a clean DQ-04 pass.
-- =============================================================================
SELECT company_id, year,
       ROUND(total_assets, 2)      AS total_assets,
       ROUND(total_liabilities, 2) AS total_liabilities,
       ROUND(ABS(total_assets - total_liabilities) / total_assets * 100, 3) AS imbalance_pct
FROM balancesheet
WHERE total_assets > 0
  AND ABS(total_assets - total_liabilities) / total_assets >= 0.01
ORDER BY imbalance_pct DESC;

-- =============================================================================
-- QUERY 13: Cash-flow reconciliation outliers (|net - (CFO+CFI+CFF)| > 10 Cr)
-- Expect 0 rows after a clean DQ-09 pass.
-- =============================================================================
SELECT company_id, year,
       ROUND(operating_activity, 2) AS cfo,
       ROUND(investing_activity, 2) AS cfi,
       ROUND(financing_activity, 2) AS cff,
       ROUND(net_cash_flow, 2)      AS net,
       ROUND(net_cash_flow - (operating_activity + investing_activity + financing_activity), 2) AS diff
FROM cashflow
WHERE ABS(net_cash_flow - (operating_activity + investing_activity + financing_activity)) > 10
ORDER BY ABS(diff) DESC;

-- =============================================================================
-- QUERY 14: Peer-group benchmark companies (is_benchmark=1)
-- =============================================================================
SELECT pg.peer_group_name, pg.company_id, c.company_name, s.broad_sector
FROM peer_groups pg
JOIN companies c ON c.id = pg.company_id
JOIN sectors   s ON s.company_id = c.id
WHERE pg.is_benchmark = 1
ORDER BY pg.peer_group_name;

-- =============================================================================
-- QUERY 15: 5-year stock-price performance — top 15 by total return (Jan 2020 → Dec 2024)
-- =============================================================================
WITH first_last AS (
  SELECT company_id,
    (SELECT close_price FROM stock_prices p1 WHERE p1.company_id = p.company_id ORDER BY date ASC  LIMIT 1) AS first_price,
    (SELECT close_price FROM stock_prices p2 WHERE p2.company_id = p.company_id ORDER BY date DESC LIMIT 1) AS last_price
  FROM (SELECT DISTINCT company_id FROM stock_prices) p
)
SELECT fl.company_id, c.company_name, s.broad_sector,
       ROUND(fl.first_price, 2) AS price_jan2020,
       ROUND(fl.last_price,  2) AS price_dec2024,
       ROUND((fl.last_price - fl.first_price) / fl.first_price * 100, 2) AS total_return_pct
FROM first_last fl
JOIN companies c ON c.id = fl.company_id
JOIN sectors   s ON s.company_id = c.id
WHERE fl.first_price > 0
ORDER BY total_return_pct DESC
LIMIT 15;

-- =============================================================================
-- QUERY 16: Missing annual reports — companies with <6 filings in 2019-2024
-- =============================================================================
SELECT c.id, c.company_name,
       COUNT(d.Year) AS reports_2019_2024
FROM companies c
LEFT JOIN documents d ON d.company_id = c.id AND d.Year BETWEEN 2019 AND 2024
GROUP BY c.id, c.company_name
HAVING COUNT(d.Year) < 6
ORDER BY reports_2019_2024;

-- =============================================================================
-- QUERY 17: Latest ETL run summary (load_audit most recent 12 entries)
-- =============================================================================
SELECT table_name, rows_in, rows_out, rows_rejected,
       ROUND(runtime_s, 3) AS runtime_s, status, loaded_at
FROM load_audit
WHERE id > (SELECT COALESCE(MAX(id), 0) FROM load_audit) - 12
ORDER BY id;

-- =============================================================================
-- END of exploratory_queries.sql
-- =============================================================================
