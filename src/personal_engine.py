"""Pure record normalization, conservative ranking and budgeted application queue."""
from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

AUTO_COLUMNS = ["ID", "Title", "Category", "Source URL", "Source", "Source excerpt",
                "Deadline candidate", "Last seen", "Last refreshed", "Availability", "Priority score",
                "Ranking reason", "Estimated hours", "Matched interests", "Possible duplicate",
                "Next action", "Application URL", "Source authority"]
HUMAN_COLUMNS = ["Status", "Eligibility", "Verified deadline", "Hours override", "Notes", "Verified application URL"]
PACK_COLUMNS = ["ID", "Opportunity", "Draft application", "Interview prep", "Source URL",
                "Evidence used", "Generated at", "Review state"]
PACK_HUMAN_COLUMNS = ["Edited answers", "Interview notes", "Official questions"]
QUEUE_COLUMNS = ["ID", "Priority", "Opportunity", "Action", "Deadline", "Hours", "Apply / review URL", "Pack ID", "Week starting"]
HEALTH_COLUMNS = ["Source", "Checked at", "Status", "Items", "Detail"]
AUDIT_COLUMNS = ["Run ID", "At", "Result", "Discovered", "New", "Updated", "Source failures", "Queue items"]
INBOX_COLUMNS = ["ID", "Title", "Source URL", "Source", "Source excerpt", "Observed at", "Primary source"]
ACTIVITY_COLUMNS = ["ID", "Opportunity ID", "Observed at", "Status", "Estimated hours", "Charge hours", "Week starting"]
SCHEMAS = {"Opportunities": AUTO_COLUMNS + HUMAN_COLUMNS,
           "Application Packs": PACK_COLUMNS + PACK_HUMAN_COLUMNS,
           "Weekly Queue": QUEUE_COLUMNS, "Verify First": QUEUE_COLUMNS,
           "Source Health": HEALTH_COLUMNS, "Run History": AUDIT_COLUMNS,
           "Discovery Inbox": INBOX_COLUMNS, "Application Activity": ACTIVITY_COLUMNS,
           "Profile": ["Key", "Value"]}
TYPE_KEYWORDS = [
    ("Scholarship", r"scholarship|bursary"), ("Exchange", r"exchange"),
    ("Startup Program", r"accelerator|incubator|startup program|start-up program"),
    ("Fellowship", r"fellowship|fellows program"), ("Internship", r"internship|intern\b|summer analyst"),
    ("Research", r"research|research assistant|phd|postdoc"),
    ("Competition", r"competition|hackathon|challenge|contest"),
    ("Conference", r"conference|summit|symposium"), ("Leadership", r"leadership|leaders|ambassador"),
]
TERMINAL = {"Applied", "Interview", "Offer", "Rejected", "Withdrawn", "Skip", "Closed"}


def canonical_url(url: str) -> str:
    """Preserve case-sensitive paths and job identifiers; strip only known trackers."""
    p = urlsplit(url.strip())
    if p.scheme.lower() not in {"http", "https"} or not p.hostname or p.username:
        raise ValueError("Opportunity URL must be an absolute HTTP(S) URL without credentials")
    trackers = {"fbclid", "gclid", "mc_cid", "mc_eid"}
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in trackers]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(sorted(query)), ""))


def identity(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:24]


