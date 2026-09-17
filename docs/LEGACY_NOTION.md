# Opportunity OS

A fully automated pipeline that discovers internships, fellowships, research roles,
competitions, scholarships, and summer programs (India + international), scores them
for career ROI, and pushes a ranked, deduplicated list straight into your Notion
workspace — with a Monday morning "here's what to apply to this week" queue.

**Cost: $0/month indefinitely.** No server to maintain, no Docker, no paid SaaS.

---

## 1. Architecture (single recommended stack, justified)

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │                    GITHUB ACTIONS (free scheduler)                   │
 │  ┌──────────────┐   ┌──────────────┐   ┌────────────────────────┐   │
 │  │ discover.yml │   │weekly_queue  │   │      archive.yml        │   │
 │  │  daily 06:00 │   │.yml  Mon AM  │   │      daily 07:30        │   │
 │  └──────┬───────┘   └──────┬───────┘   └────────────┬─────────────┘   │
 └─────────┼──────────────────┼────────────────────────┼────────────────┘
           ▼                  ▼                        ▼
    ┌─────────────┐    ┌──────────────┐         ┌──────────────┐
    │  main.py    │    │ weekly_queue │         │  archive.py  │
    └──────┬──────┘    │     .py      │         └──────┬───────┘
           │            └──────┬───────┘                │
  ┌────────┴─────────┐         │                         │
  ▼                  ▼         ▼                         ▼
INGEST          DEDUPE   CLASSIFY+RANK              NOTION API
(rss/scrape/   (seen.json  (Groq free LLM,         (Opportunities DB:
 github_list)   + fuzzy)   rule fallback)           create / query / update)
