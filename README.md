# Nifty 100 Financial Intelligence Platform

A production-grade data platform for ingesting, validating, analyzing, and visualizing financial data from the Nifty 100 index. The platform follows a modular, scalable architecture supporting ETL pipelines, analytics, interactive dashboards, and REST APIs.

---

## Project Overview

The **Nifty 100 Financial Intelligence Platform** is a Python-based data engineering project designed to:

- **Ingest** 12 distinct financial datasets covering equities, fundamentals, sectors, and macro indicators.
- **Validate** incoming data for quality, consistency, and schema conformance.
- **Load** cleansed data into a SQLite relational database with a robust schema.
- **Analyze** data using statistical and machine-learning techniques.
- **Visualize** insights through interactive Plotly charts and a Streamlit dashboard.
- **Expose** data and analytics via a FastAPI REST API.

The codebase is structured following modern Python best practices: type hints, modular packages, logging, configuration via environment variables, automated linting/formatting, and a full test suite.

---

## Folder Structure

```
nifty100-platform/
│
├── data/
│   ├── raw/            # Original, immutable source datasets
│   ├── processed/      # Cleaned, transformed datasets ready for loading
│   └── interim/        # Intermediate transformation artifacts
│
├── db/                 # SQLite database files and schema definitions
├── output/             # Generated charts, exports, and analysis outputs
├── reports/            # Generated HTML/PDF reports and notebooks exports
├── notebooks/          # Jupyter/Lab notebooks for exploration and prototyping
├── logs/               # Application log files (rotated automatically)
├── config/             # Additional static configuration (YAML/JSON)
│
├── src/                # Main application source code
│   ├── __init__.py
│   ├── etl/            # Extract, Transform, Load pipelines
│   ├── analytics/      # Statistical analysis and ML modules
│   ├── dashboard/      # Streamlit dashboard code
│   ├── api/            # FastAPI REST API endpoints
│   └── utils/          # Shared utilities (logging, config, helpers)
│
├── tests/              # Pytest test suite
│   ├── __init__.py
│   └── etl/            # Tests for ETL modules
│
├── scripts/            # Standalone utility scripts
│
├── requirements.txt    # Core production dependencies
├── requirements-dev.txt# Development dependencies (includes prod)
├── .env.example        # Example environment variable template
├── .gitignore          # Git ignore rules
├── .pre-commit-config.yaml  # Pre-commit hooks configuration
├── pyproject.toml      # Project metadata and tool config (Black, Ruff, Pytest)
├── Makefile            # Common developer commands
└── README.md           # This file
```

---

## Installation

### Prerequisites

- **Python 3.12** or higher
- **pip** (latest version recommended)
- **git**

### Virtual Environment Setup

Create and activate a Python virtual environment before installing dependencies:

```bash
# Create virtual environment
python3.12 -m venv .venv

# Activate on Linux / macOS
source .venv/bin/activate

# Activate on Windows (PowerShell)
# .venv\Scripts\Activate.ps1
```

### Installing Dependencies

For production/runtime use:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

For development (includes testing, linting, formatting, and notebooks):

```bash
pip install --upgrade pip
pip install -r requirements-dev.txt
pre-commit install
```

### Environment Configuration

Copy the example environment file and adjust values for your system:

```bash
cp .env.example .env
```

Edit `.env` to point paths, logging levels, and ports as needed.

---

## Running Tests

Run the full test suite with coverage:

```bash
make test
```

Or directly with pytest:

```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## Common Commands (via Make)

| Command            | Description                                |
|--------------------|--------------------------------------------|
| `make install`     | Install production dependencies            |
| `make install-dev` | Install development dependencies           |
| `make test`        | Run tests with coverage report             |
| `make lint`        | Run Ruff linter on the source tree         |
| `make format`      | Format code with Black (and fix Ruff)      |
| `make clean`       | Remove caches, build artifacts, and .pyc   |
| `make run-dashboard` | Launch the Streamlit dashboard          |
| `make run-api`     | Launch the FastAPI server with Uvicorn      |

---

## Project Workflow

The platform is developed in sprints. Each sprint builds on the previous one:

1. **Sprint 1 - Environment Setup (Day 1):** Project scaffolding, dependencies, tooling, logging, and configuration.
2. **Sprint 1 - ETL Foundation (Day 2):** Data loaders, validators, SQLite schema, and loaders.
3. **Sprint 2 - Analytics:** Exploratory analysis, metrics, and feature engineering.
4. **Sprint 3 - Dashboard:** Streamlit interactive visualizations.
5. **Sprint 4 - API:** FastAPI endpoints for programmatic access.
6. **Sprint 5 - ML & Reporting:** Predictive models, NLP for news, and report generation.

---

## Future Sprint Overview

| Sprint | Focus Area                          | Key Deliverables                                       |
|--------|-------------------------------------|--------------------------------------------------------|
| 1      | ETL & Database                      | 12-dataset ingestion, validation, SQLite warehouse    |
| 2      | Analytics Engine                    | Sector analysis, returns, risk metrics, correlations   |
| 3      | Interactive Dashboard               | Streamlit UI with Plotly charts, filters, drill-downs  |
| 4      | REST API                            | FastAPI endpoints, auto-docs, pagination, filtering    |
| 5      | ML & NLP Insights                   | Price prediction, sentiment analysis, PDF reports      |

---

## Code Quality Standards

- **Black** for deterministic code formatting (line length 100).
- **Ruff** for fast linting, import sorting, and auto-fixes.
- **Pytest** for unit and integration tests with coverage gates.
- **Loguru** for structured, rotating logs.
- **python-dotenv** for environment-based configuration.
- **Pre-commit hooks** enforce formatting and linting before every commit.

---

## License

Internal project - All rights reserved.
