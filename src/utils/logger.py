"""
Nifty 100 Financial Intelligence Platform - Logging Configuration.

Provides a reusable, production-ready logger built on `loguru`.
Features:
    - Console output with color and structured formatting.
    - Rotating file handler (default 10 MB rotation, 30-day retention).
    - Configurable log level via environment variable LOG_LEVEL.
    - Separate sink for errors-only log file.
    - Utility to intercept standard-library logging and route it to loguru.

Usage:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("ETL pipeline started")
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger as _logger

# ---------------------------------------------------------------------------
# Defaults (can be overridden via environment through src.utils.config)
# ---------------------------------------------------------------------------
DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_LOG_DIR: str | Path = "logs"
DEFAULT_LOG_FILE: str = "nifty100.log"
DEFAULT_ERROR_LOG_FILE: str = "errors.log"
DEFAULT_ROTATION: str = "10 MB"
DEFAULT_RETENTION: str = "30 days"
DEFAULT_FORMAT: str = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# Keep track of whether the logger has already been configured
# so we don't add duplicate handlers on repeated imports.
_CONFIGURED: bool = False


class InterceptHandler(logging.Handler):
    """
    Intercept standard-library logging messages and forward to loguru.

    This allows third-party libraries that use the `logging` module
    (e.g., uvicorn, sqlalchemy) to share the same log sink as our
    application code.
    """

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial pass-through
        try:
            level: str | int = _logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__ and frame.f_back is not None:
            frame = frame.f_back
            depth += 1

        _logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _resolve_log_dir(log_dir: str | Path | None = None) -> Path:
    """Create (if needed) and return the absolute log directory path."""
    if log_dir is None:
        try:
            # Lazy import to avoid circular dependency during initial setup
            from src.utils.config import settings

            log_dir = settings.LOGS_DIR
        except Exception:
            log_dir = DEFAULT_LOG_DIR

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    return log_path


def setup_logging(
    level: str | None = None,
    log_dir: str | Path | None = None,
    log_file: str = DEFAULT_LOG_FILE,
    error_log_file: str = DEFAULT_ERROR_LOG_FILE,
    rotation: str = DEFAULT_ROTATION,
    retention: str = DEFAULT_RETENTION,
    log_format: str = DEFAULT_FORMAT,
    intercept_stdlib: bool = True,
) -> None:
    """
    Configure loguru sinks (console + rotating files).

    Safe to call multiple times; will reset existing handlers first.

    Args:
        level: Minimum log level (e.g., "DEBUG", "INFO", "WARNING").
        log_dir: Directory where log files are written.
        log_file: Filename for combined log.
        error_log_file: Filename for error-only log.
        rotation: Rotation size/time (e.g., "10 MB", "00:00").
        retention: Retention policy (e.g., "30 days", "1 week").
        log_format: Loguru message format string.
        intercept_stdlib: If True, redirect stdlib logging to loguru.
    """
    global _CONFIGURED

    # Attempt to read level from environment if not explicitly passed
    if level is None:
        try:
            from src.utils.config import settings

            level = settings.LOG_LEVEL
        except Exception:
            level = DEFAULT_LOG_LEVEL
    level = level.upper()

    # Reset previously added sinks (keep loguru's default? No: we remove all.)
    _logger.remove()

    # Console sink (stdout) for human-friendly colored output
    _logger.add(
        sys.stdout,
        level=level,
        format=log_format,
        colorize=True,
        backtrace=True,
        diagnose=False,  # Do not leak variables in production
        enqueue=False,
    )

    # Resolve log directory and create file sinks
    log_path = _resolve_log_dir(log_dir)

    # Combined rotating log file
    _logger.add(
        log_path / log_file,
        level=level,
        format=log_format,
        rotation=rotation,
        retention=retention,
        compression="zip",
        backtrace=True,
        diagnose=False,
        enqueue=True,
        encoding="utf-8",
    )

    # Error-only log file (for alerts / monitoring)
    _logger.add(
        log_path / error_log_file,
        level="ERROR",
        format=log_format,
        rotation=rotation,
        retention=retention,
        compression="zip",
        backtrace=True,
        diagnose=False,
        enqueue=True,
        encoding="utf-8",
    )

    # Intercept standard library logging so all logs go through loguru
    if intercept_stdlib:
        logging.root.handlers = [InterceptHandler()]
        logging.root.setLevel(level)
        # Override levels for noisy third-party libraries
        for logger_name in ("uvicorn", "uvicorn.access", "fastapi"):
            logging.getLogger(logger_name).handlers = []
            logging.getLogger(logger_name).propagate = True

    _CONFIGURED = True
    _logger.debug(
        "Logging configured (level={}, log_dir={})",
        level,
        log_path,
    )


def get_logger(name: str | None = None):
    """
    Return a bound loguru logger instance.

    If logging has not yet been explicitly configured, this function will
    initialize it with defaults (reading from environment if available).

    Args:
        name: Optional logger name (usually __name__ of the caller).

    Returns:
        A loguru logger bound to the given name.
    """
    if not _CONFIGURED:
        setup_logging()

    if name:
        return _logger.bind(name=name)
    return _logger


# Auto-configure on import so consumers can simply do:
#   from src.utils.logger import logger
# and have a ready-to-use logger.
setup_logging()
logger = _logger