```

**Why this stack and not alternatives:**

| Layer | Choice | Why, over the obvious alternative |
|---|---|---|
| Scheduler | **GitHub Actions** | n8n/Zapier/Make need a hosted server or hit free-tier task caps; GH Actions gives unlimited free minutes on a public repo, or 2,000 free min/month on private — our daily run uses ~3-5 min, so even private stays free for years. |
| Discovery | **RSS + config-driven scraping + GitHub-list diffing** — never an LLM | The brief is right to separate "finding" from "understanding." LLMs hallucinate URLs and miss real-time updates; deterministic feeds/scrapers don't. |
| Classification/Ranking | **Groq free API** (Llama 3.1/3.3), not a *local* model | GH Actions runners are stateless — a local model re-downloads every run (slow, eats your free minutes). Groq's free tier (no card, ~30 req/min, ~14,400 req/day) comfortably covers the handful of new candidates/day this pipeline produces, with a deterministic rule-based scorer as automatic fallback so the pipeline **never hard-depends** on Groq staying free or up. |
| State/Dedupe | **JSON files committed back to the repo** | No database to host or pay for. Git history doubles as an audit log. |
| Sync target | **Notion API** (official `notion-client`) | You already live in Notion; no second dashboard to check. |
| Docker | **Skipped** | Adds zero value on GitHub Actions hosted runners — pure maintenance overhead for a 4-year personal tool. |

---

## 2. Repo structure

```
opportunity-os/
├── .github/workflows/
│   ├── discover.yml        # daily: ingest -> dedupe -> classify -> rank -> push to Notion
│   ├── weekly_queue.yml     # Monday: build the prioritized application queue
│   └── archive.yml         # daily: mark past-deadline items Expired
├── config/sources.yaml      # <- the only file you edit regularly
├── data/
│   ├── seen.json            # dedupe state (auto-committed by bot)
│   └── github_snapshots/    # last-seen text of any tracked GitHub lists
├── src/
│   ├── ingest/{rss,scrape,github_lists}.py
│   ├── dedupe.py
│   ├── classify.py          # Groq LLM + rule-based fallback
│   ├── rank.py               # transparent weighted scoring
│   ├── deadline.py           # regex + dateparser extraction
│   ├── notion_sync.py
│   ├── weekly_queue.py
│   └── archive.py
├── scripts/setup_notion.py  # one-time: creates the Notion DB with correct schema
├── main.py                   # daily pipeline entrypoint
└── requirements.txt
```

---

## 3. Deployment guide (~45 min one-time setup)

**Step 0 — Prereqs:** a GitHub account, a Notion account, 6 weeks of free time (you have that).

**Step 1 — Notion integration token**
1. Go to `notion.so/my-integrations` → New integration → name it "Opportunity OS" → copy the secret token.
2. In Notion, open the page where you want the Opportunities database to live → `•••` menu → Connections → add your integration.

**Step 2 — Google Alerts as RSS (5 min, replaces "Google Alerts" as a separate tool)**
1. `google.com/alerts` → create alerts like `"finance internship India"`, `"economics fellowship"`, `"CFA scholarship"`.
2. Click the settings gear on each alert → **Deliver to: RSS feed** → copy the URL.
3. Paste into `config/sources.yaml` under `rss:` and set `enabled: true`.

**Step 3 — Groq API key (2 min, optional but recommended)**
1. `console.groq.com` → sign up (no card) → API Keys → create one.

**Step 4 — Fork/clone this repo, then locally:**
```bash
cp .env.example .env        # fill in NOTION_TOKEN, GROQ_API_KEY
pip install -r requirements.txt
python scripts/setup_notion.py <parent_page_id>     # creates the Opportunities DB, prints its ID
```
Find `<parent_page_id>` from the Notion page URL (the 32-char hex string at the end).
Put the printed database ID into `.env` as `NOTION_OPPORTUNITIES_DB_ID`.

**Step 5 — Create the "Weekly Queue" page**
Make a blank Notion page (anywhere in your dashboard), share it with the integration (same `•••` → Connections step), copy its page ID into `NOTION_QUEUE_PAGE_ID`.

**Step 6 — Push secrets to GitHub**
Repo → Settings → Secrets and variables → Actions → New repository secret, for each of:
`NOTION_TOKEN`, `NOTION_OPPORTUNITIES_DB_ID`, `NOTION_QUEUE_PAGE_ID`, `GROQ_API_KEY`.

**Step 7 — Verify selectors for `scrape` sources**
Open each `scrape:` entry's URL in a browser, right-click → Inspect on a listing, confirm the CSS selectors in `config/sources.yaml` still match (sites redesign occasionally — this is the one recurring manual task, see §7).

**Step 8 — Test run**
Repo → Actions tab → "Daily Opportunity Discovery" → Run workflow (manual trigger). Check your Notion database fills in. Then let the cron schedules take over.

**Step 9 — Build the Notion-side views/dashboard**
The API creates the *database and properties*. Views, the dashboard page layout, and templates are a Notion-UI-only concept (not exposed by the Notion API), so build these once, manually, using §5 below — 15 minutes, never touched again.

---

## 4. Data flow & key strategies

**Ingestion** (`src/ingest/`): three deterministic methods, zero LLM cost —
- `rss.py` — any RSS/Atom feed, including Google Alerts delivered as RSS.
- `scrape.py` — config-driven CSS-selector scraping for sites with no feed.
- `github_lists.py` — diffs a markdown file in any GitHub repo (e.g. an "Awesome Internships" list) line-by-line, surfacing only newly added entries. High-signal, since a human curator already filtered the list.

**Deduplication** (`src/dedupe.py`), three layers:
1. Exact — normalized URL hash against `data/seen.json` (strips UTM params, trailing slashes).
2. Fuzzy — `rapidfuzz` title similarity (≥88%) catches the same opportunity reposted under a different URL.
3. Safety net — before creating any Notion page, `notion_sync.get_existing_urls()` queries Notion live, so even a wiped `seen.json` can't re-flood your database.

**Classification** (`src/classify.py`): Groq LLM returns structured JSON — type, geography, focus tags, ROI 0-100, effort estimate, deadline text, one-line summary. Falls back to a deterministic keyword-tier scorer (`src/utils.py: PRESTIGE_KEYWORDS`) if Groq is unset/down/rate-limited — **the pipeline never stalls because of a third-party API.**

**Ranking** (`src/rank.py`), fully transparent:
```
rank_score = 0.40·ROI + 0.25·deadline_urgency + 0.20·focus_match + 0.15·effort_efficiency
```
All weights and the `TARGET_FOCUS` keyword set are constants at the top of the file — tune them as your interests evolve.

**Deadline extraction** (`src/deadline.py`): regex for common phrasings ("Apply by…", "Last date…") + `dateparser` for natural-language dates; cross-checked against whatever the LLM extracted.

---

## 5. Notion structure (build once, manually — API can't create views/templates)

### Database: `Opportunities` (created automatically by `scripts/setup_notion.py`)

| Property | Type | Set by |
|---|---|---|
| Name | Title | bot |
| Org | Text | bot |
| Type | Select | bot (LLM) |
| Geography | Select | bot (LLM) |
| Focus Tags | Multi-select | bot (LLM) |
| ROI Score | Number 0-100 | bot (LLM/fallback) |
| Rank Score | Number 0-100 | bot (rank.py) |
| Status | Status: To Apply → Drafting → Applied → Interview → Offer/Rejected/Expired | bot sets "To Apply"; **you** move it forward |
| Deadline | Date | bot |
| Days Left | Formula (native Notion, auto) | Notion |
| Urgent | Formula 🔥/⚠️ (native Notion, auto) | Notion |
| Source / Source URL | Text / URL | bot |
| Effort Estimate | Select: <1h / 1-3h / 3h+ | bot (LLM) |
| Summary | Text | bot (LLM) |
| Auto-Added | Checkbox | bot |
| This Week's Queue | Checkbox | weekly_queue.py |

### Views (create manually, ~10 min)
1. **🔥 This Week** — Filter: `This Week's Queue = checked`. Sort: Rank Score desc. *Pin to top of dashboard.*
2. **Active Pipeline** — Board grouped by Status, filter Status ≠ Offer/Rejected/Expired.
3. **High ROI** — Filter: ROI Score ≥ 70. Sort: Deadline asc.
4. **Calendar** — Calendar view on Deadline, color by Type.
5. **Archive** — Filter: Status = Expired/Rejected. Collapsed.

