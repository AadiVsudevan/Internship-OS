from __future__ import annotations
"""
src/models.py
=============
Structured data model for an Opportunity throughout the pipeline.

Why a dataclass instead of plain dicts:
- Type hints catch bugs (e.g. passing a string where a float is expected).
- `.asdict()` makes serialisation to Notion properties explicit and auditable.
- A single definition here means changing a field name cascades through IDE
  refactoring instead of requiring a grep-and-replace across 7 files.
- `__post_init__` enforces invariants (e.g. ROI stays 0-100).

The pipeline flow is:
  RawCandidate (from ingest) -> filter_new (dedupe) -> classify -> score ->
  Opportunity (fully structured) -> create_opportunity (Notion sync)
"""
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import date


@dataclass
class RawCandidate:
    """What every ingestor produces. Minimal — just enough to dedupe and classify."""
    title: str
    url: str           # normalised URL (tracking params stripped)
    raw_url: str       # original URL as-found (stored in Notion for the actual link)
    raw_text: str      # title + description snippet for LLM / rule-based classifier
    source_name: str
    source_type: str   # "rss" | "scrape" | "github_list"
    tags: list[str] = field(default_factory=list)
    published_hint: str = ""

    def full_text(self) -> str:
        """Convenience: combined text blob for keyword matching."""
        return f"{self.title} {self.raw_text}"


@dataclass
class Classification:
    """Output of src/classify.py — what the LLM (or rule fallback) returns."""
    type: str                         # "Internship" | "Fellowship" | etc.
    geography: str                    # "India" | "US" | etc.
    focus_tags: list[str]
    roi_score: int                    # 0-100
    effort_estimate: str              # "<1h" | "1-3h" | "3h+"
    summary: str
    is_rolling: bool = False
    deadline_text: Optional[str] = None   # raw deadline string from source
    deadline_iso: Optional[str] = None    # YYYY-MM-DD, extracted by deadline.py
    classified_by: str = "rule_based_fallback"  # "groq_llm" | "rule_based_fallback"

    def __post_init__(self):
        self.roi_score = max(0, min(100, int(self.roi_score)))
        if self.effort_estimate not in ("<1h", "1-3h", "3h+"):
            self.effort_estimate = "1-3h"  # safe default


@dataclass
class Opportunity:
    """Fully scored, ranked opportunity ready to be written to Notion."""
    candidate: RawCandidate
    classification: Classification
    rank_score: float  # 0-100, computed by src/rank.py

    def __post_init__(self):
        self.rank_score = round(max(0.0, min(100.0, float(self.rank_score))), 1)

    def to_log_line(self) -> str:
        return (
            f"[{self.rank_score:5.1f}] {self.candidate.title[:70]}"
            f" | ROI={self.classification.roi_score}"
            f" | {self.classification.type}"
            f" | via={self.classification.classified_by}"
        )
