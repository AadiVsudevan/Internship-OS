"""Behavioral tests for personal Sheets pipeline, using an in-memory API boundary."""
import copy
import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from run_personal import execute, load_config, sheet_profile
from src.personal_engine import (AUTO_COLUMNS, PACK_COLUMNS, SCHEMAS, build_queues,
                                 canonical_url, deadline_candidate, reconcile)
from src.preparation import build_pack
from src.activity import transitions, hours_used
from src.sheets_store import SheetsClient, SheetsStore, parse_rows

NOW = "2026-09-16T10:00:00+05:30"


@pytest.fixture
def profile():
    config = json.loads((Path(__file__).parents[1] / "config/personal.json").read_text())
    return {**config, "name": "Test Applicant", "education": "I am an undergraduate at Example University.",
            "interests": ["economics", "finance", "research", "policy"],
            "evidence": [{"id": "test-project", "text": "I built an Opportunity OS experiment.",
                          "tags": ["research"], "source": "Synthetic test fixture"}]}


def candidate(url="https://example.org/Role?id=ABC", title="Economics research internship"):
    return {"url": url, "title": title, "raw_text": "Finance research. Deadline: October 12, 2026.", "source_name": "Test"}


class MemoryClient:
    """Interpret updateCells as Google does, without replacing unspecified columns."""
    def __init__(self):
        self.data = {k: [v[:]] for k, v in SCHEMAS.items()}
        self.ids = {k: i for i, k in enumerate(SCHEMAS)}
        self.fail_tab = None

    def metadata(self):
        return {k: {"sheetId": v, "gridProperties": {"rowCount": 1000}} for k, v in self.ids.items()}

    def read(self, title):
        return copy.deepcopy(self.data[title])

    def batch(self, requests):
        updated = copy.deepcopy(self.data)
        for req in requests:
            if "updateCells" not in req:
                continue
            change = req["updateCells"]
            title = next(k for k, v in self.ids.items() if v == change["start"]["sheetId"])
            if title == self.fail_tab:
                self.fail_tab = None
                raise RuntimeError("simulated write failure")
            for i, row in enumerate(change["rows"], change["start"]["rowIndex"]):
                while len(updated[title]) <= i:
                    updated[title].append([])
                vals = [next(iter(c["userEnteredValue"].values())) for c in row["values"]]
                updated[title][i][:len(vals)] = vals
        self.data = updated


def health():
    return [{"Source": "Test", "Checked at": NOW, "Status": "OK", "Items": 1, "Detail": "Fixture"}]


def test_url_preserves_case_and_job_ids():
    assert canonical_url("https://EXAMPLE.org/Role?id=AbC&utm_source=x") == "https://example.org/Role?id=AbC"
    assert canonical_url("https://x.org/a?id=1") != canonical_url("https://x.org/a?id=2")
    with pytest.raises(ValueError):
        canonical_url("javascript:alert(1)")


@pytest.mark.parametrize("text,expected", [
    ("Deadline: October 12, 2026", "2026-10-12"),
    ("Deadline: 12 October 2026", "2026-10-12"),
    ("Deadline: 2025-01-01", "2025-01-01"),
    ("Programme begins October 12, 2026", ""),
    ("Deadline: October 12", ""),
    ("Deadline: 2026-02-30", ""),
    ("Deadline: October 12, 2026. Deadline: October 13, 2026.", ""),
])
def test_deadlines_are_explicit_and_conservative(text, expected):
    assert deadline_candidate(text) == expected


def test_cap_does_not_lose_unsynced_candidates(profile):
    profile["max_new_per_run"] = 1
    candidates = [candidate(), candidate("https://x.org/2", "Leadership programme")]
    first, added = reconcile(candidates, [], profile, NOW)
    assert added == 1
    second, added = reconcile(candidates, first, profile, NOW)
    assert added == 1 and len(second) == 2


def test_fuzzy_duplicates_are_flagged_not_deleted(profile):
    records, _ = reconcile([candidate(), candidate("https://x.org/2")], [], profile, NOW)
    assert len(records) == 2 and records[1]["Possible duplicate"] == records[0]["ID"]


def test_unknown_eligibility_never_ready(profile):
    records, _ = reconcile([candidate()], [], profile, NOW)
    ready, verify = build_queues(records, profile, date(2026, 9, 16))
    assert not ready and len(verify) == 1


def test_ready_queue_obeys_budget_and_terminal_status(profile):
    records, _ = reconcile([candidate(), candidate("https://x.org/2", "Policy fellowship")], [], profile, NOW)
    for r in records:
        r.update({"Eligibility": "Eligible", "Verified deadline": "2026-10-12", "Verified application URL": "https://x.org/apply", "Hours override": 2})
    records, _ = reconcile([], records, profile, NOW)
    ready, _ = build_queues(records, profile, date(2026, 9, 16))
    assert len(ready) == 1 and sum(r["Hours"] for r in ready) <= 3
    records[0]["Status"] = "Applied"
    records[1]["Hours override"] = 4
    records, _ = reconcile([], records, profile, NOW)
    ready, _ = build_queues(records, profile, date(2026, 9, 16))
    assert ready == []


