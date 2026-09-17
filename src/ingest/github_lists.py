"""Diff a markdown file in a GitHub repo (e.g. an 'Awesome Internships' list)
against the last-seen snapshot and surface newly added lines as candidates.
Curated community lists are high-signal and low-noise -- a maintainer already
filtered out junk -- which is why this is worth a dedicated ingester."""
import re
import requests
from pathlib import Path
from src.utils import DATA_DIR, normalize_url

SNAPSHOT_DIR = DATA_DIR / "github_snapshots"
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")


def _snapshot_path(repo: str, path: str) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe = f"{repo.replace('/', '_')}__{path.replace('/', '_')}.md"
    return SNAPSHOT_DIR / safe


def fetch(source: dict, branch: str = "main") -> list[dict]:
    repo, path = source["repo"], source["path"]
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 404:  # try 'master' as fallback default branch name
            url = f"https://raw.githubusercontent.com/{repo}/master/{path}"
            resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[github_list] FAILED to fetch {repo}/{path}: {e}")
        return []

    new_text = resp.text
    snap_path = _snapshot_path(repo, path)
    old_text = snap_path.read_text() if snap_path.exists() else ""

    old_lines = set(old_text.splitlines())
    new_lines = [l for l in new_text.splitlines() if l not in old_lines]

    snap_path.write_text(new_text)  # update snapshot for next run

    candidates = []
    for line in new_lines:
        for title, link_url in LINK_RE.findall(line):
            candidates.append({
                "title": title.strip(),
                "url": normalize_url(link_url),
                "raw_url": link_url,
                "raw_text": line.strip(),
                "published_hint": "",
                "source_name": source["name"],
                "source_type": "github_list",
                "tags": source.get("tags", []),
            })
    return candidates
