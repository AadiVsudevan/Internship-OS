from __future__ import annotations
"""
src/settings.py
===============
Centralised, validated configuration loader for the whole pipeline.

Design decisions:
- All env-var reads go through here (not scattered across modules). This makes
  it trivial to find every config knob in one place.
- Values are validated at import time so the pipeline fails early with a clear
  message rather than crashing halfway through a run with a KeyError.
- The `settings` singleton is imported by every module that needs config.

Usage:
    from src.settings import settings

    db_id = settings.notion_db_id
    if settings.use_llm:
        ...
"""
import os
import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _env(key: str, default: str | None = None, required: bool = False) -> str | None:
    """Read an env var; raise a clear error if it's required and missing."""
    val = os.environ.get(key, default)
    if required and not val:
        logger.critical(
            "FATAL: required environment variable %s is not set. "
            "See .env.example for setup instructions.",
            key,
        )
        sys.exit(1)
    return val


@dataclass(frozen=True)
class Settings:
    """Immutable settings object populated from environment variables.

    Frozen so it can't be accidentally mutated mid-run (a subtle bug source
    in long-running or multi-threaded code).
    """
    # ── Notion ──────────────────────────────────────────────────────────────
    notion_token: str = field(default_factory=lambda: _env("NOTION_TOKEN", required=False))
    notion_db_id: str = field(default_factory=lambda: _env("NOTION_OPPORTUNITIES_DB_ID", required=False))
    notion_queue_page_id: str = field(default_factory=lambda: _env("NOTION_QUEUE_PAGE_ID", required=False))

    # ── Groq LLM ────────────────────────────────────────────────────────────
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    groq_model: str = field(default_factory=lambda: _env("GROQ_MODEL", "llama-3.1-8b-instant"))

    # ── Behaviour flags ──────────────────────────────────────────────────────
    use_llm: bool = field(default_factory=lambda: _env("USE_LLM_CLASSIFICATION", "true").lower() == "true")
    max_new_per_run: int = field(default_factory=lambda: int(_env("MAX_NEW_PER_RUN", "40")))
    weekly_queue_target_hours: float = field(
        default_factory=lambda: float(_env("WEEKLY_QUEUE_TARGET_HOURS", "3"))
    )

    # ── Paths ────────────────────────────────────────────────────────────────
    # These are derived from the repo root, not env vars.
    root_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def config_dir(self) -> Path:
        return self.root_dir / "config"

    @property
    def seen_path(self) -> Path:
        return self.data_dir / "seen.json"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "github_snapshots"

    @property
    def sources_path(self) -> Path:
        return self.config_dir / "sources.yaml"

    def validate_for_discovery(self):
        """Called at the start of main.py. Hard-fails if Notion is not configured."""
        if not self.notion_token:
            logger.critical("FATAL: NOTION_TOKEN is not set.")
            sys.exit(1)
        if not self.notion_db_id:
            logger.critical("FATAL: NOTION_OPPORTUNITIES_DB_ID is not set.")
            sys.exit(1)

    def validate_for_weekly_queue(self):
        self.validate_for_discovery()
        if not self.notion_queue_page_id:
            logger.critical("FATAL: NOTION_QUEUE_PAGE_ID is not set.")
            sys.exit(1)


# Module-level singleton — import this everywhere.
settings = Settings()
