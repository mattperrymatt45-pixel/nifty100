"""
Nifty 100 Financial Intelligence Platform - Configuration.

Centralizes all environment-based configuration using Pydantic-style
access patterns on top of `python-dotenv`. Provides a single `settings`
object that can be imported anywhere in the codebase.

Usage:
    from src.utils.config import settings
    df = pd.read_csv(settings.RAW_DATA_DIR / "stocks.csv")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_project_root() -> Path:
    """
    Locate the project root by walking up the directory tree from this file
    until a known marker file (pyproject.toml) is found. Falls back to CWD.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def _resolve_path(base: Path, value: str | None, default: str) -> Path:
    """Resolve a path relative to the project root unless it is absolute."""
    raw = value if value is not None else default
    p = Path(raw)
    if p.is_absolute():
        return p
    return (base / p).resolve()


# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = _get_project_root()
load_dotenv(PROJECT_ROOT / ".env", override=False)


# ---------------------------------------------------------------------------
# Settings Dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded from environment variables."""

    # ---- Base Paths ----
    PROJECT_ROOT: Path = field(default_factory=lambda: PROJECT_ROOT)
    DATA_DIR: Path = field(init=False)
    RAW_DATA_DIR: Path = field(init=False)
    PROCESSED_DATA_DIR: Path = field(init=False)
    INTERIM_DATA_DIR: Path = field(init=False)
    OUTPUT_DIR: Path = field(init=False)
    REPORTS_DIR: Path = field(init=False)
    LOGS_DIR: Path = field(init=False)
    DB_DIR: Path = field(init=False)
    CONFIG_DIR: Path = field(init=False)

    # ---- Database ----
    DB_PATH: Path = field(init=False)
    DB_CONNECTION_STRING: str = field(init=False)

    # ---- Logging ----
    LOG_LEVEL: str = field(init=False)
    LOG_FILE: str = field(init=False)
    LOG_ROTATION: str = field(init=False)
    LOG_RETENTION: str = field(init=False)

    # ---- API ----
    API_HOST: str = field(init=False)
    API_PORT: int = field(init=False)

    # ---- Dashboard ----
    DASHBOARD_PORT: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "DATA_DIR",
            _resolve_path(PROJECT_ROOT, os.getenv("DATA_DIR"), "data"),
        )
        object.__setattr__(
            self,
            "RAW_DATA_DIR",
            _resolve_path(PROJECT_ROOT, os.getenv("RAW_DATA_DIR"), "data/raw"),
        )
        object.__setattr__(
            self,
            "PROCESSED_DATA_DIR",
            _resolve_path(PROJECT_ROOT, os.getenv("PROCESSED_DATA_DIR"), "data/processed"),
        )
        object.__setattr__(
            self,
            "INTERIM_DATA_DIR",
            _resolve_path(PROJECT_ROOT, os.getenv("INTERIM_DATA_DIR"), "data/interim"),
        )
        object.__setattr__(
            self,
            "OUTPUT_DIR",
            _resolve_path(PROJECT_ROOT, os.getenv("OUTPUT_DIR"), "output"),
        )
        object.__setattr__(
            self,
            "REPORTS_DIR",
            _resolve_path(PROJECT_ROOT, os.getenv("REPORTS_DIR"), "reports"),
        )
        object.__setattr__(
            self,
            "LOGS_DIR",
            _resolve_path(PROJECT_ROOT, os.getenv("LOGS_DIR"), "logs"),
        )
        object.__setattr__(
            self,
            "DB_DIR",
            _resolve_path(PROJECT_ROOT, os.getenv("DB_DIR"), "db"),
        )
        object.__setattr__(
            self,
            "CONFIG_DIR",
            _resolve_path(PROJECT_ROOT, None, "config"),
        )

        # ---- DB ----
        db_path_raw = os.getenv("DB_PATH", "db/nifty100.db")
        db_path_obj = Path(db_path_raw)
        if not db_path_obj.is_absolute():
            db_path_obj = (PROJECT_ROOT / db_path_obj).resolve()
        object.__setattr__(self, "DB_PATH", db_path_obj)

        default_conn_str = f"sqlite:///{db_path_obj.as_posix()}"
        object.__setattr__(
            self,
            "DB_CONNECTION_STRING",
            os.getenv("DB_CONNECTION_STRING", default_conn_str),
        )

        # ---- Logging ----
        object.__setattr__(self, "LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO").upper())
        object.__setattr__(self, "LOG_FILE", os.getenv("LOG_FILE", "nifty100.log"))
        object.__setattr__(self, "LOG_ROTATION", os.getenv("LOG_ROTATION", "10 MB"))
        object.__setattr__(self, "LOG_RETENTION", os.getenv("LOG_RETENTION", "30 days"))

        # ---- API ----
        object.__setattr__(self, "API_HOST", os.getenv("API_HOST", "0.0.0.0"))
        object.__setattr__(self, "API_PORT", int(os.getenv("API_PORT", "8000")))

        # ---- Dashboard ----
        object.__setattr__(self, "DASHBOARD_PORT", int(os.getenv("DASHBOARD_PORT", "8501")))

    def ensure_directories(self) -> None:
        """Create all required data/log/output directories if they do not exist."""
        for directory in (
            self.DATA_DIR,
            self.RAW_DATA_DIR,
            self.PROCESSED_DATA_DIR,
            self.INTERIM_DATA_DIR,
            self.OUTPUT_DIR,
            self.REPORTS_DIR,
            self.LOGS_DIR,
            self.DB_DIR,
            self.CONFIG_DIR,
        ):
            directory.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Singleton Instance
# ---------------------------------------------------------------------------
settings: Settings = Settings()
settings.ensure_directories()
