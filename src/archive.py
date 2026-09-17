"""
src/archive.py
==============
Entry point for the daily ARCHIVE run (.github/workflows/archive.yml).

Run as: python -m src.archive

What it does:
  Scans the Notion Opportunities database for pages in "active" statuses
  (To Apply / Drafting / Applied / Interview) whose Deadline date has passed.
  Marks them "Expired" so your active pipeline view stays clean without
  manual triaging of dead listings.

Why this is separate from main.py:
  Runs at a different time (07:30 IST vs 06:00 IST) and touches a completely
  different slice of the database. Keeping it separate makes each job's logs
  easy to read and lets you disable archiving without touching discovery.
"""
import logging
from datetime import datetime

from src.logger import configure_logging
configure_logging()

from src.settings import settings
from src.notion_sync import query_active, set_status

logger = logging.getLogger(__name__)

# Statuses that might have a deadline and should be checked for expiry.
# "Offer" / "Rejected" are already terminal — no need to touch them.
ACTIVE_STATUSES = ["To Apply", "Drafting", "Applied", "Interview"]


def run():
    settings.validate_for_discovery()  # needs NOTION_TOKEN + NOTION_OPPORTUNITIES_DB_ID
    logger.info("=== Archive run starting ===")

    pages = query_active(settings.notion_db_id, ACTIVE_STATUSES)
    logger.info("Found %d active pages to check", len(pages))
    today = datetime.now().date()

    archived = 0
    for p in pages:
        deadline_prop = p["properties"].get("Deadline", {}).get("date")
        if not deadline_prop:
            continue  # no deadline set — can't expire it
        try:
            deadline = datetime.fromisoformat(deadline_prop["start"]).date()
        except (ValueError, KeyError) as e:
            logger.warning("Could not parse deadline for page %s: %s", p["id"], e)
            continue

        if deadline < today:
            try:
                set_status(p["id"], "Expired")
                archived += 1
                logger.info("Expired: %s", p["id"])
            except Exception as e:
                logger.error("Failed to expire page %s: %s", p["id"], e)

    logger.info("=== Done. %d opportunities marked Expired. ===", archived)


if __name__ == "__main__":
    run()
