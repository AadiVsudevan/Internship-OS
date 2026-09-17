"""Two-layer dedupe so the same opportunity posted on two different sites
(or re-posted with a tracking param) doesn't create duplicate Notion pages.

Layer 1 (cheap, exact):   normalized URL hash against data/seen.json
Layer 2 (fuzzy, catches reposts with different URLs): title similarity via rapidfuzz
Layer 3 (safety net, see notion_sync.py): a live query against Notion itself
         before any page is created, so a wiped/corrupted seen.json can never
         re-flood your database with items you already triaged.
"""
from rapidfuzz import fuzz
from src.utils import load_seen, save_seen

FUZZY_THRESHOLD = 88  # 0-100; tune in src/utils.py if you get too many/few dupes flagged


def filter_new(candidates: list[dict]) -> list[dict]:
    seen = load_seen()
    seen_titles = [(url, v.get("title", "")) for url, v in seen.items()]

    new_candidates = []
    for c in candidates:
        url = c["url"]

        if url in seen:
            continue  # exact dupe, skip entirely

        is_fuzzy_dupe = False
        for seen_url, seen_title in seen_titles:
            if seen_title and fuzz.token_sort_ratio(c["title"], seen_title) >= FUZZY_THRESHOLD:
                is_fuzzy_dupe = True
                break
        if is_fuzzy_dupe:
            # Still record it under its own URL so we don't re-check it every run,
            # but don't push a second Notion page for it.
            seen[url] = {"title": c["title"], "source": c["source_name"], "duplicate_of": True}
            seen_titles.append((url, c["title"]))
            continue

        new_candidates.append(c)
        seen[url] = {"title": c["title"], "source": c["source_name"], "duplicate_of": False}
        seen_titles.append((url, c["title"]))  # so later candidates in THIS SAME run also get fuzzy-checked against it

    save_seen(seen)
    return new_candidates
