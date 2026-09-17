# Opportunity OS

A personal career-opportunity engine for Aadi: discovery, deduplication, explainable ranking, Google Sheets tracking, a weekly application queue, draft answers and interview preparation. No paid model calls.

## Deployment

- Repository: https://github.com/AadiVsudevan/Internship-OS
- Destination: https://docs.google.com/spreadsheets/d/1D_Wwqr7aNE4scxVOIMHhwYq1A8YCR-mG--gpU3anBE4/edit
- Schedule: daily at 06:17 IST; the current-week queue refreshes each run.
- First run: Actions → Personal Opportunity OS → Run workflow → `bootstrap`.
- Required secret: `GOOGLE_SERVICE_ACCOUNT_JSON`. Share the destination Sheet with that account as Editor. The spreadsheet ID is already configured.

Pushing engine changes to main runs the tests, initializes missing tabs and syncs. Scheduled runs also test before writing. A missing credential fails clearly before discovery; source outages produce a failed check after saving healthy-source results.

See [setup and daily use](docs/PERSONAL_SETUP.md) for Google authentication, data ownership and operating limits.

## Components

| Component | Behavior |
| --- | --- |
| Discovery | RSS/Atom and configured HTML sources; bounded responses, retries and isolated source failures |
| Durable inbox | Stores discovered candidates before the processing cap so deferred entries survive disappearing feed items |
| Deduplication | Stable URL IDs; uncertain title matches flagged for review |
| Ranking | Configurable fit, category value, urgency and effort; reasons stored per record |
| Tracking | User-owned status, eligibility, deadline, effort and notes survive refreshes |
| Application packs | Evidence-based first drafts, category-specific interview guides and separate editable answers |
| Weekly queue | Only verified candidates; supports verified rolling applications; counts observed completed applications against the weekly budget |
| Operations | Source Health, Run History, Application Activity, regression-gated workflow and `doctor` command |

The source registry is a starter set, not exhaustive worldwide coverage. Drafts need review and actual application questions; the engine never submits applications. Notion history is not migrated by deployment.

## Commands

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-sheets.txt
python run_personal.py preview
# After configuring the Google service account:
python run_personal.py bootstrap
python run_personal.py doctor
python run_personal.py sync
```

`config/personal.json` controls interests, profile evidence, ranking weights and weekly hours. `config/sheets-sources.json` controls sources; `config/deployment.json` contains the supplied destinations. Secrets and generated previews are excluded from Git.

The legacy Notion pipeline is retained, with manual-only workflows and [its original guide](docs/LEGACY_NOTION.md).
