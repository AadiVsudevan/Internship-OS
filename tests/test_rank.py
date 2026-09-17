"""
tests/test_rank.py
==================
Unit tests for src/rank.py — urgency decay, focus match, effort efficiency,
and the composite score formula.
"""
import pytest
from datetime import date, timedelta
from src.rank import score, _urgency_score, _focus_score, WEIGHTS


class TestUrgencyScore:
    def test_due_in_1_day_scores_100(self):
        d = (date.today() + timedelta(days=1)).isoformat()
        assert _urgency_score(d, is_rolling=False) == 100

    def test_due_in_3_days_scores_100(self):
        d = (date.today() + timedelta(days=3)).isoformat()
        assert _urgency_score(d, is_rolling=False) == 100

    def test_due_in_30_days_scores_10(self):
        d = (date.today() + timedelta(days=30)).isoformat()
        assert _urgency_score(d, is_rolling=False) == 10

    def test_past_deadline_scores_0(self):
        d = (date.today() - timedelta(days=1)).isoformat()
        assert _urgency_score(d, is_rolling=False) == 0

    def test_rolling_scores_neutral(self):
        # Rolling has no deadline; should get neutral 40
        assert _urgency_score(None, is_rolling=True) == 40

    def test_no_deadline_scores_neutral(self):
        assert _urgency_score(None, is_rolling=False) == 40

    def test_mid_range_decays_linearly(self):
        d15 = (date.today() + timedelta(days=15)).isoformat()
        d16 = (date.today() + timedelta(days=16)).isoformat()
        score15 = _urgency_score(d15, is_rolling=False)
        score16 = _urgency_score(d16, is_rolling=False)
        assert score15 > score16  # Later deadline → lower urgency


class TestFocusScore:
    def test_perfect_match_scores_high(self):
        s = _focus_score(["finance", "india", "research"])
        assert s >= 100  # 3 matches × 35 = 105, capped at 100

    def test_no_match_scores_0(self):
        assert _focus_score(["cooking", "gardening"]) == 0

    def test_empty_tags_scores_0(self):
        assert _focus_score([]) == 0

    def test_single_match_scores_35(self):
        assert _focus_score(["finance"]) == 35


class TestCompositeScore:
    def test_weights_sum_to_1(self):
        assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

    def test_high_roi_high_rank(self, sample_classified):
        """Higher ROI score → higher rank score (all else equal)."""
        low = dict(sample_classified, roi_score=10)
        high = dict(sample_classified, roi_score=90)
        assert score(high) > score(low)

    def test_near_deadline_boosts_rank(self, sample_classified):
        urgent_deadline = (date.today() + timedelta(days=1)).isoformat()
        far_deadline = (date.today() + timedelta(days=60)).isoformat()
        near = dict(sample_classified, _deadline_iso=urgent_deadline, is_rolling=False)
        far = dict(sample_classified, _deadline_iso=far_deadline, is_rolling=False)
        assert score(near) > score(far)

    def test_score_bounded_0_100(self, sample_classified):
        s = score(sample_classified)
        assert 0 <= s <= 100

    def test_effort_lt1h_boosts_rank(self, sample_classified):
        quick = dict(sample_classified, effort_estimate="<1h")
        slow = dict(sample_classified, effort_estimate="3h+")
        assert score(quick) > score(slow)

    def test_score_is_float(self, sample_classified):
        assert isinstance(score(sample_classified), float)
