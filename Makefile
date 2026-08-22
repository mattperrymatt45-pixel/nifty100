# =============================================================================
# Nifty 100 Financial Intelligence Platform - Makefile
# Common developer commands. Run `make help` to see all targets.
# =============================================================================

.PHONY: help install install-dev test lint format clean run-dashboard run-api load load-reset dq-review

# Default target
help:
	@echo "Nifty 100 Financial Intelligence Platform"
	@echo ""
	@echo "Available targets:"
	@echo "  make install        Install production dependencies"
	@echo "  make install-dev    Install development dependencies (includes prod)"
	@echo "  make test           Run pytest with coverage report"
	@echo "  make lint           Run Ruff linter"
	@echo "  make format         Format code with Black and auto-fix Ruff issues"
	@echo "  make clean          Remove Python caches, build artifacts, and coverage files"
	@echo "  make run-dashboard  Launch the Streamlit dashboard"
	@echo "  make run-api        Launch the FastAPI server with Uvicorn"
	@echo "  make load           Run ETL pipeline (idempotent)"
	@echo "  make load-reset     Fresh ETL run: truncate tables then load"
	@echo "  make dq-review      Run DQ manual review report (5 random companies)"
	@echo ""

# ---- Dependency Installation ----

install:
	pip install --upgrade pip
	pip install -r requirements.txt

install-dev:
	pip install --upgrade pip
	pip install -r requirements-dev.txt
	pre-commit install

# ---- Testing ----

test:
	pytest tests/ -v --cov=src --cov-report=term-missing --cov-report=html

# ---- Linting & Formatting ----

lint:
	ruff check src/ tests/

format:
	black src/ tests/
	ruff check --fix src/ tests/

# ---- Cleanup ----

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info .coverage htmlcov/ .tox/ 2>/dev/null || true
	@echo "Clean complete."

# ---- Run Services ----

run-dashboard:
	streamlit run src/dashboard/app.py --server.port 8501 --server.address 0.0.0.0

run-api:
	uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# ---- ETL ----

load:          ## Run the ETL pipeline (idempotent — appends, deduplicates on PK)
	python -m scripts.run_etl

load-reset:    ## Truncate all tables then run the ETL pipeline (fresh load)
	python -m scripts.run_etl --reset

dq-review:     ## Run the Day-6 DQ manual review (5 random companies deep-dive)
	python -m scripts.dq_review
