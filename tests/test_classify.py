"""
tests/test_classify.py
======================
Unit tests for src/classify.py — fallback behaviour, Groq mock, and the
_parse_json_safely helper.
"""
import pytest
from unittest.mock import patch, MagicMock
import json


class TestFallbackClassifier:
    """The fallback path must work with zero external calls."""

    def test_fallback_used_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        from src.classify import classify

        candidate = {
            "title": "Fellowship in Behavioral Economics",
            "raw_text": "Deadline: April 30, 2027. Rolling admissions.",
            "tags": ["economics"],
        }
        result = classify(candidate)
        assert result["_classified_by"] == "rule_based_fallback"
        assert result["type"] in ["Fellowship", "Internship", "Research", "Competition",
                                  "Summer Program", "Scholarship", "Grant", "Other"]

    def test_fallback_detects_india_geography(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        from src.classify import classify

        candidate = {
            "title": "Research Internship at NSE India",
            "raw_text": "Located in Mumbai, India.",
            "tags": [],
        }
        result = classify(candidate)
        assert result["geography"] == "India"

    def test_fallback_has_all_required_keys(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        from src.classify import classify

        candidate = {"title": "Some Internship", "raw_text": "", "tags": []}
        result = classify(candidate)

        required_keys = [
            "type", "geography", "focus_tags", "roi_score", "effort_estimate",
            "summary", "is_rolling", "deadline_text", "_deadline_iso", "_classified_by",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_roi_score_bounded_0_100(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        from src.classify import classify

        candidate = {
            "title": "Goldman Sachs Fellowship Research Internship",
            "raw_text": "Prestige tier1 opportunity",
            "tags": [],
        }
        result = classify(candidate)
        assert 0 <= result["roi_score"] <= 100

    def test_use_llm_false_forces_fallback(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
        monkeypatch.setenv("USE_LLM_CLASSIFICATION", "false")
        from src.classify import classify

        candidate = {"title": "Test Opportunity", "raw_text": "", "tags": []}
        result = classify(candidate)
        assert result["_classified_by"] == "rule_based_fallback"


class TestParseJsonSafely:
    """Tests for the internal JSON parser that handles LLM responses."""

    def test_parses_clean_json(self):
        from src.classify import _parse_json_safely
        data = {"type": "Internship", "roi_score": 70}
        assert _parse_json_safely(json.dumps(data)) == data

    def test_strips_markdown_fences(self):
        from src.classify import _parse_json_safely
        content = '```json\n{"type": "Fellowship"}\n```'
        result = _parse_json_safely(content)
        assert result == {"type": "Fellowship"}

    def test_returns_none_on_invalid_json(self):
        from src.classify import _parse_json_safely
        assert _parse_json_safely("This is not JSON at all") is None

    def test_returns_none_on_empty(self):
        from src.classify import _parse_json_safely
        assert _parse_json_safely("") is None
        assert _parse_json_safely(None) is None


class TestGroqIntegration:
    """Tests for the Groq call path using mocked HTTP."""

    def test_successful_groq_response_used(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
        monkeypatch.setenv("USE_LLM_CLASSIFICATION", "true")

        mock_response = {
            "type": "Fellowship",
            "geography": "US",
            "focus_tags": ["research", "economics"],
            "roi_score": 85,
            "effort_estimate": "3h+",
            "deadline_text": "March 15, 2027",
            "is_rolling": False,
            "summary": "Prestigious economics research fellowship at Harvard.",
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps(mock_response)}}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("src.classify.requests.post", return_value=mock_resp):
            from importlib import reload
            import src.classify
            reload(src.classify)

            candidate = {
                "title": "Harvard Economics Fellowship",
                "raw_text": "Apply by March 15, 2027",
                "tags": [],
            }
            result = src.classify.classify(candidate)

        assert result["_classified_by"] == "groq_llm"
        assert result["type"] == "Fellowship"
        assert result["roi_score"] == 85

    def test_falls_back_on_groq_error(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
        monkeypatch.setenv("USE_LLM_CLASSIFICATION", "true")

        import requests as req
        with patch("src.classify.requests.post", side_effect=req.exceptions.Timeout("timeout")):
            from importlib import reload
            import src.classify
            reload(src.classify)

            candidate = {"title": "Test Opportunity", "raw_text": "", "tags": []}
            result = src.classify.classify(candidate)

        assert result["_classified_by"] == "rule_based_fallback"
