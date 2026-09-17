"""Bounded RSS/Atom and configured HTML ingestion; no persistent seen state."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.personal_engine import canonical_url

logger = logging.getLogger(__name__)
MAX_BYTES = 2_000_000


def fetch(source: dict) -> list[dict]:
    """Re-read listings each run so failed writes and capped candidates can recover."""
    canonical_url(source["url"])
    with requests.Session() as session:
        retry = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET"], respect_retry_after_header=False)
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
        with session.get(source["url"], timeout=(10, 20), stream=True,
                         headers={"User-Agent": "OpportunityOS/2.0 (personal opportunity reader)"}) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError("Source exceeds 2 MB limit")
    candidates = []
    if source["kind"] == "rss":
        feed = feedparser.parse(bytes(body))
        if not feed.version:
            raise ValueError("URL did not return an RSS/Atom feed (possibly blocked or changed)")
        entries = [{"title": e.get("title", ""), "url": e.get("link", ""),
                    "raw_text": e.get("summary", "") + " " + " ".join(c.get("value", "") for c in e.get("content", []))}
                   for e in feed.entries]
    elif source["kind"] == "page":
        soup = BeautifulSoup(bytes(body), "html.parser")
        for item in soup.select("script, style, nav, footer, header"):
            item.decompose()
        content = soup.select_one(source.get("content_selector", "body"))
        if content is None or len(content.get_text(" ", strip=True)) < 100:
            raise ValueError("Programme page is empty or selector changed")
        entries = [{"title": source["title"], "url": source["url"],
                    "raw_text": "Programme directory: verify a specific current opening before applying. " + content.get_text(" ", strip=True)}]
    elif source["kind"] == "html":
        from urllib.parse import urljoin
        soup = BeautifulSoup(bytes(body), "html.parser")
        entries = []
        for item in soup.select(source["list_selector"]):
            title = item.select_one(source["title_selector"])
            link = item.select_one(source["link_selector"])
            if title and link and link.get("href"):
                entries.append({"title": title.get_text(" ", strip=True),
                                "url": urljoin(source["url"], link["href"]),
                                "raw_text": item.get_text(" ", strip=True)})
    else:
        raise ValueError(f"Unsupported source kind: {source['kind']}")
    for entry in entries:
        if not entry["title"] or not entry["url"]:
            continue
        try:
            url = canonical_url(entry["url"])
        except ValueError:
            continue
        text = BeautifulSoup(entry["raw_text"], "html.parser").get_text(" ", strip=True)
        candidates.append({"title": entry["title"], "url": url, "raw_text": text,
                           "source_name": source["name"], "primary": source.get("primary", False)})
    if not candidates:
        raise ValueError("No listings found: inspect source/selector before treating as healthy")
    return candidates


def gather(sources: list[dict], now: str) -> tuple[list[dict], list[dict]]:
    enabled = [s for s in sources if s.get("enabled", True)]
    if not enabled:
        raise ValueError("No enabled discovery sources")
    if len({s["name"] for s in enabled}) != len(enabled):
        raise ValueError("Source names must be unique")
    candidates, health = [], []
    # Collect in configuration order to make the new-item cap reproducible.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [(source, pool.submit(fetch, source)) for source in enabled]
        for source, future in futures:
            try:
                rows = future.result()
                candidates.extend(rows)
                health.append({"Source": source["name"], "Checked at": now, "Status": "OK", "Items": len(rows), "Detail": source["url"]})
            except Exception as exc:
                logger.error("source_failed source=%s error=%s", source["name"], type(exc).__name__)
                health.append({"Source": source["name"], "Checked at": now, "Status": "FAILED", "Items": 0,
                               "Detail": f"{type(exc).__name__}: {str(exc)[:300]}"})
    return candidates, health
