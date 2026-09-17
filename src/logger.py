from __future__ import annotations
"""
src/logger.py
=============
Shared logging configuration for the entire pipeline.

Why a dedicated module (not basicConfig in each file):
- Centralised format: every module's log line looks identical.
- Timestamped at the record level so GitHub Actions logs are easy to grep.
- Respects a LOG_LEVEL env var so CI can set DEBUG without code changes.
- Called once in main.py / each entrypoint; all subsequent `logging.getLogger`
  calls anywhere in the codebase automatically inherit this config.

Usage:
    # In any entrypoint (main.py, src/archive.py, etc.) — call ONCE at top:
    from src.logger import configure_logging
    configure_logging()

    # In any module — standard Python logging:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("doing thing")
"""
import logging
import os
import sys


def configure_logging(level: str | None = None) -> None:
    """Set up root logger with a clean, structured format.

    Args:
        level: Override log level (e.g. "DEBUG"). Falls back to LOG_LEVEL env
               var, then INFO.
    """
    effective_level = (
        level
        or os.environ.get("LOG_LEVEL", "INFO")
    ).upper()

    numeric = getattr(logging, effective_level, logging.INFO)

    # Single handler: stdout. GitHub Actions captures this automatically.
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(numeric)
    # Remove any handlers already attached (e.g., pytest's caplog handler) to
    # avoid duplicate lines.
    root.handlers.clear()
    root.addHandler(handler)

    # Quiet down noisy third-party libraries that flood at DEBUG level.
    for noisy in ("urllib3", "httpx", "httpcore", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
