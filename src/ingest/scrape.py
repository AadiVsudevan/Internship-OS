"""Generic, config-driven scraper for listing pages that don't expose RSS.
Selectors live entirely in config/sources.yaml so a site redesign only needs
a YAML edit, not a code change. This is the one piece of the pipeline that
will occasionally need maintenance -- see README 'Maintenance Plan'."""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from src.utils import normalize_url

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OpportunityOS/1.0; personal research bot)"
}


def fetch(source: dict) -> list[dict]:
    candidates = []
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[scrape] FAILED to fetch {source['name']}: {e}")
        return candidates

    soup = BeautifulSoup(resp.text, "lxml")
    items = soup.select(source["list_selector"])
    if not items:
        print(f"[scrape] WARNING - 0 items matched for {source['name']}. "
              f"Selector likely stale -- check config/sources.yaml against the live page.")
        return candidates

    for item in items:
        title_el = item.select_one(source["title_selector"])
        link_el = item.select_one(source["link_selector"])
        if not title_el or not link_el:
            continue

        title = title_el.get_text(strip=True)
        href = link_el.get(source.get("link_attr", "href"), "")
        if not href:
            continue
        full_url = urljoin(source.get("base_url", source["url"]), href)

        candidates.append({
            "title": title,
            "url": normalize_url(full_url),
            "raw_url": full_url,
            "raw_text": title,  # listing pages rarely expose enough detail; classify.py
                                  # will fetch the detail page only for NEW candidates (cheap, low volume)
            "published_hint": "",
            "source_name": source["name"],
            "source_type": "scrape",
            "tags": source.get("tags", []),
        })
    return candidates


def fetch_detail_text(url: str, max_chars: int = 3000) -> str:
    """Called only for candidates that survive dedupe -- fetches the detail page
    so classify.py has enough text to extract a deadline and write a real summary."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return text[:max_chars]
    except Exception as e:
        print(f"[scrape] could not fetch detail page {url}: {e}")
        return ""