def test_expiry_staleness_and_invalid_override(profile):
    records, _ = reconcile([candidate()], [], profile, NOW)
    records[0]["Verified deadline"] = "2026-09-01"
    result, _ = reconcile([], records, profile, NOW)
    assert result[0]["Next action"] == "No application action"
    records[0].update({"Verified deadline": "2026-12-01", "Eligibility": "Eligible", "Verified application URL": "https://x.org", "Hours override": "nan"})
    result, _ = reconcile([], records, profile, "2026-10-16T10:00:00+05:30")
    assert result[0]["Availability"] == "Stale — recheck"
    assert not build_queues(result, profile, date(2026, 10, 16))[0]


def test_pack_is_grounded_and_labels_unknown_questions(profile):
    records, _ = reconcile([candidate()], [], profile, NOW)
    pack = build_pack(records[0], profile)
    assert "not the official application form" in pack["Draft application"]
    assert "Opportunity OS experiment" in pack["Draft application"]
    assert records[0]["Title"] in pack["Interview prep"]
    assert "not confirmed interview questions" in pack["Interview prep"]


def test_sync_preserves_human_answers_and_status_after_sort(profile):
    client = MemoryClient()
    store = SheetsStore(client)
    execute(store, [candidate(), candidate("https://x.org/2", "Leadership programme")], health(), profile, NOW)
    # Populate user-owned cells and reorder the complete rows, as a sheet sort does.
    row = client.data["Opportunities"][1]
    row.extend(["Applied", "Eligible", "2026-10-12", 1, "Keep my note", "https://x.org/apply"])
    key = row[0]
    client.data["Opportunities"][1:3] = client.data["Opportunities"][1:3][::-1]
    client.data["Application Packs"][1].extend(["My rewritten answer", "My interview notes", "Actual question"])
    execute(store, [candidate()], health(), profile, NOW)
    target = next(r for r in store.load("Opportunities") if r["ID"] == key)
    assert target["Status"] == "Applied" and target["Notes"] == "Keep my note"
    assert store.load("Application Packs")[0]["Edited answers"] == "My rewritten answer"
    assert len(store.load("Opportunities")) == 2


def test_partial_write_recovers_packs_on_rerun(profile):
    client = MemoryClient()
    store = SheetsStore(client)
    client.fail_tab = "Application Packs"
    with pytest.raises(RuntimeError):
        execute(store, [candidate()], health(), profile, NOW)
    assert len(store.load("Opportunities")) == 1
    execute(store, [candidate()], health(), profile, NOW)
    assert len(store.load("Opportunities")) == len(store.load("Application Packs")) == 1


def test_failed_opportunity_write_is_retryable(profile):
    client = MemoryClient()
    store = SheetsStore(client)
    client.fail_tab = "Opportunities"
    with pytest.raises(RuntimeError):
        execute(store, [candidate()], health(), profile, NOW)
    assert not store.load("Opportunities")
    execute(store, [candidate()], health(), profile, NOW)
    assert len(store.load("Opportunities")) == 1


def test_empty_queue_clears_previous_rows():
    store = SheetsStore(MemoryClient())
    store.replace("Weekly Queue", [{"ID": "old", "Opportunity": "Old item"}])
    store.replace("Weekly Queue", [])
    assert store.load("Weekly Queue") == []


def test_formula_injection_is_literal():
    client = MemoryClient()
    captured = []
    client.batch = lambda payload: captured.extend(payload)
    SheetsStore(client).upsert("Opportunities", [{"ID": "abc", "Title": '=IMPORTXML("https://evil")'}], AUTO_COLUMNS)
    cell = captured[0]["updateCells"]["rows"][0]["values"][1]
    assert "stringValue" in cell["userEnteredValue"]


def test_schema_or_duplicate_id_fails_closed():
    with pytest.raises(ValueError):
        parse_rows("Opportunities", [["wrong header"]])
    with pytest.raises(ValueError):
        parse_rows("Opportunities", [SCHEMAS["Opportunities"], ["same"], ["same"]])


