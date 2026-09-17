"""
tests/test_dedupe.py
====================
Unit tests for src/dedupe.py — exact URL dedup, fuzzy title dedup, and the
seen.json write-back behaviour.
"""
import pytest
from unittest.mock import patch
from src.dedupe import filter_new


def make_candidate(title: str, url: str, source: str = "test") -> dict:
    return {
        "title": title,
        "url": url,
        "raw_url": url,
        "raw_text": title,
        "source_name": source,
        "source_type": "rss",
        "tags": [],
        "published_hint": "",
    }


class TestFilterNew:
    def test_first_run_all_pass(self, tmp_path, monkeypatch):
        """On a clean seen.json, all candidates should pass through."""
        from src import utils as u
        monkeypatch.setattr(u, "DATA_DIR", tmp_path)
        monkeypatch.setattr(u, "SEEN_PATH", tmp_path / "seen.json")

        candidates = [
            make_candidate("Job A", "https://a.com/1"),
            make_candidate("Job B", "https://b.com/2"),
        ]
        result = filter_new(candidates)
        assert len(result) == 2

    def test_exact_url_dupe_filtered(self, tmp_path, monkeypatch):
        """Exact URL match should be filtered after first run."""
        from src import utils as u
        monkeypatch.setattr(u, "DATA_DIR", tmp_path)
        monkeypatch.setattr(u, "SEEN_PATH", tmp_path / "seen.json")

        candidates = [make_candidate("Job A", "https://a.com/1")]
        # First run — populates seen.json
        filter_new(candidates)
        # Second run — same URL should be filtered
        result = filter_new(candidates)
        assert len(result) == 0

    def test_fuzzy_title_dupe_filtered(self, tmp_path, monkeypatch):
        """Near-identical titles under different URLs should be fuzzy-deduplicated."""
        from src import utils as u
        monkeypatch.setattr(u, "DATA_DIR", tmp_path)
        monkeypatch.setattr(u, "SEEN_PATH", tmp_path / "seen.json")

        # First run: exact candidate
        filter_new([make_candidate("Goldman Sachs Summer Analyst 2027 India", "https://gs.com/1")])

        # Second run: same title with trivial variation, different URL
        result = filter_new([
            make_candidate("Goldman Sachs Summer Analyst India 2027", "https://gs.com/2")
        ])
        assert len(result) == 0, "Should be deduped as fuzzy match"

    def test_genuinely_different_title_passes(self, tmp_path, monkeypatch):
        """A genuinely different opportunity should not be blocked by fuzzy matching."""
        from src import utils as u
        monkeypatch.setattr(u, "DATA_DIR", tmp_path)
        monkeypatch.setattr(u, "SEEN_PATH", tmp_path / "seen.json")

        filter_new([make_candidate("Goldman Sachs Summer Analyst", "https://a.com/1")])
        result = filter_new([make_candidate("Fulbright Scholarship 2027", "https://b.com/2")])
        assert len(result) == 1

    def test_seen_written_back(self, tmp_path, monkeypatch):
        """After filter_new, the seen.json file should exist and contain the new URL."""
        import json
        from src import utils as u
        seen_path = tmp_path / "seen.json"
        monkeypatch.setattr(u, "DATA_DIR", tmp_path)
        monkeypatch.setattr(u, "SEEN_PATH", seen_path)

        filter_new([make_candidate("Test Job", "https://test.com/job")])

        assert seen_path.exists()
        data = json.loads(seen_path.read_text())
        assert "https://test.com/job" in data

    def test_empty_input_returns_empty(self, tmp_path, monkeypatch):
        from src import utils as u
        monkeypatch.setattr(u, "DATA_DIR", tmp_path)
        monkeypatch.setattr(u, "SEEN_PATH", tmp_path / "seen.json")
        assert filter_new([]) == []
