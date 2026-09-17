from __future__ import annotations
"""
src/utils.py
============
Shared helpers used across the pipeline.

Design principles:
- This file has ZERO imports from Notion / Groq / requests — it is the lowest
  layer of the dependency graph and must stay that way.
- Every other module can import from here without risk of circular imports.
- The `env()` function is kept as a thin wrapper for backward compatibility,
  but all new code should prefer `from src.settings import settings`.
"""
import os
import json
import re
import time
import logging
import functools
import yaml
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants (kept for backward compatibility; prefer settings.xxx)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SEEN_PATH = DATA_DIR / "seen.json"
CONFIG_PATH = ROOT / "config" / "sources.yaml"

# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------
# Tracking params that would otherwise make identical URLs look "new" to dedupe.
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "source", "mc_cid", "mc_eid",
}


def normalize_url(url: str) -> str:
    """Strip tracking params and trailing slashes so the same listing from two
    sources hashes identically.

    Examples:
        https://example.com/job?utm_source=linkedin  ->  https://example.com/job
        https://example.com/job/   ->  https://example.com/job
    """
    if not url:
        return url
    parsed = urlparse(url)
    clean_qs = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in TRACKING_PARAMS]
    clean = parsed._replace(query=urlencode(clean_qs), fragment="")
    s = urlunparse(clean)
    return s.rstrip("/").lower()


# ---------------------------------------------------------------------------
# Seen-state persistence (dedupe store)
# ---------------------------------------------------------------------------

def load_seen() -> dict:
    """Load the dedupe state file. Returns {} if it doesn't exist yet."""
    DATA_DIR.mkdir(exist_ok=True)
    if not SEEN_PATH.exists():
        return {}
    try:
        with open(SEEN_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load seen.json (%s) — starting fresh.", e)
        return {}


def save_seen(seen: dict):
    """Persist the dedupe state atomically (write to temp, then rename)."""
    DATA_DIR.mkdir(exist_ok=True)
    tmp = SEEN_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(seen, f, indent=2, sort_keys=True)
    tmp.replace(SEEN_PATH)


# ---------------------------------------------------------------------------
# Source config loader
# ---------------------------------------------------------------------------

def load_sources() -> dict:
    """Load config/sources.yaml. This is the user-editable file."""
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Keyword-tier rule-based scorer (fallback when LLM is unavailable)
# ---------------------------------------------------------------------------

# Extend this list over time — it's the main lever for tuning ROI scoring
# without touching code.
PRESTIGE_KEYWORDS = {
    "tier1": [  # +40 base points — globally recognised, highly selective
        "goldman sachs", "morgan stanley", "jpmorgan", "j.p. morgan", "mckinsey",
        "bcg", "bain & company", "rhodes scholarship", "fulbright", "y combinator",
        "nber", "rbi", "reserve bank of india", "world bank", "imf", "cfa institute",
        "sebi", "nse", "bse", "rotman", "wharton", "ashoka university",
        "harvard", "oxbridge", "lse", "isi kolkata", "iim ahmedabad",
    ],
    "tier2": [  # +20 base points — strong signal but broader category
        "fellowship", "research assistant", "accelerator", "incubator", "scholarship",
        "venture capital", "private equity", "hedge fund", "wealthtech", "fintech",
        "behavioral economics", "policy research", "quant", "summer analyst",
    ],
    "tier3": [  # +5 base points — legitimate but generic
        "internship", "summer program", "competition", "case study challenge",
        "hackathon", "grant",
    ],
}

FOCUS_TAGS = [
    "finance", "economics", "behavioral-economics", "wealthtech",
    "private-markets", "research", "policy", "india", "competition", "fellowship",
]


def rule_based_score(text: str) -> int:
    """Fallback ROI score (0-100) using keyword tiers.

    Used when USE_LLM_CLASSIFICATION=false or Groq is rate-limited/unreachable.
    Only the highest matching tier contributes (not additive across tiers) to
    avoid over-scoring a text that mentions multiple generic terms.
    """
    t = text.lower()
    for kw in PRESTIGE_KEYWORDS["tier1"]:
        if kw in t:
            return 40
    for kw in PRESTIGE_KEYWORDS["tier2"]:
        if kw in t:
            return 20
    for kw in PRESTIGE_KEYWORDS["tier3"]:
        if kw in t:
            return 5
    return 0


def extract_focus_tags(text: str) -> list[str]:
    """Extract focus tags from free text using simple substring matching."""
    t = text.lower()
    return [tag for tag in FOCUS_TAGS if tag.replace("-", " ") in t or tag in t]


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def with_retry(max_attempts: int = 3, base_delay: float = 2.0, exceptions=(Exception,)):
    """Decorator: retry a function up to `max_attempts` times with exponential
    back-off. Only retries on the given exception types.

    Usage:
        @with_retry(max_attempts=3, base_delay=1.0, exceptions=(requests.Timeout,))
        def call_api():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__, max_attempts, e,
                        )
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "%s attempt %d/%d failed (%s) — retrying in %.1fs",
                        func.__name__, attempt, max_attempts, e, delay,
                    )
                    time.sleep(delay)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Backward-compat shim — prefer src.settings.settings
# ---------------------------------------------------------------------------

def env(key: str, default=None):
    """Read an environment variable. Prefer `from src.settings import settings`
    for new code."""
    return os.environ.get(key, default)
