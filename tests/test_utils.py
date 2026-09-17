"""
tests/test_utils.py
===================
Unit tests for src/utils.py — URL normalisation, seen.json persistence,
rule-based scorer, and retry decorator.
"""
import json
import time
import pytest
from pathlib import Path
from src.utils import (
    normalize_url,
    load_seen,
    save_seen,
    rule_based_score,
    extract_focus_tags,
    with_retry,
)


# ── normalize_url ─────────────────────────────────────────────────────────────

class TestNormalizeUrl:
    def test_strips_utm_params(self):
        url = "https://example.com/job?utm_source=linkedin&utm_campaign=summer"
        assert normalize_url(url) == "https://example.com/job"

    def test_strips_trailing_slash(self):
        assert normalize_url("https://example.com/job/") == "https://example.com/job"

    def test_lowercases(self):
        assert normalize_url("https://EXAMPLE.COM/Job") == "https://example.com/job"

    def test_preserves_non_tracking_params(self):
        url = "https://example.com/job?id=123&ref=linkedin"
        # 'ref' is a tracking param, 'id' is not
        result = normalize_url(url)
        assert "id=123" in result
        assert "ref=" not in result

    def test_strips_fragment(self):
        assert normalize_url("https://example.com/job#apply") == "https://example.com/job"

    def test_empty_url_passthrough(self):
        assert normalize_url("") == ""

    def test_none_passthrough(self):
        assert normalize_url(None) is None

    def test_two_identical_urls_normalise_to_same(self):
        url1 = "https://example.com/job?utm_source=email"
        url2 = "https://example.com/job?utm_medium=social"
        assert normalize_url(url1) == normalize_url(url2)


# ── Seen state ────────────────────────────────────────────────────────────────

class TestSeenState:
    def test_round_trip(self, tmp_path, monkeypatch):
        """save_seen then load_seen should return identical data."""
        from src import utils as utils_module
        monkeypatch.setattr(utils_module, "DATA_DIR", tmp_path)
        monkeypatch.setattr(utils_module, "SEEN_PATH", tmp_path / "seen.json")

        data = {"https://example.com/job": {"title": "Test Job", "source": "rss", "duplicate_of": False}}
        save_seen(data)
        loaded = load_seen()
        assert loaded == data

    def test_load_missing_file_returns_empty(self, tmp_path, monkeypatch):
        from src import utils as utils_module
        monkeypatch.setattr(utils_module, "DATA_DIR", tmp_path)
        monkeypatch.setattr(utils_module, "SEEN_PATH", tmp_path / "nonexistent.json")
        assert load_seen() == {}

    def test_load_corrupt_file_returns_empty(self, tmp_path, monkeypatch):
        from src import utils as utils_module
        corrupt = tmp_path / "seen.json"
        corrupt.write_text("NOT VALID JSON{{{")
        monkeypatch.setattr(utils_module, "DATA_DIR", tmp_path)
        monkeypatch.setattr(utils_module, "SEEN_PATH", corrupt)
        assert load_seen() == {}


# ── rule_based_score ─────────────────────────────────────────────────────────

class TestRuleBasedScore:
    def test_tier1_keyword_scores_40(self):
        assert rule_based_score("Goldman Sachs summer internship 2027") == 40

    def test_tier2_keyword_scores_20(self):
        assert rule_based_score("fellowship in behavioral economics research") == 20

    def test_tier3_keyword_scores_5(self):
        assert rule_based_score("internship opportunity at local firm") == 5

    def test_no_match_scores_0(self):
        assert rule_based_score("random text with no keywords here") == 0

    def test_capped_at_100(self):
        # tier1 match alone gives 40, not more
        score = rule_based_score("Goldman Sachs Rhodes Scholarship fellowship internship")
        assert score <= 100

    def test_case_insensitive(self):
        assert rule_based_score("GOLDMAN SACHS INTERNSHIP") == 40


# ── extract_focus_tags ────────────────────────────────────────────────────────

class TestExtractFocusTags:
    def test_finds_finance_tag(self):
        tags = extract_focus_tags("This is a finance internship")
        assert "finance" in tags

    def test_finds_india_tag(self):
        tags = extract_focus_tags("Mumbai-based economics research role")
        assert "india" not in tags  # "mumbai" is not in FOCUS_TAGS list; "india" literal is
        tags2 = extract_focus_tags("Internship at RBI, India")
        assert "india" in tags2

    def test_hyphenated_tag_matches(self):
        tags = extract_focus_tags("behavioral economics study")
        assert "behavioral-economics" in tags

    def test_returns_empty_for_no_match(self):
        assert extract_focus_tags("random text about cooking recipes") == []


# ── with_retry ────────────────────────────────────────────────────────────────

class TestWithRetry:
    def test_succeeds_on_first_try(self):
        calls = []

        @with_retry(max_attempts=3)
        def always_succeeds():
            calls.append(1)
            return "ok"

        result = always_succeeds()
        assert result == "ok"
        assert len(calls) == 1

    def test_retries_on_failure_then_succeeds(self):
        calls = []

        @with_retry(max_attempts=3, base_delay=0.01)
        def fails_twice():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("temporary failure")
            return "ok"

        result = fails_twice()
        assert result == "ok"
        assert len(calls) == 3

    def test_raises_after_max_attempts(self):
        @with_retry(max_attempts=2, base_delay=0.01)
        def always_fails():
            raise RuntimeError("permanent failure")

        with pytest.raises(RuntimeError, match="permanent failure"):
            always_fails()

    def test_only_retries_specified_exceptions(self):
        calls = []

        @with_retry(max_attempts=3, base_delay=0.01, exceptions=(ValueError,))
        def raises_type_error():
            calls.append(1)
            raise TypeError("not retried")

        with pytest.raises(TypeError):
            raises_type_error()
        # Should not retry TypeError since only ValueError is in exceptions
        assert len(calls) == 1
