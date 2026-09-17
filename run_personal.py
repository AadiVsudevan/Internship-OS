"""Personal Opportunity OS entrypoint. Run --help for setup, sync and preview."""
from __future__ import annotations

import argparse
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.personal_engine import AUTO_COLUMNS, PACK_COLUMNS, INBOX_COLUMNS, ACTIVITY_COLUMNS, build_queues, reconcile, identity
from src.personal_views import ASSESSMENT_COLUMNS, assess, reviewed_records, snapshots
from src.activity import transitions, hours_used
from src.preparation import build_pack
from src.sheets_store import SheetsClient, SheetsStore

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"at": datetime.now(ZoneInfo("UTC")).isoformat(), "level": record.levelname,
                           "logger": record.name, "message": record.getMessage()})


def load_config(private_profile: dict) -> dict:
    profile = json.loads((ROOT / "config/personal.json").read_text())
    profile.update(private_profile)
    if not all(isinstance(profile.get(k), str) and profile[k].strip() for k in ["name", "education"]):
        raise ValueError("Complete name and education in the private Profile tab")
    if not isinstance(profile.get("interests"), list) or not profile["interests"]:
        raise ValueError("Profile interests must be a nonempty JSON list")
    if profile["weekly_hours"] <= 0 or profile["max_new_per_run"] <= 0:
        raise ValueError("Weekly hours and new-item limit must be positive")
    if abs(sum(profile["weights"].values()) - 1) > 1e-9 or any(v < 0 for v in profile["weights"].values()):
        raise ValueError("Ranking weights must be nonnegative and sum to one")
    return profile


def sheet_profile(store: SheetsStore) -> dict:
    """Load identity and evidence from the private Sheet, never public source code."""
    values = {r["Key"]: r.get("Value", "") for r in store.load("Profile")}
    for key in ["interests", "evidence"]:
        values[key] = json.loads(values.get(key) or "[]")
    return {k: v for k, v in values.items() if k in {"name", "education", "interests", "evidence"}}


def execute(store: SheetsStore, candidates: list[dict], health: list[dict], profile: dict, now: str) -> dict:
    """Durable stages recover through ID upserts; never commit pre-sync dedupe state."""
    run_id = str(uuid.uuid4())
    failures = sum(h["Status"] != "OK" for h in health)
    audit = {"Run ID": run_id, "At": now, "Result": "FAILED", "Discovered": len(candidates),
             "New": 0, "Updated": 0, "Source failures": failures, "Queue items": 0}
    try:
        # Persist every discovered candidate before the processing cap. A listing
        # can then leave its source feed without disappearing from our backlog.
        inbox = [{"ID": identity(c["url"]), "Title": c["title"], "Source URL": c["url"],
                  "Source": c["source_name"], "Source excerpt": c.get("raw_text", "")[:5000],
                  "Observed at": now, "Primary source": "yes" if c.get("primary") else "no"} for c in candidates]
        inbox = list({row["ID"]: row for row in inbox}.values())
        store.upsert("Discovery Inbox", inbox, INBOX_COLUMNS)
        old = store.load("Opportunities")
        known = {r["ID"] for r in old}
        pending = [{"title": r["Title"], "url": r["Source URL"], "source_name": r["Source"],
                    "raw_text": r["Source excerpt"], "observed_at": r["Observed at"],
                    "primary": r["Primary source"] == "yes"}
                   for r in store.load("Discovery Inbox") if r["ID"] not in known]
        records, added = reconcile(pending + candidates, old, profile, now)
        store.upsert("Opportunities", records, AUTO_COLUMNS)
        # Re-read user fields and stable IDs after committing discovered records.
        records, _ = reconcile([], store.load("Opportunities"), profile, now)
        packs = [build_pack(r, profile) for r in records]
        store.upsert("Application Packs", packs, PACK_COLUMNS)
        history = store.load("Application Activity")
        events = transitions(records, history, now)
        store.upsert("Application Activity", events, ACTIVITY_COLUMNS)
        spent = hours_used(history + events, datetime.fromisoformat(now).date())
        assessments = [assess(r, profile) for r in records]
        store.upsert("Personal Review", assessments, ASSESSMENT_COLUMNS)
        reviews = store.load("Personal Review")
        for title, rows in snapshots(assessments, reviews).items():
            store.replace(title, rows)
        queued = reviewed_records(records, assessments, reviews)
        ready, verify = build_queues(queued, profile, datetime.fromisoformat(now).date(), spent)
        store.replace("Weekly Queue", ready)
        store.replace("Verify First", verify)
        store.replace("Source Health", health)
        audit.update({"Result": "DEGRADED" if failures else "OK", "New": added,
                      "Updated": len(records) - added, "Queue items": len(ready)})
        store.audit(audit)
        return {"audit": audit, "records": records, "ready": ready, "verify": verify, "spent_hours": spent}
    except Exception:
        try:
            store.audit(audit)
        except Exception:
            logger.error("audit_write_failed run_id=%s", run_id)
        raise


