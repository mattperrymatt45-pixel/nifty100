#!/usr/bin/env python3
"""Generate realistic synthetic Nifty 100 Excel datasets for Day 5 load testing.

This script produces all 12 Excel files under ``data/raw/`` with the exact
column layout, header-row positions, and approximate row counts specified in
sections 5-6 of the project plan.  The generated data is **synthetic** -
numbers are randomised but realistic - and is intended to exercise the ETL
pipeline end to end, including FK integrity, DQ rules, indexes, and audit
logging.

The generator is **deterministic** (fixed RNG seed) so repeated runs produce
identical files and the Day 5 target row counts are reproducible.

Target row counts per spec sections 5-6:
    companies      = 92
    profitandloss  ~ 1,276   (varies by company history length)
    balancesheet   ~ 1,312
    cashflow       ~ 1,187
    analysis       ~ 20
    documents      ~ 1,585
    prosandcons    ~ 16
    sectors        = 92
    stock_prices   = 5,520   (92 x 60 months)
    market_cap     = 552     (92 x 6 years)
    financial_ratios ~ 1,184
    peer_groups    ~ 56
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---- paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
SUP_DIR = RAW_DIR / "supporting datasets"
RAW_DIR.mkdir(parents=True, exist_ok=True)
SUP_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# ---- master ticker list (92 Nifty 100 constituents, approximate) -----------
# Sorted alphabetically for deterministic ordering; includes all major names
# mentioned in spec §6.5 peer groups.
TICKERS: list[tuple[str, str, str, str, str, float]] = [
    # (ticker, name, broad_sector, sub_sector, mcap_cat, index_weight_pct)
    ("ADANIGREEN", "Adani Green Energy Ltd", "Energy", "Renewable Energy", "Large Cap", 0.85),
    ("ADANIPORTS", "Adani Ports & SEZ Ltd", "Industrials", "Infrastructure", "Large Cap", 0.75),
    ("ADANIPOWER", "Adani Power Ltd", "Energy", "Power & Utilities", "Mid Cap", 0.30),
    ("APOLLOHOSP", "Apollo Hospitals Enterprise Ltd", "Healthcare", "Hospitals", "Large Cap", 0.80),
    ("ASIANPAINT", "Asian Paints Ltd", "Materials", "Paints & Coatings", "Large Cap", 2.30),
    ("ATGL", "Adani Total Gas Ltd", "Energy", "Gas Distribution", "Mid Cap", 0.30),
    ("AXISBANK", "Axis Bank Ltd", "Financials", "Private Banks", "Large Cap", 2.40),
    ("BAJAJ-AUTO", "Bajaj Auto Ltd", "Consumer Discretionary", "Two Wheelers", "Large Cap", 0.85),
    ("BAJFINANCE", "Bajaj Finance Ltd", "Financials", "Consumer Finance", "Large Cap", 3.20),
    ("BAJAJFINSV", "Bajaj Finserv Ltd", "Financials", "Holding Cos", "Large Cap", 0.95),
    ("BANKBARODA", "Bank of Baroda", "Financials", "Public Sector Banks", "Large Cap", 0.70),
    ("BERGEPAINT", "Berger Paints India Ltd", "Materials", "Paints & Coatings", "Mid Cap", 0.45),
    (
        "BHARTIARTL",
        "Bharti Airtel Ltd",
        "Communication Services",
        "Telecommunications",
        "Large Cap",
        3.10,
    ),
    ("BPCL", "Bharat Petroleum Corporation Ltd", "Energy", "Oil & Gas Refining", "Large Cap", 0.95),
    ("BRITANNIA", "Britannia Industries Ltd", "Consumer Staples", "FMCG", "Large Cap", 0.80),
    ("CIPLA", "Cipla Ltd", "Healthcare", "Pharmaceuticals", "Large Cap", 0.90),
    ("CANBK", "Canara Bank", "Financials", "Public Sector Banks", "Mid Cap", 0.40),
    (
        "CHOLAFIN",
        "Cholamandalam Investment & Finance",
        "Financials",
        "Consumer Finance",
        "Mid Cap",
        0.35,
    ),
    ("COALINDIA", "Coal India Ltd", "Energy", "Oil & Gas Exploration", "Large Cap", 1.10),
    (
        "COLPAL",
        "Colgate Palmolive (India) Ltd",
        "Consumer Staples",
        "Personal Products",
        "Mid Cap",
        0.50,
    ),
    ("DABUR", "Dabur India Ltd", "Consumer Staples", "FMCG", "Large Cap", 0.65),
    ("DIVISLAB", "Divi's Laboratories Ltd", "Healthcare", "Pharmaceuticals", "Large Cap", 0.85),
    ("DLF", "DLF Ltd", "Real Estate", "Real Estate", "Large Cap", 0.70),
    ("DRREDDY", "Dr Reddy's Laboratories Ltd", "Healthcare", "Pharmaceuticals", "Large Cap", 1.05),
    ("EICHERMOT", "Eicher Motors Ltd", "Consumer Discretionary", "Automobiles", "Large Cap", 0.85),
    ("GAIL", "GAIL (India) Ltd", "Energy", "Gas Distribution", "Large Cap", 0.55),
    ("GODREJCP", "Godrej Consumer Products Ltd", "Consumer Staples", "FMCG", "Mid Cap", 0.55),
    (
        "GRASIM",
        "Grasim Industries Ltd",
        "Conglomerates / Other",
        "Diversified Conglomerates",
        "Large Cap",
        0.70,
    ),
    ("HAVELLS", "Havells India Ltd", "Industrials", "Consumer Electricals", "Large Cap", 0.70),
    ("HCLTECH", "HCL Technologies Ltd", "Information Technology", "IT Services", "Large Cap", 1.75),
    ("HDFCBANK", "HDFC Bank Ltd", "Financials", "Private Banks", "Large Cap", 4.50),
    ("HDFCLIFE", "HDFC Life Insurance Co Ltd", "Financials", "Life Insurance", "Large Cap", 0.80),
    (
        "HEROMOTOCO",
        "Hero MotoCorp Ltd",
        "Consumer Discretionary",
        "Two Wheelers",
        "Large Cap",
        0.55,
    ),
    ("HINDALCO", "Hindalco Industries Ltd", "Materials", "Metals & Mining", "Large Cap", 0.85),
    ("HINDUNILVR", "Hindustan Unilever Ltd", "Consumer Staples", "FMCG", "Large Cap", 2.80),
    ("ICICIBANK", "ICICI Bank Ltd", "Financials", "Private Banks", "Large Cap", 3.40),
    (
        "ICICIPRULI",
        "ICICI Prudential Life Insurance",
        "Financials",
        "Life Insurance",
        "Large Cap",
        0.65,
    ),
    ("INDUSINDBK", "IndusInd Bank Ltd", "Financials", "Private Banks", "Large Cap", 0.80),
    ("INFY", "Infosys Ltd", "Information Technology", "IT Services", "Large Cap", 3.10),
    ("IOC", "Indian Oil Corporation Ltd", "Energy", "Oil & Gas Refining", "Large Cap", 1.10),
    (
        "IRCTC",
        "Indian Railway Catering & Tourism",
        "Consumer Discretionary",
        "Travel & Tourism",
        "Mid Cap",
        0.45,
    ),
    ("ITC", "ITC Ltd", "Consumer Staples", "FMCG", "Large Cap", 3.80),
    ("JINDALSTEL", "Jindal Steel & Power Ltd", "Materials", "Steel", "Mid Cap", 0.30),
    ("JSWENERGY", "JSW Energy Ltd", "Energy", "Power & Utilities", "Mid Cap", 0.25),
    ("JSWSTEEL", "JSW Steel Ltd", "Materials", "Steel", "Large Cap", 1.05),
    ("KOTAKBANK", "Kotak Mahindra Bank Ltd", "Financials", "Private Banks", "Large Cap", 2.20),
    ("LT", "Larsen & Toubro Ltd", "Industrials", "Engineering & Construction", "Large Cap", 3.00),
    (
        "LICI",
        "Life Insurance Corporation of India",
        "Financials",
        "Life Insurance",
        "Large Cap",
        2.10,
    ),
    ("LTIM", "LTIMindtree Ltd", "Information Technology", "IT Services", "Large Cap", 0.60),
    ("M&M", "Mahindra & Mahindra Ltd", "Consumer Discretionary", "Automobiles", "Large Cap", 1.65),
    ("MARICO", "Marico Ltd", "Consumer Staples", "FMCG", "Mid Cap", 0.50),
    (
        "MARUTI",
        "Maruti Suzuki India Ltd",
        "Consumer Discretionary",
        "Automobiles",
        "Large Cap",
        2.30,
    ),
    ("NESTLEIND", "Nestle India Ltd", "Consumer Staples", "Food & Beverages", "Large Cap", 1.30),
    ("NHPC", "NHPC Ltd", "Energy", "Power & Utilities", "Mid Cap", 0.35),
    ("NTPC", "NTPC Ltd", "Energy", "Power & Utilities", "Large Cap", 1.80),
    (
        "ONGC",
        "Oil & Natural Gas Corporation Ltd",
        "Energy",
        "Oil & Gas Exploration",
        "Large Cap",
        1.50,
    ),
    ("PNB", "Punjab National Bank", "Financials", "Public Sector Banks", "Mid Cap", 0.35),
    (
        "POWERGRID",
        "Power Grid Corporation of India",
        "Energy",
        "Power Transmission",
        "Large Cap",
        1.20,
    ),
    ("RELIANCE", "Reliance Industries Ltd", "Energy", "Oil & Gas Refining", "Large Cap", 4.20),
    ("SBILIFE", "SBI Life Insurance Co Ltd", "Financials", "Life Insurance", "Large Cap", 0.85),
    ("SBIN", "State Bank of India", "Financials", "Public Sector Banks", "Large Cap", 2.50),
    ("SHREECEM", "Shree Cement Ltd", "Materials", "Cement", "Large Cap", 0.65),
    ("SHRIRAMFIN", "Shriram Finance Ltd", "Financials", "Consumer Finance", "Large Cap", 0.60),
    (
        "SUNPHARMA",
        "Sun Pharmaceutical Industries Ltd",
        "Healthcare",
        "Pharmaceuticals",
        "Large Cap",
        2.40,
    ),
    (
        "TATACONSUM",
        "Tata Consumer Products Ltd",
        "Consumer Staples",
        "Food Products",
        "Large Cap",
        0.70,
    ),
    ("TATAMOTORS", "Tata Motors Ltd", "Consumer Discretionary", "Automobiles", "Large Cap", 1.40),
    ("TATAPOWER", "Tata Power Co Ltd", "Energy", "Power & Utilities", "Large Cap", 0.75),
    ("TATASTEEL", "Tata Steel Ltd", "Materials", "Steel", "Large Cap", 1.30),
    (
        "TCS",
        "Tata Consultancy Services Ltd",
        "Information Technology",
        "IT Services",
        "Large Cap",
        4.20,
    ),
    ("TECHM", "Tech Mahindra Ltd", "Information Technology", "IT Services", "Large Cap", 0.95),
    ("TITAN", "Titan Company Ltd", "Consumer Discretionary", "Gems & Jewellery", "Large Cap", 1.70),
    ("TORNTPHARM", "Torrent Pharmaceuticals Ltd", "Healthcare", "Pharmaceuticals", "Mid Cap", 0.45),
    (
        "TVSMOTOR",
        "TVS Motor Company Ltd",
        "Consumer Discretionary",
        "Two Wheelers",
        "Mid Cap",
        0.40,
    ),
    ("ULTRACEMCO", "UltraTech Cement Ltd", "Materials", "Cement", "Large Cap", 1.20),
    ("UPL", "UPL Ltd", "Materials", "Specialty Chemicals", "Large Cap", 0.55),
    ("WIPRO", "Wipro Ltd", "Information Technology", "IT Services", "Large Cap", 1.10),
    (
        "ZEEL",
        "Zee Entertainment Enterprises Ltd",
        "Communication Services",
        "Internet & Platforms",
        "Mid Cap",
        0.25,
    ),
    (
        "ADANIENT",
        "Adani Enterprises Ltd",
        "Conglomerates / Other",
        "Diversified Conglomerates",
        "Large Cap",
        1.10,
    ),
    ("BAJAJHLDNG", "Bajaj Holdings & Investment", "Financials", "Holding Cos", "Mid Cap", 0.30),
    ("BOSCHLTD", "Bosch Ltd", "Consumer Discretionary", "Auto Ancillaries", "Large Cap", 0.55),
    ("DMART", "Avenue Supermarts Ltd", "Consumer Discretionary", "Retail", "Large Cap", 1.30),
    ("HINDPETRO", "Hindustan Petroleum Corp Ltd", "Energy", "Oil & Gas Refining", "Mid Cap", 0.35),
    ("INDIGO", "InterGlobe Aviation Ltd", "Consumer Discretionary", "Airlines", "Large Cap", 0.65),
    (
        "NAUKRI",
        "Info Edge (India) Ltd",
        "Communication Services",
        "Internet & Platforms",
        "Large Cap",
        0.55,
    ),
    ("OBEROIRLTY", "Oberoi Realty Ltd", "Real Estate", "Real Estate", "Mid Cap", 0.30),
    (
        "PIDILITIND",
        "Pidilite Industries Ltd",
        "Materials",
        "Specialty Chemicals",
        "Large Cap",
        0.80,
    ),
    ("SIEMENS", "Siemens Ltd", "Industrials", "Capital Goods", "Large Cap", 0.75),
    (
        "TATACOMM",
        "Tata Communications Ltd",
        "Communication Services",
        "Telecommunications",
        "Mid Cap",
        0.30,
    ),
    ("TORNTPOWER", "Torrent Power Ltd", "Energy", "Power & Utilities", "Mid Cap", 0.30),
    ("VEDL", "Vedanta Ltd", "Materials", "Metals & Mining", "Large Cap", 0.80),
    ("BANDHANBNK", "Bandhan Bank Ltd", "Financials", "Private Banks", "Mid Cap", 0.30),
    ("BIOCON", "Biocon Ltd", "Healthcare", "Pharmaceuticals", "Mid Cap", 0.30),
]

# Ensure exactly 92
assert len(TICKERS) == 92, f"Expected 92 tickers, got {len(TICKERS)}"

ALL_TICKERS = [t[0] for t in TICKERS]
TICKER_INFO = {t[0]: t for t in TICKERS}

# FY labels Mar-10 .. Mar-24 (15 years)
FY_LABELS = [f"Mar-{str(y)[-2:]}" for y in range(2010, 2025)]
# Calendar years for documents 2008-2025 (some companies have multiple filings)
DOC_YEARS = list(range(2008, 2026))
# Market cap years 2019-2024
MCAP_YEARS = list(range(2019, 2025))
# Stock prices Jan 2020 - Dec 2024 (60 months)
PRICE_DATES = pd.date_range("2020-01-01", "2024-12-01", freq="MS").strftime("%Y-%m-%d").tolist()


def _metarow(sheet_name: str) -> pd.DataFrame:
    """Return a single metadata row for core-file row 0 (screener.in style)."""
    return pd.DataFrame([{"Company": "Rs Cr", "Data Source": f"Screener.in - {sheet_name}"}])


# ---------------------------------------------------------------------------
# Core files — header=1 with metadata row 0
# ---------------------------------------------------------------------------


def gen_companies() -> pd.DataFrame:
    """Companies master: 92 rows, 12 columns."""
    rows = []
    for tick, name, _sector, sub, _mcap, _wt in TICKERS:
        fv = random.choice([1, 2, 5, 10])
        bv = round(random.uniform(30, 800), 2)
        roce = round(random.uniform(5, 60), 2)
        roe = round(random.uniform(3, 45), 2)
        about = f"{name} is a leading company in the {sub} sector " "with operations across India."
        rows.append(
            {
                "id": tick,
                "company_logo": f"https://logo.example.com/{tick}.png",
                "company_name": name,
                "chart_link": (f"https://in.tradingview.com/chart/?symbol=NSE%3A{tick}"),
                "about_company": about,
                "website": f"https://www.{tick.lower().replace('-', '')}.co.in/",
                "nse_profile": (f"https://www.nseindia.com/get-quotes/equity?symbol={tick}"),
                "bse_profile": (f"https://www.bseindia.com/stock-share-price/{tick.lower()}/"),
                "face_value": fv,
                "book_value": bv,
                "roce_percentage": roce,
                "roe_percentage": roe,
            }
        )
    return pd.DataFrame(rows)


def gen_profitandloss() -> pd.DataFrame:
    """P&L: ~1,276 rows, 15 columns.

    Realistic accounting: sales > expenses > 0 (non-banks); op_profit = sales - expenses
    (modest rounding for DQ-05 to pass). We add small noise to opm_pct to keep it
    within DQ-05 tolerance (±1%).
    """
    rows = []
    rid = 1
    for tick, _name, sector, _sub, *_ in TICKERS:
        # Companies have varying history length (avg ~13.9 to hit ~1276)
        n_years = random.choice([12, 13, 14, 14, 14, 15, 15])
        years = FY_LABELS[-n_years:]
        # Base sales scales by sector
        base_sales = {
            "Financials": 30000,
            "Energy": 60000,
            "IT": 15000,
            "Consumer Discretionary": 20000,
            "Consumer Staples": 12000,
            "Healthcare": 8000,
            "Materials": 18000,
            "Industrials": 25000,
            "Communication Services": 22000,
            "Real Estate": 4000,
            "Conglomerates / Other": 20000,
        }.get(sector, 15000)
        sales = base_sales * random.uniform(0.5, 2.5)
        # Track a growth rate
        growth = random.uniform(0.05, 0.20)
        for fy in years:
            sales *= 1 + growth + random.uniform(-0.05, 0.05)
            # Banks have very different P&L but we treat them generically with sales>0
            op_margin = random.uniform(0.08, 0.35)
            op_profit = sales * op_margin
            expenses = sales - op_profit  # enforce sales - expenses = op_profit exactly
            opm_pct = op_margin * 100  # exact match so DQ-05 tolerance passes
            other_income = sales * random.uniform(0.005, 0.05)
            interest = sales * random.uniform(0.0, 0.08)
            depreciation = sales * random.uniform(0.01, 0.06)
            pbt = op_profit + other_income - interest - depreciation
            tax_pct = random.uniform(22, 30) if pbt > 0 else 0
            net_profit = pbt * (1 - tax_pct / 100) if pbt > 0 else pbt
            # Shares outstanding implied from base
            shares = sales / random.uniform(50, 500)  # rough
            eps = net_profit / shares if shares > 0 else 0
            div_payout = random.uniform(10, 70) if net_profit > 0 else 0
            rows.append(
                {
                    "id": rid,
                    "company_id": tick,
                    "year": fy,
                    "sales": round(sales, 2),
                    "expenses": round(expenses, 2),
                    "operating_profit": round(op_profit, 2),
                    "opm_percentage": round(opm_pct, 2),
                    "other_income": round(other_income, 2),
                    "interest": round(interest, 2),
                    "depreciation": round(depreciation, 2),
                    "profit_before_tax": round(pbt, 2),
                    "tax_percentage": round(tax_pct, 2),
                    "net_profit": round(net_profit, 2),
                    "eps": round(eps, 2),
                    "dividend_payout": round(div_payout, 2),
                }
            )
            rid += 1
    return pd.DataFrame(rows)


def gen_balancesheet(pl_df: pd.DataFrame) -> pd.DataFrame:
    """Balance sheet: ~1,312 rows, 13 columns.

    Must balance: total_assets == total_liabilities (within DQ-04 tolerance).
    We construct from the identity: equity + liab = assets.
    """
    rows = []
    rid = 1
    seen_keys: set[tuple[str, str]] = set()
    for (tick, fy), grp in pl_df.groupby(["company_id", "year"]):
        sales = float(grp["sales"].iloc[0])
        np_ = float(grp["net_profit"].iloc[0])
        # Assets scale ~2x annual sales for industrials; ~0.3x for banks.
        info = TICKER_INFO[tick]
        sector = info[2]
        asset_mult = 1.8 if sector != "Financials" else 0.4
        total_assets = sales * asset_mult * random.uniform(0.8, 1.3)
        # equity side
        equity_cap = random.choice([5, 10, 20, 50, 100, 200, 500])
        # Build reserves ~ cumulative profits
        fy_idx = FY_LABELS.index(fy) if fy in FY_LABELS else 10
        reserves = max(np_ * (fy_idx + 1) * random.uniform(3, 7), equity_cap * 5)
        # Liabilities
        is_bank = sector == "Financials"
        if is_bank:
            borrowings = total_assets * random.uniform(0.6, 0.85)
        else:
            borrowings = total_assets * random.uniform(0.0, 0.4)
        # Round liability components first and plug other_liabilities so
        # equity_cap + reserves + borrowings + other_liabilities == total_assets exactly.
        eq_r = round(equity_cap, 2)
        res_r = round(reserves, 2)
        bor_r = round(borrowings, 2)
        ta_r = round(total_assets, 2)
        oth_l_r = round(ta_r - eq_r - res_r - bor_r, 2)

        # Asset side breakdown (rounded); plug other_asset so they sum to ta_r.
        fixed_assets = total_assets * random.uniform(0.15, 0.55)
        cwip = fixed_assets * random.uniform(0.01, 0.10)
        investments = total_assets * random.uniform(0.0, 0.25)
        fa_r = round(fixed_assets, 2)
        cw_r = round(cwip, 2)
        inv_r = round(investments, 2)
        oth_a_r = round(ta_r - fa_r - cw_r - inv_r, 2)
        rows.append(
            {
                "id": rid,
                "company_id": tick,
                "year": fy,
                "equity_capital": eq_r,
                "reserves": res_r,
                "borrowings": bor_r,
                "other_liabilities": oth_l_r,
                "total_liabilities": ta_r,
                "fixed_assets": fa_r,
                "cwip": cw_r,
                "investments": inv_r,
                "other_asset": oth_a_r,
                "total_assets": ta_r,
            }
        )
        seen_keys.add((tick, fy))
        rid += 1
    # Add extra rows to hit ~1312: earlier history for companies (still valid FKs).
    extras_needed = max(0, 1310 - len(rows))
    extra_years = FY_LABELS[:8]  # early / mid history
    attempts = 0
    while extras_needed > 0 and attempts < extras_needed * 5:
        attempts += 1
        tick = random.choice(ALL_TICKERS)
        fy = random.choice(extra_years)
        if (tick, fy) in seen_keys:
            continue
        sales = random.uniform(5000, 50000)
        total_assets = sales * random.uniform(1.0, 2.5)
        equity_cap = random.choice([5, 10, 20])
        reserves = total_assets * random.uniform(0.3, 0.6)
        borrowings = total_assets * random.uniform(0.1, 0.4)
        fixed_assets = total_assets * random.uniform(0.2, 0.5)
        cwip = fixed_assets * 0.05
        investments = total_assets * random.uniform(0, 0.2)
        ta_r = round(total_assets, 2)
        eq_r = round(equity_cap, 2)
        res_r = round(reserves, 2)
        bor_r = round(borrowings, 2)
        oth_l_r = round(ta_r - eq_r - res_r - bor_r, 2)
        fa_r = round(max(fixed_assets, 0), 2)
        cw_r = round(max(cwip, 0), 2)
        inv_r = round(max(investments, 0), 2)
        oth_a_r = round(ta_r - fa_r - cw_r - inv_r, 2)
        rows.append(
            {
                "id": rid,
                "company_id": tick,
                "year": fy,
                "equity_capital": eq_r,
                "reserves": res_r,
                "borrowings": bor_r,
                "other_liabilities": oth_l_r,
                "total_liabilities": ta_r,
                "fixed_assets": fa_r,
                "cwip": cw_r,
                "investments": inv_r,
                "other_asset": oth_a_r,
                "total_assets": ta_r,
            }
        )
        seen_keys.add((tick, fy))
        rid += 1
        extras_needed -= 1
    return pd.DataFrame(rows)


def gen_cashflow(pl_df: pd.DataFrame, bs_df: pd.DataFrame) -> pd.DataFrame:
    """Cash flow: ~1,187 rows, 7 columns.

    Net cash flow = CFO + CFI + CFF (within ₹10 Cr tolerance per DQ-09).
    """
    rows = []
    rid = 1
    for (tick, fy), grp in pl_df.groupby(["company_id", "year"]):
        # Most companies have CF (~93% coverage per spec row count 1187/1276)
        if random.random() < 0.06:
            continue
        sales = float(grp["sales"].iloc[0])
        np_ = float(grp["net_profit"].iloc[0])
        # CFO ~ 1.1x PAT for healthy cos
        cfo = np_ * random.uniform(0.8, 1.6) + sales * random.uniform(-0.02, 0.05)
        # CFI is usually negative (capex)
        cfi = -sales * random.uniform(0.03, 0.15)
        # CFF is the swing factor; net = CFO+CFI+CFF exactly after rounding.
        cff = -(cfo + cfi) * random.uniform(0.5, 1.2)
        cfo_r = round(cfo, 2)
        cfi_r = round(cfi, 2)
        cff_r = round(cff, 2)
        net_r = round(cfo_r + cfi_r + cff_r, 2)
        rows.append(
            {
                "id": rid,
                "company_id": tick,
                "year": fy,
                "operating_activity": cfo_r,
                "investing_activity": cfi_r,
                "financing_activity": cff_r,
                "net_cash_flow": net_r,
            }
        )
        rid += 1
    return pd.DataFrame(rows)


def gen_analysis() -> pd.DataFrame:
    """Analysis: 20 rows (partial coverage), compounded growth text."""
    chosen = random.sample(ALL_TICKERS, 20)
    rows = []
    for i, tick in enumerate(chosen, start=1):
        s10 = round(random.uniform(5, 25), 1)
        p5 = round(random.uniform(3, 20), 1)
        cagr = round(random.uniform(8, 30), 1)
        roe = round(random.uniform(10, 25), 1)
        rows.append(
            {
                "id": i,
                "company_id": tick,
                "compounded_sales_growth": f"10 Years: {s10}%",
                "compounded_profit_growth": f"5 Years: {p5}%",
                "stock_price_cagr": f"10 Years: {cagr}%",
                "roe": f"10 Years: {roe}%",
            }
        )
    return pd.DataFrame(rows)


def gen_documents() -> pd.DataFrame:
    """Documents: ~1,585 rows, Annual_Report URLs, calendar Year."""
    rows = []
    rid = 1
    seen_pairs: set[tuple[str, int]] = set()
    for tick in ALL_TICKERS:
        # Most companies have ~15-19 years of documents (to hit 1585 total)
        n_docs = random.randint(15, 19)
        years = sorted(random.sample(DOC_YEARS, min(n_docs, len(DOC_YEARS))))
        for y in years:
            url = f"https://www.bseindia.com/bseplus/AnnualReport/{tick}/{tick}_{y}.pdf"
            # 5% chance of broken URL (DQ-13)
            if random.random() < 0.05:
                url = f"https://www.bseindia.com/missing/{tick}_{y}.pdf"
            rows.append(
                {
                    "id": rid,
                    "company_id": tick,
                    "Year": y,
                    "Annual_Report": url,
                }
            )
            seen_pairs.add((tick, y))
            rid += 1
    # Top up if needed to hit ~1585
    target = 1585
    attempts = 0
    while len(rows) < target and attempts < target * 5:
        attempts += 1
        tick = random.choice(ALL_TICKERS)
        y = random.choice(DOC_YEARS)
        if (tick, y) in seen_pairs:
            continue
        url = f"https://www.bseindia.com/bseplus/AnnualReport/{tick}/{tick}_{y}.pdf"
        rows.append(
            {
                "id": rid,
                "company_id": tick,
                "Year": y,
                "Annual_Report": url,
            }
        )
        seen_pairs.add((tick, y))
        rid += 1
    return pd.DataFrame(rows)


def gen_prosandcons() -> pd.DataFrame:
    """Pros & Cons: 16 rows (partial)."""
    pros_text = [
        "Strong brand moat and consistent market share leader.",
        "Healthy operating cash flows and low debt on balance sheet.",
        "Diversified revenue streams across geographies.",
        "High return ratios (ROCE/ROE > 20%) over the last decade.",
        "Consistent dividend history with rising payout trend.",
        "Beneficiary of structural industry tailwinds.",
        "Best-in-class management with strong capital allocation track record.",
        "Scalable digital platform driving margin expansion.",
    ]
    cons_text = [
        "High raw material price volatility can pressure near-term margins.",
        "Regulatory risk remains a key monitorable going forward.",
        "Valuation premium leaves little room for execution misses.",
        "Slowing rural demand and competitive intensity are concerns.",
        "Currency headwinds may impact overseas earnings translation.",
        "Leveraged balance sheet post recent acquisitions.",
        "Customer concentration risk with top 10 clients driving large revenue share.",
        "Succession / key-person risk in founder-led operations.",
    ]
    chosen = random.sample(ALL_TICKERS, 16)
    rows = []
    for i, tick in enumerate(chosen):
        rows.append(
            {
                "id": i + 1,
                "company_id": tick,
                "pros": pros_text[i % len(pros_text)],
                "cons": cons_text[i % len(cons_text)],
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Supplementary files — header=0, NO metadata row
# ---------------------------------------------------------------------------


def gen_sectors() -> pd.DataFrame:
    """Sectors: 92 rows, full coverage."""
    rows = []
    for tick, _name, sector, sub, mcap, wt in TICKERS:
        rows.append(
            {
                "company_id": tick,
                "broad_sector": sector,
                "sub_sector": sub,
                "index_weight_pct": round(wt, 2),
                "market_cap_category": mcap,
            }
        )
    return pd.DataFrame(rows)


def gen_stock_prices() -> pd.DataFrame:
    """Stock prices: 5,520 rows (92 x 60 months)."""
    rows = []
    for tick, *_ in TICKERS:
        # starting price
        price = random.uniform(200, 3000)
        for d in PRICE_DATES:
            ret = random.gauss(0.01, 0.07)  # ~1% monthly drift, 7% vol
            price = max(price * (1 + ret), 5)
            high = price * (1 + abs(random.gauss(0, 0.03)))
            low = price * (1 - abs(random.gauss(0, 0.03)))
            open_p = price * (1 + random.gauss(0, 0.01))
            vol = random.randint(100_000, 50_000_000)
            rows.append(
                {
                    "company_id": tick,
                    "date": d,
                    "open_price": round(open_p, 2),
                    "high_price": round(max(high, open_p, price), 2),
                    "low_price": round(min(low, open_p, price), 2),
                    "close_price": round(price, 2),
                    "volume": vol,
                    "adjusted_close": round(price, 2),
                }
            )
    return pd.DataFrame(rows)


def gen_market_cap() -> pd.DataFrame:
    """Market cap: 552 rows (92 x 6 years)."""
    rows = []
    for tick, *_ in TICKERS:
        mcap = random.uniform(20_000, 1_500_000)
        for y in MCAP_YEARS:
            mcap *= 1 + random.uniform(-0.05, 0.25)
            ev = mcap + random.uniform(-50_000, 100_000)
            pe = random.uniform(8, 45)
            pb = random.uniform(0.8, 12)
            ev_ebitda = random.uniform(6, 30)
            dy = random.uniform(0.3, 4.0)
            rows.append(
                {
                    "company_id": tick,
                    "year": y,
                    "market_cap_crore": round(mcap, 2),
                    "enterprise_value_crore": round(ev, 2),
                    "pe_ratio": round(pe, 2),
                    "pb_ratio": round(pb, 2),
                    "ev_ebitda": round(ev_ebitda, 2),
                    "dividend_yield_pct": round(dy, 2),
                }
            )
    return pd.DataFrame(rows)


def gen_financial_ratios(
    pl_df: pd.DataFrame, bs_df: pd.DataFrame, cf_df: pd.DataFrame
) -> pd.DataFrame:
    """Financial ratios: ~1,184 rows, 16 columns — derived from P&L + BS + CF."""
    # Index by (company_id, year)
    pl_idx = {(r.company_id, r.year): r for r in pl_df.itertuples(index=False)}
    bs_idx = {(r.company_id, r.year): r for r in bs_df.itertuples(index=False)}
    cf_idx = {(r.company_id, r.year): r for r in cf_df.itertuples(index=False)}
    rows = []
    keys = sorted(set(pl_idx) & set(bs_idx))
    # Trim to ~1184 rows
    random.shuffle(keys)
    target = 1184
    for tick, fy in keys[:target]:
        pl = pl_idx[(tick, fy)]
        bs = bs_idx[(tick, fy)]
        cf = cf_idx.get((tick, fy))
        sales = pl.sales
        np_ = pl.net_profit
        op = pl.operating_profit
        equity = bs.equity_capital + bs.reserves
        npm = (np_ / sales * 100) if sales else None
        opm = pl.opm_percentage
        roe = (np_ / equity * 100) if equity else None
        roce = (op / (equity + bs.borrowings) * 100) if (equity + bs.borrowings) else None
        de = (bs.borrowings / equity) if equity else 0
        ic = ((op + pl.other_income) / pl.interest) if pl.interest else None
        at = (sales / bs.total_assets) if bs.total_assets else None
        if cf is not None:
            fcf = cf.operating_activity + cf.investing_activity
            capex = abs(cf.investing_activity)
            cfo = cf.operating_activity
        else:
            fcf = np_ * random.uniform(0.3, 0.9)
            capex = sales * random.uniform(0.02, 0.10)
            cfo = np_ * random.uniform(0.9, 1.4)
        eps = pl.eps
        bvps = (
            ((bs.equity_capital + bs.reserves) / (bs.equity_capital / 1))
            if bs.equity_capital
            else None
        )
        # better bvps: equity / shares
        shares = (np_ / eps) if eps and eps > 0 else bs.equity_capital
        bvps = (equity / shares) if shares else None
        div_pay = pl.dividend_payout
        rows.append(
            {
                "company_id": tick,
                "year": fy,
                "net_profit_margin_pct": round(npm, 2) if npm is not None else None,
                "operating_profit_margin_pct": round(opm, 2) if opm is not None else None,
                "return_on_equity_pct": round(roe, 2) if roe is not None else None,
                "roce_pct": round(roce, 2) if roce is not None else None,
                "debt_to_equity": round(de, 2) if de is not None else None,
                "interest_coverage": round(ic, 2) if ic is not None else None,
                "asset_turnover": round(at, 2) if at is not None else None,
                "free_cash_flow_cr": round(fcf, 2),
                "capex_cr": round(capex, 2),
                "earnings_per_share": round(eps, 2) if eps is not None else None,
                "book_value_per_share": round(bvps, 2) if bvps is not None else None,
                "dividend_payout_ratio_pct": round(div_pay, 2) if div_pay is not None else None,
                "total_debt_cr": round(bs.borrowings, 2),
                "cash_from_operations_cr": round(cfo, 2),
            }
        )
    return pd.DataFrame(rows)


def gen_peer_groups() -> pd.DataFrame:
    """Peer groups: ~56 rows from spec §6.5."""
    groups = {
        "Private Banks": (
            ["HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
            "HDFCBANK",
        ),
        "Public Banks": (["SBIN", "BANKBARODA", "CANBK", "PNB"], "SBIN"),
        "IT Services": (["TCS", "INFY", "HCLTECH", "TECHM", "LTIM"], "TCS"),
        "Pharmaceuticals": (
            ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "TORNTPHARM"],
            "SUNPHARMA",
        ),
        "Automobiles": (
            ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR"],
            "MARUTI",
        ),
        "Life Insurance": (["LICI", "HDFCLIFE", "SBILIFE", "ICICIPRULI"], "LICI"),
        "Oil & Gas": (["RELIANCE", "ONGC", "BPCL", "IOC", "GAIL"], "RELIANCE"),
        "Power & Utilities": (
            ["NTPC", "POWERGRID", "TATAPOWER", "ADANIPOWER", "NHPC", "JSWENERGY", "ADANIGREEN"],
            "NTPC",
        ),
        "Steel & Metals": (["TATASTEEL", "JSWSTEEL", "JINDALSTEL", "HINDALCO"], "TATASTEEL"),
        "FMCG": (
            ["HINDUNILVR", "ITC", "BRITANNIA", "DABUR", "NESTLEIND", "GODREJCP", "TATACONSUM"],
            "HINDUNILVR",
        ),
        "Consumer Finance": (["BAJFINANCE", "CHOLAFIN", "SHRIRAMFIN"], "BAJFINANCE"),
    }
    rows = []
    for grp_name, (members, bench) in groups.items():
        for m in members:
            if m in ALL_TICKERS:
                rows.append(
                    {
                        "company_id": m,
                        "peer_group_name": grp_name,
                        "is_benchmark": 1 if m == bench else 0,
                    }
                )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Excel writers
# ---------------------------------------------------------------------------


def _write_core(df: pd.DataFrame, path: Path, sheet: str) -> None:
    """Write a core dataset: row 0 = metadata, row 1 = headers, row 2+ = data.

    The Screener.in export format has a metadata row at index 0, then the
    real header row at index 1, so the loader uses ``header=1``. We replicate
    that layout using openpyxl directly for precise control.
    """
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet

    cols = list(df.columns)
    # Row 1 (1-indexed): metadata
    meta_values = ["Rs Cr", f"Screener.in export - {sheet}"] + [""] * (len(cols) - 2)
    ws.append(meta_values)
    # Row 2 (1-indexed): real headers
    ws.append(cols)
    # Rows 3+: data
    for row in df.itertuples(index=False, name=None):
        ws.append(list(row))
    wb.save(path)


def _write_supp(df: pd.DataFrame, path: Path, sheet: str = "Sheet1") -> None:
    """Write a supplementary dataset: row 0 = headers, row 1+ = data."""
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name=sheet, index=False)


def generate_all(raw_root: Path | None = None) -> dict[str, int]:
    """Generate all 12 synthetic Excel files under ``raw_root``.

    Returns a dict mapping dataset name → row count. If ``raw_root`` is
    None, writes to the default ``data/raw/`` location.

    Re-seeds both ``random`` and ``numpy.random`` from SEED on every call so
    the generated data is fully deterministic regardless of how many times
    the RNG state was consumed between invocations (important when multiple
    tests exercise the generator in one process).
    """
    random.seed(SEED)
    np.random.seed(SEED)
    if raw_root is None:
        raw_root = RAW_DIR
        sup_root = SUP_DIR
    else:
        raw_root = Path(raw_root)
        sup_root = raw_root / "supporting datasets"
    raw_root.mkdir(parents=True, exist_ok=True)
    sup_root.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}

    comp = gen_companies()
    _write_core(comp, raw_root / "companies.xlsx", "Companies")
    counts["companies"] = len(comp)

    pl = gen_profitandloss()
    _write_core(pl, raw_root / "profitandloss.xlsx", "Profit & Loss")
    counts["profitandloss"] = len(pl)

    bs = gen_balancesheet(pl)
    _write_core(bs, raw_root / "balancesheet.xlsx", "Balance Sheet")
    counts["balancesheet"] = len(bs)

    cf = gen_cashflow(pl, bs)
    _write_core(cf, raw_root / "cashflow.xlsx", "Cash Flow")
    counts["cashflow"] = len(cf)

    an = gen_analysis()
    _write_core(an, raw_root / "analysis.xlsx", "Analysis")
    counts["analysis"] = len(an)

    doc = gen_documents()
    _write_core(doc, raw_root / "documents.xlsx", "Documents")
    counts["documents"] = len(doc)

    pc = gen_prosandcons()
    _write_core(pc, raw_root / "prosandcons.xlsx", "Pros & Cons")
    counts["prosandcons"] = len(pc)

    sec = gen_sectors()
    _write_supp(sec, sup_root / "sectors.xlsx")
    counts["sectors"] = len(sec)

    sp = gen_stock_prices()
    _write_supp(sp, sup_root / "stock_prices.xlsx")
    counts["stock_prices"] = len(sp)

    mc = gen_market_cap()
    _write_supp(mc, sup_root / "market_cap.xlsx")
    counts["market_cap"] = len(mc)

    fr = gen_financial_ratios(pl, bs, cf)
    _write_supp(fr, sup_root / "financial_ratios.xlsx")
    counts["financial_ratios"] = len(fr)

    pg = gen_peer_groups()
    _write_supp(pg, sup_root / "peer_groups.xlsx")
    counts["peer_groups"] = len(pg)

    return counts


def main() -> None:
    print("Generating companies ...")
    counts = generate_all(RAW_DIR)
    for name, n in counts.items():
        print(f"  {name}: {n} rows")
    print("\nDone. Files written to:", RAW_DIR)


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT))
    main()
