"""
Smoke tests for Sprint 1 - Day 1 environment setup.

These tests validate that:
    - The project structure is in place.
    - Core dependencies import successfully.
    - Configuration loads correctly from environment.
    - Logger is properly configured.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Project Structure
# ---------------------------------------------------------------------------
EXPECTED_DIRECTORIES = [
    "data",
    "data/raw",
    "data/processed",
    "data/interim",
    "db",
    "output",
    "reports",
    "notebooks",
    "logs",
    "config",
    "src",
    "src/etl",
    "src/analytics",
    "src/dashboard",
    "src/api",
    "src/utils",
    "tests",
    "tests/etl",
    "scripts",
]

EXPECTED_FILES = [
    "requirements.txt",
    "requirements-dev.txt",
    ".env.example",
    ".gitignore",
    "README.md",
    "Makefile",
    "pyproject.toml",
    ".pre-commit-config.yaml",
    "src/__init__.py",
    "src/utils/__init__.py",
    "src/utils/logger.py",
    "src/utils/config.py",
    "tests/__init__.py",
]


@pytest.mark.parametrize("relative_dir", EXPECTED_DIRECTORIES)
def test_directories_exist(relative_dir: str) -> None:
    assert (PROJECT_ROOT / relative_dir).is_dir(), f"Missing directory: {relative_dir}"


@pytest.mark.parametrize("relative_file", EXPECTED_FILES)
def test_files_exist(relative_file: str) -> None:
    assert (PROJECT_ROOT / relative_file).is_file(), f"Missing file: {relative_file}"


# ---------------------------------------------------------------------------
# Core Dependency Imports
# ---------------------------------------------------------------------------
CORE_MODULES = [
    "pandas",
    "numpy",
    "openpyxl",
    "sqlalchemy",
    "dotenv",
    "requests",
    "matplotlib",
    "plotly",
    "streamlit",
    "fastapi",
    "uvicorn",
    "sklearn",
    "scipy",
    "nltk",
    "pytest",
    "tqdm",
    "loguru",
    "black",
    "ruff",
]


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_dependencies_importable(module_name: str) -> None:
    """Verify every declared core dependency can be imported."""
    importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# Configuration & Logging
# ---------------------------------------------------------------------------
def test_settings_loads() -> None:
    from src.utils.config import settings

    assert settings.PROJECT_ROOT.exists()
    assert settings.DATA_DIR.is_dir()
    assert settings.RAW_DATA_DIR.is_dir()
    assert settings.PROCESSED_DATA_DIR.is_dir()
    assert settings.INTERIM_DATA_DIR.is_dir()
    assert settings.LOGS_DIR.is_dir()
    assert settings.DB_DIR.is_dir()
    assert settings.OUTPUT_DIR.is_dir()
    assert settings.LOG_LEVEL in {
        "TRACE",
        "DEBUG",
        "INFO",
        "SUCCESS",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }
    assert settings.API_PORT > 0
    assert settings.DASHBOARD_PORT > 0
    assert settings.DB_PATH is not None
    assert "sqlite" in settings.DB_CONNECTION_STRING


def test_logger_works() -> None:
    from src.utils.logger import _CONFIGURED, get_logger

    assert _CONFIGURED is True
    log = get_logger("test")
    assert log is not None
    # Emit a test log entry (should not raise)
    log.debug("Smoke test: debug message from test_environment.py")
    log.info("Smoke test: info message from test_environment.py")