def main() -> int:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "sync", "preview", "bootstrap", "doctor"])
    parser.add_argument("--input", type=Path, help="Read candidate JSON instead of live sources (preview only)")
    parser.add_argument("--profile", type=Path, help="Private profile JSON path (preview only; never committed)")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/preview.json")
    args = parser.parse_args()
    if args.input and args.command != "preview":
        parser.error("--input is restricted to preview; fixture data cannot be synced")
    if args.profile and args.command != "preview":
        parser.error("--profile is restricted to preview; live runs read the private Profile tab")
    store = None
    # Fail on missing credentials before spending time fetching external sources.
    if args.command != "preview":
        store = SheetsStore(SheetsClient(os.environ.get("GOOGLE_SHEET_ID", "")))
    if args.command in {"setup", "bootstrap"}:
        store.setup()
        logger.info("sheet_schema_ready")
        if args.command == "setup":
            return 0
    if args.command == "doctor":
        from src.personal_engine import SCHEMAS
        meta = store.client.metadata()
        missing = set(SCHEMAS) - set(meta)
        if missing:
            raise ValueError("Missing tabs; run bootstrap: " + ", ".join(sorted(missing)))
        for title in SCHEMAS:
            store.load(title)
        logger.info("doctor_ok tabs=%d schema_and_read_access_verified=true", len(SCHEMAS))
        load_config(sheet_profile(store))
        return 0
    if args.command == "preview":
        if not args.profile:
            parser.error("preview requires --profile pointing to a private local JSON file")
        profile = load_config(json.loads(args.profile.read_text()))
    else:
        profile = load_config(sheet_profile(store))
    now = datetime.now(ZoneInfo(profile["timezone"])).isoformat(timespec="seconds")
    if args.input:
        candidates = json.loads(args.input.read_text())
        health = [{"Source": "Local preview input", "Checked at": now, "Status": "OK", "Items": len(candidates), "Detail": "Preview only; never synced"}]
    else:
        from src.personal_sources import gather
        sources = json.loads((ROOT / "config/sheets-sources.json").read_text())
        candidates, health = gather(sources, now)
    if args.command == "preview":
        records, _ = reconcile(candidates, [], profile, now)
        ready, verify = build_queues(records, profile, datetime.fromisoformat(now).date())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"mode": "PREVIEW — not deployed", "opportunities": records,
            "packs": [build_pack(r, profile) for r in records], "weekly_queue": ready, "verify_first": verify,
            "source_health": health}, indent=2, ensure_ascii=False))
        logger.info("preview_saved records=%s failed_sources=%s", len(records), sum(h["Status"] != "OK" for h in health))
        return 2 if any(h["Status"] != "OK" for h in health) else 0
    result = execute(store, candidates, health, profile, now)
    logger.info("run_finished %s", json.dumps(result["audit"]))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as out:
            out.write(f"Opportunity OS: {result['audit']['Result']}. {len(result['ready'])} applications; {len(result['verify'])} need verification. "
                      f"Estimated time already applied this week: {result['spent_hours']:g}h.\n")
    # Visible failing check even for partial source outages; other sources still sync.
    return 2 if result["audit"]["Source failures"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logger.error("run_failed error=%s detail=%s", type(exc).__name__, str(exc)[:250])
        raise SystemExit(1)