def deadline_candidate(text: str) -> str:
    """Only accept explicit full dates after deadline language; keep expired dates."""
    results = set()
    for m in re.finditer(r"(?:deadline|apply by|applications close|closing date)\s*[:\-–]?\s*([^\n.;]{1,65})", text, re.I):
        fragment = m[1].replace(",", "")
        for pattern, formats in [
            (r"\b\d{4}-\d{2}-\d{2}\b", ("%Y-%m-%d",)),
            (r"\b[A-Za-z]+ \d{1,2} \d{4}\b", ("%B %d %Y", "%b %d %Y")),
            (r"\b\d{1,2} [A-Za-z]+ \d{4}\b", ("%d %B %Y", "%d %b %Y")),
        ]:
            found = re.search(pattern, fragment)
            if found:
                for fmt in formats:
                    try:
                        results.add(datetime.strptime(found[0], fmt).date().isoformat())
                        break
                    except ValueError:
                        continue
    return results.pop() if len(results) == 1 else ""


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def positive_hours(value: object, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.inf
    return result if math.isfinite(result) and result > 0 else math.inf


def evaluate(record: dict, profile: dict, today: date) -> dict:
    """Refresh time-dependent fields without overwriting human decisions."""
    record = dict(record)
    expiry = parse_date(record.get("Verified deadline") or record.get("Deadline candidate"))
    seen = parse_date(record["Last seen"][:10])
    status = record.get("Status", "")
    if status == "Closed":
        availability = "Closed by user"
    elif expiry and expiry < today:
        availability = "Deadline passed"
    elif seen and (today - seen).days > profile["stale_after_days"]:
        availability = "Stale — recheck"
    else:
        availability = "Needs verification"
    record["Availability"] = availability
    text = (record["Title"] + " " + record["Source excerpt"]).lower()
    matches = [s for s in profile["interests"] if s.lower() in text]
    fit = min(100, len(matches) * 35)
    value = 70 if record["Category"] in {"Research", "Internship", "Fellowship"} else 50
    hours = positive_hours(record.get("Hours override"), float(record["Estimated hours"]))
    urgency = 30 if not expiry else max(0, min(100, 100 - max(0, (expiry - today).days - 3) * 3))
    effort = max(0, 100 - hours * 20)
    w = profile["weights"]
    total = round(w["fit"] * fit + w["value"] * value + w["urgency"] * urgency + w["effort"] * effort, 1)
    record["Priority score"] = total
    record["Matched interests"] = ", ".join(matches)
    record["Ranking reason"] = f"Heuristic, not acceptance probability or financial ROI: fit={fit}; category value={value}; urgency={urgency}; effort={effort}. Weights={w}"
    blocked = availability in {"Deadline passed", "Closed by user"} or record.get("Eligibility") == "Ineligible" or status in TERMINAL
    official_link = record.get("Verified application URL", "")
    try:
        if official_link:
            canonical_url(official_link)
    except ValueError:
        official_link = ""
    rolling = str(record.get("Verified deadline", "")).strip().lower() == "rolling"
    ready = (record.get("Eligibility") == "Eligible" and
             (bool(parse_date(record.get("Verified deadline"))) or rolling) and
             availability != "Stale — recheck" and bool(official_link) and
             not record.get("Possible duplicate") and math.isfinite(hours))
    record["Next action"] = "No application action" if blocked else (
        "Review draft and apply" if ready else "Verify eligibility, deadline, official link and any duplicate flag")
    record["Application URL"] = official_link or record["Source URL"]
    return record


def reconcile(candidates: list[dict], existing: list[dict], profile: dict, now: str) -> tuple[list[dict], int]:
    """Use destination state, never a premature seen marker. Flag uncertain duplicates."""
    records = {r["ID"]: dict(r) for r in existing}
    if len(records) != len(existing):
        raise ValueError("Duplicate IDs in Opportunities; repair before syncing")
    today = date.fromisoformat(now[:10])
    new_count = 0
    for candidate in candidates:
        url = canonical_url(candidate["url"])
        key = identity(url)
        if key not in records and new_count >= profile["max_new_per_run"]:
            continue
        old = records.get(key, {})
        title, text = candidate["title"], candidate.get("raw_text", "")
        category = next((label for label, pattern in TYPE_KEYWORDS if re.search(pattern, title, re.I)), "Other")
        if category == "Other":
            category = next((label for label, pattern in TYPE_KEYWORDS if re.search(pattern, text, re.I)), "Other")
        if not old:
            new_count += 1
        duplicate = old.get("Possible duplicate", "") if old else next((
            r["ID"] for r in records.values() if r["ID"] != key and
            SequenceMatcher(None, title.lower(), r["Title"].lower()).ratio() >= 0.92), "")
        records[key] = {**old, "ID": key, "Title": title[:500], "Category": category,
                        "Source URL": url, "Source": candidate["source_name"], "Source excerpt": text[:5000],
                        "Deadline candidate": deadline_candidate(text), "Last seen": candidate.get("observed_at", now),
                        "Last refreshed": now, "Estimated hours": profile["effort_hours"][category],
                        "Possible duplicate": old.get("Possible duplicate", duplicate),
                        "Source authority": "Official source" if candidate.get("primary") else "Aggregator — verify official listing"}
    return [evaluate(r, profile, today) for r in records.values()], new_count


def build_queues(records: list[dict], profile: dict, today: date, spent_hours: float = 0) -> tuple[list[dict], list[dict]]:
    """Strict weekly budget; unknown eligibility is never promoted to ready-to-apply."""
    from datetime import timedelta
    ready, verify = [], []
    remaining = max(0, float(profile["weekly_hours"]) - spent_hours)
    week = (today - timedelta(days=today.weekday())).isoformat()
    for record in sorted(records, key=lambda r: (-float(r["Priority score"]), r["ID"])):
        if record["Next action"] == "No application action":
            continue
        hours = positive_hours(record.get("Hours override"), float(record["Estimated hours"]))
        row = {"ID": record["ID"], "Priority": record["Priority score"], "Opportunity": record["Title"],
               "Action": record["Next action"], "Deadline": record.get("Verified deadline") or record["Deadline candidate"] or "Unknown",
               "Hours": hours if math.isfinite(hours) else "Fix hours override", "Apply / review URL": record["Application URL"],
               "Pack ID": record["ID"], "Week starting": week}
        if record["Next action"] != "Review draft and apply":
            verify.append(row)
        elif hours <= remaining:
            ready.append(row)
            remaining -= hours
    return ready, verify
