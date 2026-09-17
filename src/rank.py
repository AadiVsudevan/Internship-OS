"""Transparent, debuggable ranking -- no black box. Weights are tunable
constants at the top of this file, not buried in a model.

rank_score (0-100) =
    0.40 * roi_score                (career value, from classify.py)
  + 0.25 * deadline_urgency         (100 if due <=3 days, decaying to 0 by 30 days)
  + 0.20 * focus_match              (overlap with YOUR target fields, set below)
  + 0.15 * effort_efficiency        (rewards quick high-value wins)
"""
from __future__ import annotations
from src.deadline import days_until

WEIGHTS = {"roi": 0.40, "urgency": 0.25, "focus": 0.20, "effort": 0.15}

# Edit this list as your interests evolve -- it's the main personalization lever.
TARGET_FOCUS = {"finance", "economics", "behavioral-economics", "wealthtech",
                 "private-markets", "research", "policy", "india"}

EFFORT_SCORE = {"<1h": 100, "1-3h": 60, "3h+": 30}


def _urgency_score(deadline_iso, is_rolling: bool) -> float:
    if is_rolling or not deadline_iso:
        return 40  # neutral-ish: not urgent, but don't bury it either
    days = days_until(deadline_iso)
    if days is None:
        return 40
    if days < 0:
        return 0  # already past -- archive.py will mark this Expired
    if days <= 3:
        return 100
    if days >= 30:
        return 10
    # linear decay between 3 and 30 days
    return round(100 - ((days - 3) / 27) * 90, 1)


def _focus_score(focus_tags: list) -> float:
    if not focus_tags:
        return 0
    overlap = len(set(focus_tags) & TARGET_FOCUS)
    return min(100, overlap * 35)


def score(classified: dict) -> float:
    roi = classified.get("roi_score", 0)
    urgency = _urgency_score(classified.get("_deadline_iso"), classified.get("is_rolling", False))
    focus = _focus_score(classified.get("focus_tags", []))
    effort = EFFORT_SCORE.get(classified.get("effort_estimate", "1-3h"), 60)

    total = (WEIGHTS["roi"] * roi + WEIGHTS["urgency"] * urgency
             + WEIGHTS["focus"] * focus + WEIGHTS["effort"] * effort)
    return round(total, 1)