def test_transient_http_retries_but_auth_error_does_not():
    session = Mock()
    response = Mock(status_code=200)
    response.json.return_value = {"ok": True}
    session.request.side_effect = [requests.Timeout(), response]
    with patch("src.sheets_store.time.sleep"):
        assert SheetsClient("sheet", session).request("POST", ":batchUpdate", json={}) == {"ok": True}
    assert session.request.call_count == 2
    forbidden = Mock(status_code=403)
    forbidden.raise_for_status.side_effect = requests.HTTPError("Forbidden")
    session.request.side_effect = [forbidden]
    session.request.reset_mock()
    with pytest.raises(requests.HTTPError):
        SheetsClient("sheet", session).request("GET")
    assert session.request.call_count == 1


def test_source_outage_is_degraded_without_losing_successes(profile):
    store = SheetsStore(MemoryClient())
    result = execute(store, [candidate()], health() + [{"Source": "Blocked", "Status": "FAILED"}], profile, NOW)
    assert result["audit"]["Result"] == "DEGRADED"
    assert len(store.load("Opportunities")) == 1


def test_backlog_survives_disappearing_feed_and_processing_cap(profile):
    profile["max_new_per_run"] = 1
    store = SheetsStore(MemoryClient())
    first = execute(store, [candidate(), candidate("https://x.org/later", "Leadership opportunity")], health(), profile, NOW)
    assert len(first["records"]) == 1
    assert len(store.load("Discovery Inbox")) == 2
    second = execute(store, [], health(), profile, "2026-09-17T10:00:00+05:30")
    assert len(second["records"]) == 2
    deferred = next(r for r in second["records"] if r["Title"] == "Leadership opportunity")
    assert deferred["Last seen"] == NOW


def test_applied_transitions_reduce_remaining_weekly_budget(profile):
    records, _ = reconcile([candidate(), candidate("https://x.org/other", "Finance fellowship")], [], profile, NOW)
    baseline = transitions(records, [], NOW)
    assert hours_used(baseline, date(2026, 9, 16)) == 0
    records[0]["Status"] = "Applied"
    events = transitions(records, baseline, "2026-09-17T10:00:00+05:30")
    assert len(events) == 1
    history = baseline + events
    assert hours_used(history, date(2026, 9, 17)) == 2
    assert not transitions(records, history, "2026-09-18T10:00:00+05:30")
    assert hours_used(history, date(2026, 9, 21)) == 0
    records[1].update({"Eligibility": "Eligible", "Verified deadline": "2026-10-12", "Verified application URL": "https://x.org/apply", "Hours override": 2})
    records, _ = reconcile([], records, profile, NOW)
    assert not build_queues(records, profile, date(2026, 9, 17), 2)[0]


def test_baseline_applied_is_not_assumed_to_be_new_work(profile):
    records, _ = reconcile([candidate()], [], profile, NOW)
    records[0]["Status"] = "Applied"
    assert hours_used(transitions(records, [], NOW), date(2026, 9, 16)) == 0


def test_status_toggles_charge_only_once_per_week(profile):
    records, _ = reconcile([candidate()], [], profile, NOW)
    history = transitions(records, [], NOW)
    for day, status in [(17, "Applied"), (18, "Drafting"), (19, "Applied")]:
        records[0]["Status"] = status
        history += transitions(records, history, f"2026-09-{day}T10:00:00+05:30")
    assert hours_used(history, date(2026, 9, 19)) == 2


def test_verified_rolling_deadline_can_be_queued(profile):
    records, _ = reconcile([candidate()], [], profile, NOW)
    records[0].update({"Eligibility": "Eligible", "Verified deadline": "Rolling", "Verified application URL": "https://x.org/apply"})
    records, _ = reconcile([], records, profile, NOW)
    ready, verify = build_queues(records, profile, date(2026, 9, 16))
    assert len(ready) == 1 and ready[0]["Deadline"] == "Rolling" and not verify


def test_invalid_verified_link_never_becomes_cta(profile):
    records, _ = reconcile([candidate()], [], profile, NOW)
    records[0].update({"Eligibility": "Eligible", "Verified deadline": "2026-10-12", "Verified application URL": "javascript:alert(1)"})
    records, _ = reconcile([], records, profile, NOW)
    assert records[0]["Application URL"].startswith("https://")
    assert not build_queues(records, profile, date(2026, 9, 16))[0]


def test_profile_requires_identity_from_private_input():
    with pytest.raises(ValueError, match="private Profile tab"):
        load_config({})


def test_sheet_profile_loads_only_private_profile_keys(profile):
    store = Mock()
    store.load.return_value = [{"Key": "name", "Value": "Test Applicant"},
                              {"Key": "education", "Value": "I am a student."},
                              {"Key": "interests", "Value": '["research"]'},
                              {"Key": "evidence", "Value": "[]"},
                              {"Key": "weekly_hours", "Value": "999"}]
    loaded = load_config(sheet_profile(store))
    assert loaded["name"] == "Test Applicant" and loaded["interests"] == ["research"]
    assert loaded["weekly_hours"] == profile["weekly_hours"]
