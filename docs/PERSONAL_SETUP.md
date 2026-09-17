# Personal Opportunity OS: deployment and daily use

## What is implemented

The personal backend discovers RSS/Atom listings and configured HTML listings, identifies opportunities by canonical URL, ranks them with configurable rules, writes Google Sheets, and creates an application draft and interview guide for each record. It requires no paid model or Notion account at runtime.

The existing Notion implementation remains in the project. Its three workflows are now manual-only so enabling the personal workflow does not run two competing systems. See `LEGACY_NOTION.md` for the original instructions. The personal backend deliberately does not use `data/seen.json` or GitHub listing snapshots: those legacy mechanisms could suppress records before a successful write.

Only the public repository is named in `config/deployment.json`; the destination Sheet ID is a runtime secret. Runtime activation requires Google service-account credentials and Sheet sharing. No Notion records are migrated by setup; the supplied ZIP contained code, not exported opportunity rows.

## One-time deployment

1. Use the supplied repository `AadiVsudevan/Internship-OS`. The engine workflow runs on its `main` branch. Generated previews, environment files and credential JSON files are excluded from Git.
2. Set the destination Sheet ID in Actions secret `GOOGLE_SHEET_ID`. Existing unrelated tabs are left intact.
3. In Google Cloud, enable the Google Sheets API and create a service account. No project-wide IAM role or domain-wide delegation is needed for this application. Share only the destination Sheet with the service account's email as Editor. Create a JSON key for that account.
4. Add repository Actions secret `GOOGLE_SERVICE_ACCOUNT_JSON` (the complete JSON key). Also set `GOOGLE_SHEET_ID` to your private destination. Do not paste private keys into chat, source files or the Sheet.
5. Open Actions → **Personal Opportunity OS** → Run workflow → choose `bootstrap`. This initializes missing/blank project tabs and syncs. Existing nonempty tabs must have the exact schema; otherwise setup stops without rewriting them. Engine changes pushed to main also bootstrap after tests pass.
6. Run `doctor` to validate read access and all tab schemas. Inspect **Source Health**, **Run History**, **Verify First**, and **Application Packs**. Confirm success in Actions before treating the system as live.
7. Fill the private Profile tab with keys `name`, `education`, `interests`, and `evidence`. The last two are JSON lists. Each evidence item has `id`, `text`, `tags` (a list) and `source`. Edit this tab as your degree, evidence and interests change; adjust the weekly budget in `config/personal.json`. The initial three-hour application budget is an editable default, not a confirmed availability claim.

The workflow is scheduled daily at 00:47 UTC (06:17 IST). Each run refreshes the current week's queue, including a fresh Monday queue. The queue is an actionable view in Sheets, not an email notification. GitHub sends failure notifications according to your notification settings; enable notifications for failed workflows.

ChatGPT's connected Google account is separate from the service account that unattended GitHub jobs use. Connecting Drive here does not automatically authorize GitHub Actions.

## Tabs and ownership

| Tab | Purpose | Editable fields |
| --- | --- | --- |
| Opportunities | Discovery records, priority explanations, availability and next action | Status, Eligibility, Verified deadline, Hours override, Notes, Verified application URL (S:X) |
| Application Packs | Generated draft form answers and interview guide for every record | Edited answers, Interview notes, Official questions (I:K) |
| Weekly Queue | Eligible, verified applications that fit the time budget | Generated; edit the source record instead |
| Verify First | Missing eligibility, deadline, official link, stale records or duplicate flags | Generated; resolve fields in Opportunities |
| Source Health | Per-source success or failure and counts | Generated |
| Run History | Run result, counts and failure audit | Generated |
| Discovery Inbox | Persistent backlog of discovered listings | Generated |
| Application Activity | Observed status transitions and weekly effort accounting | Generated |
| Profile | Name, education, interests and evidence (private) | Value column |

Application Activity charges estimated effort when a tracked status changes to Applied, once per opportunity per week. Baseline preexisting Applied entries are not treated as new work. These are observed transitions, not exact submission timestamps or a time tracker. Counts reset by Monday in the configured timezone.

IDs join an opportunity, its pack and its queue entry. Filter a tab by ID to locate the matching record. Generated columns have warning protection; human columns are tinted light blue. Open long answers in the formula bar or expand the row to read/edit them.

The URL in **Apply / review URL** is the CTA. Before an official application URL is confirmed, it opens the source listing. These are review/apply links; nothing submits an application or sends outreach automatically.

## Application workflow

