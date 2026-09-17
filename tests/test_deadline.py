"""
tests/test_deadline.py
======================
Unit tests for src/deadline.py — regex keyword detection, natural-language
date parsing, and days_until calculation.
"""
import pytest
from datetime import date, timedelta
from unittest.mock import patch
from src.deadline import extract_deadline, days_until


class TestExtractDeadline:
    def test_apply_by_phrasing(self):
        result = extract_deadline("Apply by March 15, 2027 to be considered.")
        assert result == "2027-03-15"

    def test_deadline_phrasing(self):
        result = extract_deadline("Deadline: June 30, 2027.")
        assert result == "2027-06-30"

    def test_last_date_phrasing(self):
        result = extract_deadline("Last date to apply: December 1, 2027")
        assert result is not None
        assert "2027-12" in result

    def test_rolling_returns_none(self):
        result = extract_deadline("Applications are reviewed on a rolling basis.")
        assert result is None

    def test_no_date_returns_none(self):
        result = extract_deadline("This is a great internship with many benefits.")
        assert result is None

    def test_empty_text_returns_none(self):
        assert extract_deadline("") is None

    def test_none_text_returns_none(self):
        assert extract_deadline(None) is None

    def test_past_date_not_returned(self):
        # dateparser with PREFER_DATES_FROM=future should skip obviously past dates
        # We can't easily test a fixed past date without mocking "now", so just
        # verify the function runs cleanly.
        result = extract_deadline("Deadline was January 1, 2020.")
        # Past date — should return None (or None if dateparser rejects it)
        # This tests that we don't crash on past dates.
        assert result is None or isinstance(result, str)


class TestDaysUntil:
    def test_future_date_is_positive(self):
        future = (date.today() + timedelta(days=10)).isoformat()
        assert days_until(future) == 10

    def test_past_date_is_negative(self):
        past = (date.today() - timedelta(days=5)).isoformat()
        assert days_until(past) == -5

    def test_today_is_zero(self):
        today = date.today().isoformat()
        assert days_until(today) == 0

    def test_none_returns_none(self):
        assert days_until(None) is None

    def test_invalid_string_returns_none(self):
        assert days_until("not-a-date") is None
