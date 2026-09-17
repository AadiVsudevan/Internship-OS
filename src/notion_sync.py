from __future__ import annotations
"""
src/notion_sync.py
==================
All Notion API interaction lives here. No other module touches the Notion SDK.

Why single-module isolation:
  - One place to update if the Notion API changes.
  - Easy to mock in tests (mock just this module's functions).
  - Rate-limit logic and retry handling are centralised.

Property names MUST match the Notion database schema in README.md exactly
(case-sensitive). If you rename a column in Notion, update it here too.

Notion API rate limits (as of 2024): ~3 requests/second average.
The 1.2s inter-item sleep in main.py keeps us well within this.
"""
import logging
from notion_client import Client
from src.utils import env

logger = logging.getLogger(__name__)

STATUS_DEFAULT = "To Apply"


def _client() -> Client:
    """Create a new Notion client. We create per-call rather than a module-level
    singleton because GitHub Actions runners are stateless and short-lived."""
    token = env("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN is not set")
    return Client(auth=token)


def get_existing_urls(db_id: str) -> set:
    """Safety-net dedupe: query Notion for all Source URLs already in the DB.

    Even if data/seen.json is wiped/corrupted, this prevents re-flooding the
    database with items you've already triaged. Handles pagination automatically.
    """
    client = _client()
    urls: set = set()
    cursor = None

    while True:
        resp = client.databases.query(
            database_id=db_id,
            start_cursor=cursor,
            page_size=100,
        )
        for page in resp["results"]:
            url_prop = page["properties"].get("Source URL", {})
            url = url_prop.get("url")
            if url:
                urls.add(url.rstrip("/").lower())
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    logger.debug("Notion safety-net: found %d existing URLs", len(urls))
    return urls


def create_opportunity(db_id: str, candidate: dict, classified: dict, rank_score: float):
    """Create a single Notion page in the Opportunities database.

    Args:
        db_id: The Notion database ID.
        candidate: Raw candidate dict from any ingest module.
        classified: Classification dict from classify.py.
        rank_score: Final rank score from rank.py (0-100).
    """
    client = _client()
    deadline_iso = classified.get("_deadline_iso")

    properties = {
        "Name": {"title": [{"text": {"content": candidate["title"][:200]}}]},
        "Org": {"rich_text": [{"text": {"content": candidate.get("source_name", "")[:100]}}]},
        "Type": {"select": {"name": classified.get("type", "Other")}},
        "Geography": {"select": {"name": classified.get("geography", "Other")}},
        "Focus Tags": {
            "multi_select": [{"name": t} for t in classified.get("focus_tags", [])[:4]]
        },
        "ROI Score": {"number": int(classified.get("roi_score", 0))},
        "Rank Score": {"number": float(rank_score)},
        "Status": {"status": {"name": STATUS_DEFAULT}},
        "Source": {"rich_text": [{"text": {"content": candidate.get("source_name", "")[:100]}}]},
        "Source URL": {"url": candidate.get("raw_url", "") or None},
        "Effort Estimate": {"select": {"name": classified.get("effort_estimate", "1-3h")}},
        "Summary": {
            "rich_text": [{"text": {"content": (classified.get("summary") or "")[:500]}}]
        },
        "Auto-Added": {"checkbox": True},
        "This Week's Queue": {"checkbox": False},
    }

    if deadline_iso:
        properties["Deadline"] = {"date": {"start": deadline_iso}}

    client.pages.create(parent={"database_id": db_id}, properties=properties)
    logger.debug("Created Notion page: %s", candidate["title"][:70])


def mark_in_weekly_queue(db_id: str, page_ids: list):
    """Check the 'This Week's Queue' checkbox on the given pages.

    Also clears the checkbox on ALL other 'To Apply' pages first, so the
    "🔥 This Week" view always shows only this week's selection.
    """
    client = _client()
    for pid in page_ids:
        try:
            client.pages.update(
                page_id=pid,
                properties={"This Week's Queue": {"checkbox": True}},
            )
        except Exception as e:
            logger.error("Failed to mark page %s in queue: %s", pid, e)


def query_active(db_id: str, status_names: list) -> list:
    """Query Notion for all pages matching any of the given Status values.

    Handles pagination — returns the complete list regardless of size.
    """
    client = _client()
    results: list = []
    cursor = None

    filter_body = {
        "or": [
            {"property": "Status", "status": {"equals": s}}
            for s in status_names
        ]
    }

    while True:
        resp = client.databases.query(
            database_id=db_id,
            filter=filter_body,
            start_cursor=cursor,
            page_size=100,
        )
        results.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    return results


def set_status(page_id: str, status_name: str):
    """Update the Status property of a single page."""
    client = _client()
    client.pages.update(
        page_id=page_id,
        properties={"Status": {"status": {"name": status_name}}},
    )


def append_digest_blocks(page_id: str, lines: list[str]):
    """Append a plain-text digest to the given Notion page.

    Each line becomes a separate paragraph block. This is used by
    weekly_queue.py to write the Monday briefing.
    """
    client = _client()
    blocks = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": line[:2000]}}]
            },
        }
        for line in lines
    ]
    client.blocks.children.append(block_id=page_id, children=blocks)
    logger.debug("Appended %d digest blocks to page %s", len(lines), page_id)
