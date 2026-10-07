#!/usr/bin/env bash
# =============================================================================
# Nifty 100 Financial Intelligence Platform - Render Build Script
# =============================================================================
# Usage (Render Build Command):  ./build.sh
#
# Steps:
#   1. Install Python dependencies from requirements.txt
#   2. Run ETL pipeline to populate the SQLite DB from raw Excel files
#      (required on fresh deploys because db/*.db is gitignored and starts
#      empty on Render ephemeral storage)
#   3. Populate the financial_ratios table (CAGR, ROCE, ROE, D/E, FCF, etc.)
#   4. Run the Day 26 valuation summary generator (valuation_summary.xlsx
#      and valuation_flags.csv)
#
# The script uses `set -e` so any failing step aborts the build immediately
# and surfaces the error in the Render build log.
# =============================================================================

set -euo pipefail

echo "=========================================="
echo " Nifty 100 Platform — Build"
echo "=========================================="

# ---- 1. Install dependencies ------------------------------------------------
echo ""
echo "[1/4] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# ---- 2. ETL — load raw Excel files into the (fresh) SQLite DB ---------------
#    This is required because db/nifty100.db is in .gitignore; Render starts
#    with an empty db/ directory. Skip --reset safely (DB is fresh) but use it
#    to guarantee idempotent behaviour if the disk cache persists across deploys.
echo ""
echo "[2/4] Running ETL pipeline (load raw Excel -> SQLite)..."
python scripts/run_etl.py --reset

# ---- 3. Populate derived financial_ratios table -----------------------------
echo ""
echo "[3/4] Populating financial_ratios (CAGR, ROCE, ROE, D/E, FCF, etc.)..."
python scripts/populate_ratios.py --reset --spot-check

# ---- 4. Valuation summary (Day 26) ------------------------------------------
echo ""
echo "[4/4] Generating valuation summary & flags..."
python scripts/day26_valuation.py

echo ""
echo "=========================================="
echo " Build complete."
echo "=========================================="
echo ""
echo "Run the API with:       uvicorn src.api.main:app --host 0.0.0.0 --port \$PORT"
echo "Run the dashboard with: streamlit run src/dashboard/app.py --server.port \$PORT --server.address 0.0.0.0"