1. Review a candidate in **Verify First** and open its source. Check the official programme's eligibility, deadline/timezone, cost, funding and application link.
2. Set Eligibility to `Eligible` or `Ineligible`. Enter a verified deadline as ISO text `YYYY-MM-DD`, and the official URL. For a genuinely rolling opportunity, enter `Rolling` after checking the official page. Do not invent a date. Missing or ambiguous deadlines remain in Verify First.
3. Set Status to `To Apply` or `Drafting`. Adjust Hours override if the estimate is wrong. On the next sync, verified candidates are prioritized within the weekly budget. A task larger than the entire budget is not forced into the queue; increase the budget or estimate a real, smaller application step.
4. Read its **Application Packs** row. Generated answers are first drafts based on the profile, not submission-ready forms. Paste the actual questions into **Official questions**, write final answers in **Edited answers**, and store your rehearsal notes in **Interview notes**. The current deterministic generator does not answer newly pasted official questions automatically.
5. Mark `Applied` after you submit. Applied, Interview, Offer, Rejected, Withdrawn, Skip and Closed records are excluded from the application queue while their preparation packs remain available.

The application draft includes an introduction, motivation, a real evidence example and document/availability prompts. Interview guides include category-specific practice, a topic exercise, evidence preparation and a question to ask the interviewer. They do not claim knowledge of an employer's actual interview questions. Education and project evidence come only from the private Profile tab; grades, citizenship, graduation year, language proficiency, accomplishments and work authorisation are not invented.

## Reliability and limits

- Sheets is the source of truth. Deduplication reads its existing IDs every run. Tracking parameters are removed while case-sensitive URL paths and job IDs remain intact.
- Similar titles at different URLs are flagged, not silently deleted. A flagged item needs review; clear a false-positive flag in the generated field after inspection (existing values are retained). Separate years/roles are not automatically merged.
- Source failures are isolated. Healthy sources still sync; the job exits nonzero for any failed enabled source. Empty/unparseable feeds are failures, not healthy zero-opportunity runs.
- A failed save leaves no premature “seen” state. Each source is read again on the next run. The Discovery Inbox persists candidates before the cap, so deferred candidates survive disappearing feed items after a successful inbox write.
- Machine-only updates preserve human columns and look up positions by stable ID immediately before writing. One GitHub concurrency group prevents overlapping workflow writers. Use filter views; do not sort, insert or delete rows during a running sync. Sheets cannot provide transactional row locking against simultaneous manual edits.
- HTTP retries cover throttling, transient server failures and transport errors. Fixed-position writes are safe to replay after a lost response. Larger upserts use bounded batches; a run can partially commit and is recovered by rerunning.
- A queue is a dated snapshot refreshed daily, not a live formula. Re-run `sync` after manual edits if an immediate queue refresh is needed.
- Dates are only candidates until verified. The parser requires an explicit full year and deadline language. Past dates remain past; unrelated event dates are not promoted to deadlines. Missing records become stale rather than automatically closed.
- Scores are explainable heuristics, not measured financial ROI or acceptance probabilities. Eligibility is a separate gate. This starter source set is broad, not exhaustive; global discovery does not imply worldwide eligibility or coverage of every category every week.
- The supplied source configuration uses feeds verified by this runtime. Sources may change or block GitHub runners; the first deployed live run remains a required gate. Additional official university/organisation pages can use the existing configurable HTML adapter.
- GitHub schedules can be delayed or dropped. Public-repository schedules can be disabled after inactivity. This workflow is not a service-level guarantee or an independent heartbeat monitor. Check Run History if a refresh is missing; an external missed-run alert is not deployed.
- Daily private-repository runs consume the account's included Actions minutes. Keep paid usage disabled and check the account allowance; zero cost is a budget configuration, not a four-year pricing guarantee.
- No destructive archive/purge is performed. Review long-term Sheet size and back up personal answers periodically. Existing Notion history remains the migration source until a read and row-count reconciliation succeed.

## Local commands

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-sheets.txt
python run_personal.py preview --profile /path/to/private-profile.json
# After supplying GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID securely:
python run_personal.py bootstrap
python run_personal.py doctor
python run_personal.py sync
```

The preview writes `outputs/preview.json` and never calls Google. `--input` accepts a local candidate JSON list only for previews, preventing test fixtures from entering the live database.

Run tests with `pip install -r requirements.txt -r requirements-sheets.txt` followed by `python -m pytest -q`. Unit and simulated integration tests do not need credentials. A native Sheets readback and a live Notion migration cannot be verified without access.

## References used for deployment behavior

- [Google Sheets API quotas, atomic requests and backoff](https://developers.google.com/workspace/sheets/api/limits)
- [Google service-account authentication](https://developers.google.com/identity/protocols/oauth2/service-account)
- [GitHub scheduled workflow behavior](https://docs.github.com/actions/using-workflows/events-that-trigger-workflows#schedule)
