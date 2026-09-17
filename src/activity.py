"""Track observed status transitions without resetting the weekly work budget daily."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from src.personal_engine import positive_hours


def week_start(today: date) -> str:
    return (today - timedelta(days=today.weekday())).isoformat()


def transitions(records: list[dict], history: list[dict], now: str) -> list[dict]:
    """Baseline preexisting statuses; charge only an observed change to Applied."""
    latest: dict[str, dict] = {}
    for event in sorted(history, key=lambda row: (row["Observed at"], row["ID"])):
        latest[event["Opportunity ID"]] = event
    changes = []
    for record in records:
        status = record.get("Status") or "New"
        previous = latest.get(record["ID"])
        if previous and previous["Status"] == status:
            continue
        cost = positive_hours(record.get("Hours override"), float(record["Estimated hours"]))
        if cost == float("inf"):
            cost = float(record["Estimated hours"])
        token = f"{record['ID']}|{previous['ID'] if previous else 'baseline'}|{status}|{now}"
        changes.append({"ID": hashlib.sha256(token.encode()).hexdigest()[:24],
                        "Opportunity ID": record["ID"], "Observed at": now, "Status": status,
                        "Estimated hours": cost, "Charge hours": cost if previous and status == "Applied" else 0,
                        "Week starting": week_start(date.fromisoformat(now[:10]))})
    return changes


def hours_used(history: list[dict], today: date) -> float:
    """Count each opportunity at most once per week, even after status toggles."""
    charged: dict[str, float] = {}
    for event in history:
        if event["Week starting"] == week_start(today):
            key = event["Opportunity ID"]
            charged[key] = max(charged.get(key, 0), float(event.get("Charge hours", 0)))
    return sum(charged.values())
