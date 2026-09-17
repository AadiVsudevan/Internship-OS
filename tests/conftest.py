"""
tests/conftest.py
=================
Shared pytest fixtures available to all tests.
"""
import pytest
import os


@pytest.fixture(autouse=True)
def clear_env_vars(monkeypatch):
    """Ensure tests don't accidentally pick up real credentials from .env."""
    for key in ["NOTION_TOKEN", "NOTION_OPPORTUNITIES_DB_ID", "NOTION_QUEUE_PAGE_ID",
                "GROQ_API_KEY"]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def sample_candidate():
    """A minimal valid raw candidate dict, as produced by ingest modules."""
    return {
        "title": "Goldman Sachs Summer Analyst – Finance (India)",
        "url": "https://goldmansachs.com/careers/summer-analyst",
        "raw_url": "https://goldmansachs.com/careers/summer-analyst?utm_source=linkedin",
        "raw_text": "Goldman Sachs Summer Analyst program India deadline April 30 2027",
        "source_name": "Test Source",
        "source_type": "rss",
        "tags": ["finance", "india"],
        "published_hint": "",
    }


@pytest.fixture
def sample_classified():
    """A minimal valid classification dict, as produced by classify.py."""
    return {
        "type": "Internship",
        "geography": "India",
        "focus_tags": ["finance", "india"],
        "roi_score": 80,
        "effort_estimate": "1-3h",
        "deadline_text": "April 30, 2027",
        "is_rolling": False,
        "summary": "Goldman Sachs summer analyst program for finance students.",
        "_deadline_iso": "2027-04-30",
        "_classified_by": "groq_llm",
    }
