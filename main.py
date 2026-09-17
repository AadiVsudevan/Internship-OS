"""
main.py
-------
Entry point for the DAILY discovery run (triggered by .github/workflows/discover.yml).

    python main.py

Flow:
  1. Ingest: gather raw candidates from all enabled sources (RSS / scrape / GitHub lists).
  2. Dedupe: filter out anything already in data/seen.json (exact URL + fuzzy title).
  3. Safety-net: cross-check survivors against live Notion DB (protects against a reset seen.json).
  4. Classify: call Groq LLM for structured JSON (type, ROI, effort, deadline, summary).
              Automatically falls back to rule-based scorer if Groq is down/unset.
  5. Rank: compute a transparent weighted score.
  6. Push: create a Notion page for each new opportunity.

Design principle: fail loudly PER SOURCE, never abort the whole run.
A broken scraper or a rate-limited Groq call should not prevent the other
20 sources from working.
"""
import time
import logging

# Configure logging first — before any other module emits a log line.
from src.logger import configure_logging
configure_logging()

from src.settings import settings
from src.utils import load_sources
from src.ingest import rss, scrape, github_lists
from src.dedupe import filter_new
from src.classify import classify
from src.rank import score
from src.notion_sync import get_existing_urls, create_opportunity

logger = logging.getLogger(__name__)

# Pause between Notion page creates — keeps us well under their 3 req/s limit
# and Groq's 30 req/min free-tier cap (the classify call happens inside the loop).
_INTER_ITEM_DELAY = 1.2


def gather_raw_candidates() -> list[dict]:
    """Run all enabled ingestors and pool their raw candidates.

    Each source type is isolated in its own try/except so a single broken
    source never silences the others.
    """
    sources = load_sources()
    raw: list[dict] = []

    for src in sources.get("rss", []):
        if not src.get("enabled", True):
            continue
        try:
            found = rss.fetch(src)
            logger.info("[rss] %s: %d raw items", src["name"], len(found))
            raw.extend(found)
        except Exception as e:
            logger.error("[rss] ERROR in source '%s': %s", src["name"], e)

    for src in sources.get("scrape", []):
        if not src.get("enabled", True):
            continue
        try:
            found = scrape.fetch(src)
            logger.info("[scrape] %s: %d raw items", src["name"], len(found))
            raw.extend(found)
        except Exception as e:
            logger.error("[scrape] ERROR in source '%s': %s", src["name"], e)

    for src in sources.get("github_list", []):
        if not src.get("enabled", True):
            continue
        try:
            found = github_lists.fetch(src)
            logger.info("[github_list] %s: %d raw items", src["name"], len(found))
            raw.extend(found)
        except Exception as e:
            logger.error("[github_list] ERROR in source '%s': %s", src["name"], e)

    return raw


def run():
    settings.validate_for_discovery()

    logger.info("=== Discovery run starting ===")
    raw = gather_raw_candidates()
    logger.info("%d raw candidates across all sources", len(raw))

    new_candidates = filter_new(raw)
    logger.info("%d survive local dedupe (data/seen.json)", len(new_candidates))

    # Safety-net layer: cross-check against what's already live in Notion,
    # in case seen.json was reset/lost after a git repo reset or accidental delete.
    try:
        existing_urls = get_existing_urls(settings.notion_db_id)
        before = len(new_candidates)
        new_candidates = [c for c in new_candidates if c["url"] not in existing_urls]
        logger.info(
            "%d survive Notion safety-net check (filtered %d already-in-Notion)",
            len(new_candidates), before - len(new_candidates),
        )
    except Exception as e:
        logger.warning(
            "Could not query Notion for safety-net dedupe: %s. Proceeding anyway.", e
        )

    if len(new_candidates) > settings.max_new_per_run:
        logger.warning(
            "Capping at MAX_NEW_PER_RUN=%d (was %d — source may be misbehaving or "
            "this is the first run)",
            settings.max_new_per_run, len(new_candidates),
        )
        new_candidates = new_candidates[:settings.max_new_per_run]

    created = 0
    for candidate in new_candidates:
        try:
            classified = classify(candidate)
            rank_score = score(classified)
            create_opportunity(settings.notion_db_id, candidate, classified, rank_score)
            created += 1
            logger.info(
                "+ Added: %s (rank=%.1f, roi=%s, via=%s)",
                candidate["title"][:70],
                rank_score,
                classified.get("roi_score"),
                classified.get("_classified_by", "llm"),
            )
            time.sleep(_INTER_ITEM_DELAY)
        except Exception as e:
            logger.error(
                "ERROR processing candidate '%s': %s",
                candidate.get("title"), e,
            )

    logger.info("=== Done. %d new opportunities pushed to Notion. ===", created)


if __name__ == "__main__":
    run()
