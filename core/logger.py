"""Unified logging system for the KS automation project.

Provides rotating file logs and colored console output for all modules.
Usage:
    from core.logger import get_logger
    logger = get_logger("my_module")
    logger.info("Something happened")
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI color codes for console output
# ---------------------------------------------------------------------------

_COLORS: dict[int, str] = {
    logging.DEBUG: "\033[36m",      # cyan
    logging.INFO: "\033[32m",       # green
    logging.WARNING: "\033[33m",    # yellow
    logging.ERROR: "\033[31m",      # red
    logging.CRITICAL: "\033[1;31m", # bold red
}
_RESET = "\033[0m"

# Default log directory
DEFAULT_LOG_DIR = r"D:\ks_automation\logs"

# Cache of already-configured loggers to avoid duplicate handlers
_configured_loggers: set[str] = set()


class _ColoredFormatter(logging.Formatter):
    """Formatter that adds ANSI color codes based on log level."""

    def __init__(self, fmt: str, datefmt: str | None = None) -> None:
        super().__init__(fmt, datefmt)

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelno, "")
        message = super().format(record)
        if color:
            return f"{color}{message}{_RESET}"
        return message


def setup_logger(
    name: str,
    log_dir: str = DEFAULT_LOG_DIR,
    level: str = "INFO",
) -> logging.Logger:
    """Create and configure a logger with file rotation and colored console output.

    Args:
        name: Logger name, typically the module name.
        log_dir: Directory for log files. Created automatically if missing.
        level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if already configured
    if name in _configured_loggers:
        return logger

    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)

    log_fmt = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    # --- File handler: rotating, 10 MB, 5 backups, UTF-8 ---
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / f"{name}.log"

    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_fmt, datefmt=date_fmt))
    logger.addHandler(file_handler)

    # --- Console handler: colored output ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(_ColoredFormatter(log_fmt, datefmt=date_fmt))
    logger.addHandler(console_handler)

    # Prevent propagation to root logger to avoid duplicate messages
    logger.propagate = False

    _configured_loggers.add(name)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get an existing logger or create one with default settings.

    Args:
        name: Logger name, typically the module name.

    Returns:
        A configured logging.Logger instance.
    """
    if name in _configured_loggers:
        return logging.getLogger(name)
    return setup_logger(name)
