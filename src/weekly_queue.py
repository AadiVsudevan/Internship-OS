from __future__ import annotations
"""
src/weekly_queue.py
===================
Entry point for the WEEKLY queue run (.github/workflows/weekly_queue.yml).

Run as: python -m src.weekly_queue

What it does (every Monday morning):
  1. Queries Notion for all "To Apply" pages.
  2. Sorts by Rank Score (descending).
  3. Greedily selects items until the weekly time budget (WEEKLY_QUEUE_TARGET_HOURS) is full.
  4. Marks selected pages with "This Week's Queue = ✓" in Notion — this drives
     the "🔥 This Week" filtered view.
  5. Appends a plain-text digest block to the NOTION_QUEUE_PAGE_ID page — your
     Monday morning briefing.

Why a separate time-budget selection instead of "top N":
  An N-fixed list ignores effort variance. A <1h quick-apply and a 3h+ essay are
  not equivalent. The time-budget greedy approach lets you consume a realistic
  slice of your week without over-committing.
"""
import logging
from src.logger import configure_logging
configure_logging()

from src.settings import settings
from src.notion_sync import query_active, mark_in_weekly_queue, append_digest_blocks

logger = logging.getLogger(__name__)

# Maps effort-estimate labels to approximate hours.
EFFORT_HOURS = {"<1h": 0.5, "1-3h": 2, "3h+": 4}


def _get_prop(page: dict, name: str, kind: str):
    """Safely extract a typed property value from a Notion page object."""
    prop = page["properties"].get(name, {})
    if kind == "number":
        return prop.get("number") or 0
    if kind == "select":
        sel = prop.get("select")
        return sel["name"] if sel else None
    if kind == "title":
        items = prop.get("title", [])
        return items[0]["plain_text"] if items else ""
    if kind == "date":
        d = prop.get("date")
        return d["start"] if d else None
    if kind == "url":
        return prop.get("url")
    return None


def _build_digest_lines(selected: list[dict], hours_used: float, total_waiting: int) -> list[str]:
    """Format the Monday morning digest as plain text Notion blocks."""
    lines = [
        f"=== Weekly Queue — {len(selected)} items, ~{hours_used:.1f}h budgeted ==="
    ]
    for i, s in enumerate(selected, 1):
        deadline_str = s["deadline"] or "no fixed deadline"
        lines.append(
            f"{i}. [{s['rank']:.0f}pts] {s['title']}"
            f" | due {deadline_str}"
            f" | ~{s['effort']}"
            f" | {s['url'] or 'no URL'}"
        )

    remaining = total_waiting - len(selected)
    if remaining > 0:
        lines.append("")
        lines.append(
            f"({remaining} more 'To Apply' items not queued — review in 'Active Pipeline' view)"
        )
    return lines


def run():
    settings.validate_for_weekly_queue()
    logger.info("=== Weekly queue run starting ===")

    pages = query_active(settings.notion_db_id, ["To Apply"])
    logger.info("%d items with Status='To Apply'", len(pages))

    # Enrich each page with the fields we need for selection.
    enriched = []
    for p in pages:
        enriched.append({
            "id": p["id"],
            "title": _get_prop(p, "Name", "title"),
            "rank": _get_prop(p, "Rank Score", "number"),
            "deadline": _get_prop(p, "Deadline", "date"),
            "effort": _get_prop(p, "Effort Estimate", "select") or "1-3h",
            "url": _get_prop(p, "Source URL", "url"),
        })

    # Sort by rank score descending — highest-value first.
    enriched.sort(key=lambda x: x["rank"], reverse=True)

    # Greedy time-budget selection: add items until budget exhausted.
    # The `not selected` guard ensures at least one item is always picked,
    # even if it exceeds the budget, so the queue is never empty.
    selected: list[dict] = []
    hours_used = 0.0
    for item in enriched:
        cost = EFFORT_HOURS.get(item["effort"], 2)
        if hours_used + cost <= settings.weekly_queue_target_hours or not selected:
            selected.append(item)
            hours_used += cost
        if hours_used >= settings.weekly_queue_target_hours:
            break

    logger.info("Selected %d items (~%.1fh) for this week's queue", len(selected), hours_used)

    # Mark selected items in Notion (drives the "🔥 This Week" view).
    if selected:
        try:
            mark_in_weekly_queue(settings.notion_db_id, [s["id"] for s in selected])
        except Exception as e:
            logger.error("Failed to mark items in Notion: %s", e)

    # Build and post the digest.
    lines = _build_digest_lines(selected, hours_used, len(enriched))
    for line in lines:
        logger.info(line)

    if settings.notion_queue_page_id:
        try:
            append_digest_blocks(settings.notion_queue_page_id, lines)
            logger.info("Digest written to Notion queue page.")
        except Exception as e:
            logger.error("Could not write digest to Notion page: %s", e)
    else:
        logger.warning("NOTION_QUEUE_PAGE_ID not set — digest only printed to log.")

    logger.info("=== Weekly queue run complete. ===")


if __name__ == "__main__":
    run()
