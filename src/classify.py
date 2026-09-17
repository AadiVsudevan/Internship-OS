from __future__ import annotations
"""
src/classify.py
===============
Classifies each NEW (post-dedupe) candidate using the Groq LLM API, with an
automatic fallback to a deterministic rule-based scorer.

Design principles:
  - Discovery (ingestion) never depends on an LLM — this is the ONLY module
    that calls one.
  - Called only for the small number of candidates that survive dedupe each
    run (typically a handful), so even Groq's free-tier 30 req/min cap is not
    a concern in normal operation.
  - If GROQ_API_KEY is unset, USE_LLM_CLASSIFICATION=false, or Groq returns
    an error after retries, this silently falls back to the keyword-based
    scorer in src/utils.py. The pipeline NEVER stalls because of a third-party
    outage.

Output shape (both LLM and fallback return the same keys):
  {
    "type": "Internship" | "Fellowship" | "Research" | "Competition" |
            "Summer Program" | "Scholarship" | "Grant" | "Other",
    "geography": "India" | "US" | "UK" | "EU" | "Remote" | "Other",
    "focus_tags": [str, ...],       # up to 4
    "roi_score": int,               # 0-100
    "effort_estimate": "<1h" | "1-3h" | "3h+",
    "deadline_text": str | null,
    "is_rolling": bool,
    "summary": str,                 # one sentence, ≤ 20 words
    "_deadline_iso": str | null,    # YYYY-MM-DD, cross-checked by deadline.py
    "_classified_by": "groq_llm" | "rule_based_fallback",
  }
"""
import json
import time
import logging
import requests

from src.utils import env, rule_based_score, extract_focus_tags
from src.deadline import extract_deadline

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """\
You are a strict JSON-only classifier for a college student's internship/fellowship discovery pipeline.
Given a title + raw text snippet about an opportunity, return ONLY a JSON object (no markdown fences, no prose) with these exact keys:
{
  "type": one of ["Internship","Fellowship","Research","Competition","Summer Program","Scholarship","Grant","Other"],
  "geography": one of ["India","US","UK","EU","Remote","Other"],
  "focus_tags": array of up to 4 strings from ["finance","economics","behavioral-economics","wealthtech","private-markets","research","policy","tech","general"],
  "roi_score": integer 0-100 estimating long-term career/resume value (org prestige, selectivity, compounding value),
  "effort_estimate": one of ["<1h","1-3h","3h+"],
  "deadline_text": the deadline as written in the source text if present, else null,
  "is_rolling": boolean,
  "summary": a single sentence (max 20 words) summary in your own words.
}
Be conservative with roi_score: 80+ only for globally recognized organizations or highly selective programs.\
"""


def _parse_json_safely(content: str) -> dict | None:
    """Parse LLM output that might have markdown fences or leading/trailing whitespace."""
    if not content:
        return None
    # Strip markdown fences if the model added them despite instructions.
    stripped = content.strip()
    if stripped.startswith("```"):
        # Remove ```json ... ``` wrapper
        lines = stripped.split("\n")
        stripped = "\n".join(lines[1:-1]) if len(lines) > 2 else stripped
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None


def _call_groq(title: str, raw_text: str) -> dict | None:
    """Call the Groq API and return parsed classification JSON, or None on failure.

    Retries up to 3 times with back-off. Returns None (triggering the fallback)
    on rate-limits, network errors, or malformed responses.
    """
    api_key = env("GROQ_API_KEY")
    if not api_key or env("USE_LLM_CLASSIFICATION", "true").lower() != "true":
        return None

    model = env("GROQ_MODEL", "llama-3.1-8b-instant")

    # Truncate raw_text to avoid blowing the context window / costing tokens.
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"TITLE: {title}\nTEXT: {raw_text[:2000]}"},
        ],
        "temperature": 0.2,
        # json_object format is supported by llama-3.x models on Groq.
        # If you swap to a different model that doesn't support it, remove this
        # line — the SYSTEM_PROMPT's "ONLY a JSON object" instruction still works.
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(1, 4):
        try:
            resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=20)

            if resp.status_code == 429:
                # Rate-limited — respect the retry-after header.
                wait = float(resp.headers.get("retry-after", 5))
                logger.warning("Groq rate-limited on attempt %d/3 — waiting %.0fs", attempt, wait)
                time.sleep(min(wait, 30))
                continue

            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = _parse_json_safely(content)
            if parsed is None:
                logger.warning("Groq returned unparseable JSON on attempt %d/3", attempt)
                continue
            return parsed

        except requests.exceptions.RequestException as e:
            logger.warning("Groq HTTP error attempt %d/3: %s", attempt, e)
            time.sleep(2 ** attempt)  # exponential back-off: 2s, 4s, 8s

        except Exception as e:
            logger.warning("Groq unexpected error attempt %d/3: %s", attempt, e)
            time.sleep(2)

    logger.warning("All 3 Groq attempts failed — using rule-based fallback.")
    return None


def _fallback(title: str, raw_text: str, tags: list) -> dict:
    """Deterministic rule-based classification used when LLM is unavailable.

    Guaranteed to return a valid classification dict with all required keys.
    Less nuanced than the LLM but structurally identical — downstream code
    doesn't need to know which path was taken (except for the _classified_by
    key, which is logged for observability).
    """
    full_text = f"{title} {raw_text}"
    deadline = extract_deadline(full_text)
    is_india = any(
        w in full_text.lower()
        for w in ["india", "bengaluru", "bangalore", "mumbai", "delhi", "nse", "bse", "rbi", "sebi"]
    )

    # Infer type from keywords
    type_map = [
        ("fellowship", "Fellowship"),
        ("scholarship", "Scholarship"),
        ("research", "Research"),
        ("competition", "Competition"),
        ("hackathon", "Competition"),
        ("grant", "Grant"),
        ("summer program", "Summer Program"),
        ("internship", "Internship"),
    ]
    opp_type = "Other"
    for keyword, label in type_map:
        if keyword in full_text.lower():
            opp_type = label
            break

    return {
        "type": opp_type,
        "geography": "India" if is_india else "Other",
        "focus_tags": extract_focus_tags(full_text) or tags or ["general"],
        "roi_score": rule_based_score(full_text),
        "effort_estimate": "1-3h",
        "deadline_text": None,
        "is_rolling": "rolling" in full_text.lower(),
        "summary": title[:140],
        "_deadline_iso": deadline,
        "_classified_by": "rule_based_fallback",
    }


def classify(candidate: dict) -> dict:
    """Classify a raw candidate. Tries Groq LLM first; falls back to rules.

    Args:
        candidate: dict as produced by any ingest module (rss/scrape/github_lists).

    Returns:
        Classification dict with all keys including _deadline_iso and _classified_by.
    """
    title = candidate["title"]
    raw_text = candidate.get("raw_text", "")
    tags = candidate.get("tags", [])

    result = _call_groq(title, raw_text)

    if result is None:
        return _fallback(title, raw_text, tags)

    # Even when the LLM extracts a deadline_text, cross-check it with the regex
    # extractor — the LLM sometimes misformats dates or makes them up.
    # The regex result is more reliable for ISO formatting.
    deadline_iso = extract_deadline(result.get("deadline_text") or raw_text)
    result["_deadline_iso"] = deadline_iso
    result["_classified_by"] = "groq_llm"

    # Guard against missing optional keys that downstream code expects.
    result.setdefault("focus_tags", tags or ["general"])
    result.setdefault("is_rolling", False)
    result.setdefault("effort_estimate", "1-3h")
    result.setdefault("roi_score", 0)

    return result
