"""CV-grounded assessments and human-reviewed category snapshots.

Scores are transparent relevance heuristics, never predicted admission chances.
"""
from __future__ import annotations
import re
from src.geography import in_scope

ASSESSMENT_COLUMNS = ["ID", "Opportunity", "Category", "CV fit", "Acceptance probability",
    "CV evidence", "Stage check", "Vetting checklist", "Priority", "Next action", "Source URL"]
REVIEW_COLUMNS = ASSESSMENT_COLUMNS + ["My decision", "My notes"]
VIEW_CATEGORIES = {"Internships": {"Internship"}, "Fellowships": {"Fellowship"},
    "Scholarships": {"Scholarship"}, "Volunteering": {"Volunteering"},
    "Other Opportunities": {"Research", "Competition", "Conference", "Leadership", "Exchange", "Startup Program", "Other"}}


def assess(record: dict, profile: dict) -> dict:
    """Expose evidence and uncertainty; keywords alone cannot establish eligibility."""
    text = (record["Title"] + " " + record.get("Source excerpt", "")).lower()
    evidence = [e for e in profile.get("evidence", []) if any(
        re.search(r"\b" + re.escape(t.lower()) + r"\b", text) for t in e.get("tags", []) if t)]
    first_year = bool(re.search(r"first.year|year 1", profile.get("education", ""), re.I))
    mismatch = first_year and bool(re.search(
        r"(?:must|required|only|minimum|eligib\w*)[^.]{0,65}(?:final.year|penultimate|second.year|third.year|master.s|phd|doctorate|bachelor.s degree)|(?:final.year|penultimate.year) (?:students|undergraduates)|postdoctoral", text))
    mismatch = mismatch or (first_year and bool(re.search(r"\b(senior|director|manager|postdoc|policy fellow)\b", record["Title"], re.I)))
    stage = "Later-stage requirement detected — check official eligibility" if mismatch else "First-year eligibility not established; verify official requirements"
    if not mismatch and re.search(r"undergraduate|first.year|open to all|volunteer", text):
        stage = "Potentially accessible — verify first-year eligibility and role requirements"
    if re.search(r"military (?:family|dependent)|bipoc|indigenous|african creatives|u\.s\. citizens", record["Title"], re.I):
        stage = "Restricted eligibility — qualifying background not established by CV"
    if record.get("Eligibility") == "Eligible":
        stage = "Eligibility confirmed by user"
    if record.get("Eligibility") == "Ineligible":
        stage = "Ineligible (user verified)"
    blocked = record.get("Next action") == "No application action" or (mismatch and record.get("Eligibility") != "Eligible")
    fit = "Not suitable now" if blocked else ("Strong evidence match" if len(evidence) >= 2 else "Some evidence match" if evidence else "Stretch / evidence missing")
    checks = "Confirm first-year entry, age, citizenship, location, cost/funding, current intake, workload and a concrete deliverable/mentor."
    if record["Category"] == "Scholarship":
        checks += " Check income, marks, institution/course coverage and whether existing students may apply."
    return {"_in_scope": in_scope(record, profile), "ID": record["ID"], "Opportunity": record["Title"], "Category": record["Category"],
        "CV fit": fit, "Acceptance probability": "Unknown — no calibrated applicant/outcome data",
        "CV evidence": "; ".join(e["id"] + ": " + e["text"] for e in evidence[:3]) or "No matching experience evidenced in CV",
        "Stage check": stage, "Vetting checklist": checks,
        "Priority": 0 if blocked else round(float(record["Priority score"]) + min(20, len(evidence)*5), 1),
        "Next action": "No application action" if blocked else record["Next action"],
        "Source URL": record.get("Application URL") or record["Source URL"]}


def reviewed_records(records: list[dict], assessments: list[dict], reviews: list[dict]) -> list[dict]:
    """Personal approval is additional to official eligibility/deadline checks."""
    decisions = {r["ID"]: r.get("My decision", "") for r in reviews}
    checks = {r["ID"]: r for r in assessments}
    result = []
    for original in records:
        r = dict(original)
        decision = decisions.get(r["ID"], "")
        a = checks[r["ID"]]
        r["Priority score"] = a["Priority"]
        if a["Next action"] == "No application action" or decision in {"Hold", "Reject"}:
            r["Next action"] = "No application action"
        elif decision != "Approve":
            r["Next action"] = "Complete Personal Review; then verify official eligibility and deadline"
        result.append(r)
    return result


def snapshots(assessments: list[dict], reviews: list[dict]) -> dict[str, list[dict]]:
    """Keep all records in category tabs; best opportunities exclude holds and rejects."""
    decisions = {r["ID"]: r for r in reviews}
    rows = [{**a, "My decision": decisions.get(a["ID"], {}).get("My decision", ""),
             "My notes": decisions.get(a["ID"], {}).get("My notes", "")} for a in assessments if a.get("_in_scope", True)]
    rows.sort(key=lambda r: (-r["Priority"], r["ID"]))
    out = {name: [r for r in rows if r["Category"] in categories] for name, categories in VIEW_CATEGORIES.items()}
    out["Best Opportunities"] = [r for r in rows if r["Next action"] != "No application action"
        and r["My decision"] not in {"Hold", "Reject"}
        and (r["Stage check"].startswith("Potentially accessible") or r["Stage check"] == "Eligibility confirmed by user")
        and r["CV fit"] in {"Strong evidence match", "Some evidence match"}][:10]
    return out
