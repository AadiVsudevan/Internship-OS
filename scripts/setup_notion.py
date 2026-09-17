"""
scripts/setup_notion.py
========================
Run ONCE during initial setup to create the 'Opportunities' database with the
exact schema this pipeline expects, under a parent Notion page you choose.

Usage:
    python scripts/setup_notion.py <PARENT_PAGE_ID>

The PARENT_PAGE_ID is the 32-character hex string at the end of any Notion
page URL. The integration must have access to that page (Settings → Connections).

Prints the new database ID — paste it into:
  - Your local .env as NOTION_OPPORTUNITIES_DB_ID
  - GitHub repo Settings → Secrets and variables → Actions

Why a separate setup script (not auto-created on first run):
  - Notion database creation is idempotent if you run this exactly once.
  - Running it twice creates two databases. A one-time explicit script is safer
    than "create if not exists" logic in main.py.
  - The Status property's complex group structure makes it impractical to define
    inline; having it written out clearly here documents the intended workflow.
"""
import sys
import logging
from notion_client import Client
from src.utils import env
from src.logger import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------
# The Status property uses Notion's group structure (in-progress, complete)
# because Notion requires it for the native Status type.
# See: https://developers.notion.com/reference/property-object#status

STATUS_OPTIONS = ["To Apply", "Drafting", "Applied", "Interview", "Offer", "Rejected", "Expired"]

SCHEMA = {
    # Notion requires exactly one "title" property; it's always called "Name" in
    # the API even if you rename it in the UI.
    "Name": {"title": {}},

    "Org": {"rich_text": {}},

    "Type": {"select": {"options": [
        {"name": n, "color": "default"}
        for n in ["Internship", "Fellowship", "Research", "Competition",
                  "Summer Program", "Scholarship", "Grant", "Other"]
    ]}},

    "Geography": {"select": {"options": [
        {"name": n, "color": "default"}
        for n in ["India", "US", "UK", "EU", "Remote", "Other"]
    ]}},

    "Focus Tags": {"multi_select": {"options": [
        {"name": n, "color": "default"}
        for n in ["finance", "economics", "behavioral-economics", "wealthtech",
                  "private-markets", "research", "policy", "tech", "general"]
    ]}},

    "ROI Score": {"number": {"format": "number"}},
    "Rank Score": {"number": {"format": "number"}},

    # Status property: requires options + groups.
    # Groups tell Notion how to categorise the status options for its Kanban view.
    "Status": {"status": {
        "options": [{"name": n, "color": "default"} for n in STATUS_OPTIONS],
        "groups": [
            {
                "name": "To-do",
                "color": "gray",
                "option_ids": [],  # Notion fills these in after creation
            },
            {
                "name": "In progress",
                "color": "blue",
                "option_ids": [],
            },
            {
                "name": "Complete",
                "color": "green",
                "option_ids": [],
            },
        ],
    }},

    "Deadline": {"date": {}},
    "Source": {"rich_text": {}},
    "Source URL": {"url": {}},

    "Effort Estimate": {"select": {"options": [
        {"name": n, "color": "default"} for n in ["<1h", "1-3h", "3h+"]
    ]}},

    "Summary": {"rich_text": {}},
    "Auto-Added": {"checkbox": {}},
    "This Week's Queue": {"checkbox": {}},

    # Formula properties — Notion evaluates these live, bot never writes to them.
    "Days Left": {
        "formula": {
            "expression": 'dateBetween(prop("Deadline"), now(), "days")'
        }
    },
    "Urgent": {
        "formula": {
            "expression": 'if(prop("Days Left") <= 3, "🔥", if(prop("Days Left") <= 7, "⚠️", ""))'
        }
    },
}


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    parent_page_id = sys.argv[1].strip().replace("-", "")  # accept dashed or plain form
    token = env("NOTION_TOKEN")

    if not token:
        logger.critical(
            "NOTION_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
        sys.exit(1)

    logger.info("Creating 'Opportunities' database under page %s ...", parent_page_id)

    client = Client(auth=token)

    try:
        db = client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "Opportunities"}}],
            properties=SCHEMA,
        )
    except Exception as e:
        logger.critical("Failed to create database: %s", e)
        logger.info(
            "Common causes:\n"
            "  1. The parent page is not shared with your integration.\n"
            "     (Notion page → ••• → Connections → add your integration)\n"
            "  2. The page ID is wrong (should be 32 hex chars, no dashes).\n"
            "  3. NOTION_TOKEN is invalid."
        )
        sys.exit(1)

    db_id = db["id"]
    print()
    print("=" * 60)
    print(f"SUCCESS — database created: {db_id}")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Add to .env:  NOTION_OPPORTUNITIES_DB_ID=" + db_id)
    print("  2. Add to GitHub Secrets:  NOTION_OPPORTUNITIES_DB_ID=" + db_id)
    print("  3. Run:  python scripts/create_queue_page.py  (creates the Weekly Queue page)")
    print("  4. Build your Notion views manually — see README Section 5.")
    print()


if __name__ == "__main__":
    main()