### Dashboard layout (one page, embedded in your existing dashboard)
```
[Opportunity Pipeline]
├─ Callout: "N active · M due this week" (manually glance, or build a simple
│            linked-database count — Notion supports this natively)
├─ Linked view: 🔥 This Week        ← top of page
├─ Linked view: Active Pipeline (board)
├─ Toggle: High ROI (collapsed)
├─ Toggle: Calendar (collapsed)
└─ Toggle: Archive (collapsed)
```
Link this page from your existing dashboard sidebar — don't rebuild anything else.

### Templates
- **New manual entry template** (for opportunities you find by hand, outside the bot): pre-fill Status="To Apply", Auto-Added=unchecked, with a checklist sub-block: `[ ] Confirm eligibility` `[ ] Buffer deadline -2 days` `[ ] Save essay/doc link`.
- **Weekly Review template** (separate page, duplicate each week) — see §6.

---

## 6. Weekly operating workflow (<3 hrs/week, as designed)

| When | What happens | Your time |
|---|---|---|
| Daily 06:00 IST | `discover.yml` runs automatically | 0 min |
| Daily 07:30 IST | `archive.yml` cleans up expired items | 0 min |
| **Monday 06:30 IST** | `weekly_queue.yml` posts your ranked queue to the Notion "Weekly Queue" page and flags top items in the **🔥 This Week** view | 0 min |
| **Monday–Friday** | You work through the queue in rank order | up to ~3 hrs total (budget set by `WEEKLY_QUEUE_TARGET_HOURS`) |
| **Sunday, 20 min** | Weekly review (below) | 20 min |

**Sunday 20-min review checklist:**
1. Open **Active Pipeline** board — drag anything that moved (interview scheduled, rejected) to the right column.
2. Glance at **🔥 This Week** — anything untouched? Decide: do it Monday or drop it.
3. Skim Actions tab → confirm all 3 workflows ran green this week (red = a source likely broke, see §7).
4. Once a month: scan `data/seen.json` size and the Notion "Source" column for which sources are actually producing hits — disable dead ones in `sources.yaml`.

---

## 7. Maintenance plan

This is a scraping-dependent system, so the **only** recurring cost is: *scrape selectors occasionally go stale when a site redesigns.*

- **Signal:** `discover.yml` will still run green, but you'll see `[scrape] WARNING - 0 items matched` in the Actions run log for that source.
- **Fix (5 min):** open the site, Inspect the listing, update the 3 selectors in `config/sources.yaml`, commit. No code change needed.
- **Everything else** (RSS, GitHub-list diffing, Notion sync, ranking) is structurally stable and shouldn't need touching for years.
- **Groq free tier disappearing/changing:** the rule-based fallback in `src/classify.py` means the pipeline degrades gracefully (slightly less accurate scoring) rather than breaking. If you ever want to swap providers, only `_call_groq()` needs editing — everything downstream is provider-agnostic.

## 8. Scalability plan (optional future upgrades, not needed now)

1. **Gmail newsletter parsing** — add a Gmail API read-only ingester for newsletters with no public RSS (OAuth refresh-token setup is the only reason this isn't in v1).
2. **Telegram/WhatsApp push** — `python-telegram-bot` (free) to ping you the Monday queue instead of just writing to Notion.
3. **Semantic dedupe** — swap `rapidfuzz` for local `sentence-transformers` embeddings once volume grows past a few hundred entries/month and title-fuzzing starts missing paraphrased duplicates.
4. **Per-university opportunity boards** —  add your university's specific portals as new `scrape` entries; the architecture doesn't change.
