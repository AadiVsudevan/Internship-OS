"""Best-effort deadline extraction. Used as a fallback when the LLM classifier
is unavailable, and as a sanity-check against whatever the LLM extracted."""
from __future__ import annotations
import re
from datetime import datetime
from typing import Optional
from dateparser.search import search_dates

DEADLINE_KEYWORDS = re.compile(
    r"(apply by|deadline|due date|last date(?: to apply)?|closes? on|applications close)",
    re.IGNORECASE,
)


def extract_deadline(text: Optional[str]) -> Optional[str]:
    """Returns an ISO date string (YYYY-MM-DD) or None if nothing found."""
    if not text:
        return None
    t = text.lower()

    if "rolling" in t:
        return None  # no fixed deadline -- flag as rolling in classify.py instead

    match = DEADLINE_KEYWORDS.search(text)
    if match:
        # Search a window right after the keyword -- search_dates is robust to
        # trailing junk ("...March 15, 2027 for this fellowship") in a way a
        # hand-rolled regex capture group is not.
        window = text[match.end():match.end() + 60].lstrip(" :-\u2013\u2014\t")
        found = search_dates(window, languages=["en"],
                              settings={"PREFER_DATES_FROM": "future", "STRICT_PARSING": False})
        if found:
            parsed_date = found[0][1].date()
            if parsed_date >= datetime.now().date():
                return parsed_date.isoformat()

    # Last resort: scan the whole blob for any date-shaped substring
    found = search_dates(text, languages=["en"],
                          settings={"PREFER_DATES_FROM": "future", "STRICT_PARSING": False})
    if found:
        parsed_date = found[0][1].date()
        if parsed_date >= datetime.now().date():
            return parsed_date.isoformat()

    return None


def days_until(iso_date: Optional[str]) -> Optional[int]:
    if not iso_date:
        return None
    try:
        target = datetime.fromisoformat(iso_date).date()
        return (target - datetime.now().date()).days
    except Exception:
        return None
