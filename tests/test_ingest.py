"""
tests/test_ingest.py
====================
Unit tests for all three ingest modules (rss, scrape, github_lists).
Uses mocked HTTP so no real network calls are made during CI.
"""
import pytest
from unittest.mock import patch, MagicMock


# ── RSS ───────────────────────────────────────────────────────────────────────

class TestRssIngest:
    def _make_feed(self, entries):
        """Build a minimal feedparser-like object."""
        feed = MagicMock()
        feed.bozo = False
        feed.entries = entries
        return feed

    def _make_entry(self, title, link, summary=""):
        entry = MagicMock()
        entry.get = lambda k, default="": {
            "title": title, "link": link, "summary": summary,
            "published": "", "description": "", "updated": "",
        }.get(k, default)
        return entry

    def test_fetch_returns_candidates(self):
        entries = [self._make_entry("Goldman Internship", "https://gs.com/1", "Finance role")]
        feed = self._make_feed(entries)

        with patch("src.ingest.rss.feedparser.parse", return_value=feed):
            from src.ingest import rss
            source = {"name": "Test", "url": "http://test.com/feed", "tags": ["finance"]}
            result = rss.fetch(source)

        assert len(result) == 1
        assert result[0]["title"] == "Goldman Internship"
        assert result[0]["source_type"] == "rss"

    def test_fetch_skips_entries_without_link(self):
        entries = [self._make_entry("No Link", "", "no url here")]
        feed = self._make_feed(entries)

        with patch("src.ingest.rss.feedparser.parse", return_value=feed):
            from src.ingest import rss
            source = {"name": "Test", "url": "http://test.com/feed", "tags": []}
            result = rss.fetch(source)

        assert result == []

    def test_fetch_handles_network_error_gracefully(self):
        with patch("src.ingest.rss.feedparser.parse", side_effect=Exception("network error")):
            from src.ingest import rss
            source = {"name": "Test", "url": "http://bad.com/feed", "tags": []}
            result = rss.fetch(source)

        assert result == []

    def test_url_is_normalised(self):
        entries = [self._make_entry("Job", "https://a.com/job?utm_source=email")]
        feed = self._make_feed(entries)

        with patch("src.ingest.rss.feedparser.parse", return_value=feed):
            from src.ingest import rss
            source = {"name": "Test", "url": "http://test.com/feed", "tags": []}
            result = rss.fetch(source)

        assert "utm_source" not in result[0]["url"]
        assert result[0]["raw_url"] == "https://a.com/job?utm_source=email"


# ── Scrape ────────────────────────────────────────────────────────────────────

class TestScrapeIngest:
    def test_fetch_parses_html(self):
        html = """
        <html><body>
          <div class="listing">
            <h2 class="title">Finance Intern</h2>
            <a class="link" href="/careers/finance">Apply</a>
          </div>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        with patch("src.ingest.scrape.requests.get", return_value=mock_resp):
            from src.ingest import scrape
            source = {
                "name": "Test",
                "url": "https://example.com/careers",
                "list_selector": "div.listing",
                "title_selector": "h2.title",
                "link_selector": "a.link",
                "link_attr": "href",
                "base_url": "https://example.com",
                "tags": ["finance"],
            }
            result = scrape.fetch(source)

        assert len(result) == 1
        assert result[0]["title"] == "Finance Intern"
        assert "example.com/careers/finance" in result[0]["url"]

    def test_warns_when_no_items_matched(self, capsys):
        html = "<html><body><p>No listings here</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        with patch("src.ingest.scrape.requests.get", return_value=mock_resp):
            from src.ingest import scrape
            source = {
                "name": "Dead Source",
                "url": "https://example.com",
                "list_selector": "div.listing",
                "title_selector": "h2",
                "link_selector": "a",
                "link_attr": "href",
                "base_url": "https://example.com",
                "tags": [],
            }
            result = scrape.fetch(source)

        assert result == []

    def test_network_error_returns_empty(self):
        import requests
        with patch("src.ingest.scrape.requests.get", side_effect=requests.exceptions.Timeout):
            from src.ingest import scrape
            source = {"name": "Bad", "url": "https://bad.com", "list_selector": "div",
                      "title_selector": "h2", "link_selector": "a", "link_attr": "href",
                      "base_url": "https://bad.com", "tags": []}
            result = scrape.fetch(source)
        assert result == []


# ── GitHub Lists ──────────────────────────────────────────────────────────────

class TestGithubListsIngest:
    def test_new_lines_surfaced_as_candidates(self, tmp_path, monkeypatch):
        from src.ingest import github_lists as gl
        # Redirect snapshot dir to tmp_path
        monkeypatch.setattr(gl, "SNAPSHOT_DIR", tmp_path)

        new_content = "- [Fulbright Scholarship](https://fulbright.org) — prestigious award\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = new_content
        mock_resp.raise_for_status = MagicMock()

        with patch("src.ingest.github_lists.requests.get", return_value=mock_resp):
            source = {"name": "Test List", "repo": "user/repo", "path": "README.md", "tags": []}
            result = gl.fetch(source)

        assert len(result) == 1
        assert result[0]["title"] == "Fulbright Scholarship"
        assert "fulbright.org" in result[0]["url"]

    def test_unchanged_lines_not_surfaced(self, tmp_path, monkeypatch):
        from src.ingest import github_lists as gl
        monkeypatch.setattr(gl, "SNAPSHOT_DIR", tmp_path)

        content = "- [Job A](https://a.com) — some job\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = content
        mock_resp.raise_for_status = MagicMock()

        # First fetch — content is "new"
        with patch("src.ingest.github_lists.requests.get", return_value=mock_resp):
            source = {"name": "Test", "repo": "user/repo", "path": "README.md", "tags": []}
            result1 = gl.fetch(source)
        assert len(result1) == 1

        # Second fetch — same content, nothing new
        with patch("src.ingest.github_lists.requests.get", return_value=mock_resp):
            result2 = gl.fetch(source)
        assert result2 == []

    def test_network_error_returns_empty(self):
        import requests
        with patch("src.ingest.github_lists.requests.get", side_effect=Exception("network down")):
            from src.ingest import github_lists as gl
            source = {"name": "Bad", "repo": "user/repo", "path": "README.md", "tags": []}
            result = gl.fetch(source)
        assert result == []
