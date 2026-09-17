"""Ingest candidates from RSS/Atom feeds, including Google Alerts delivered as RSS."""
import feedparser
from src.utils import normalize_url


def fetch(source: dict) -> list[dict]:
    """source = one entry from sources.yaml['rss']. Returns list of raw candidates."""
    candidates = []
    try:
        feed = feedparser.parse(source["url"])
    except Exception as e:
        print(f"[rss] FAILED to parse {source['name']}: {e}")
        return candidates

    if getattr(feed, "bozo", False) and not feed.entries:
        print(f"[rss] WARNING - feed may be broken or URL not yet configured: {source['name']}")
        return candidates

    for entry in feed.entries:
        url = entry.get("link", "")
        if not url:
            continue
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "") or entry.get("description", "")
        published = entry.get("published", "") or entry.get("updated", "")

        candidates.append({
            "title": title,
            "url": normalize_url(url),
            "raw_url": url,
            "raw_text": f"{title} {summary}",
            "published_hint": published,
            "source_name": source["name"],
            "source_type": "rss",
            "tags": source.get("tags", []),
        })
    return candidates
