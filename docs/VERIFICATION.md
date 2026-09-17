# Verification

2026-09-16

- Original supplied project: 82 tests passed.
- Sheets implementation before deployment hardening: 104 tests passed.
- Deployment suite: **112 tests passed**. Hardening adds tests for durable backlog recovery, completed-work weekly budget accounting, rolling deadlines and invalid CTA rejection.
- Existing live source check: Opportunity Desk 10 listings; Opportunities for Youth 10 listings; 20 generated preparation packs.
- Local doctor fails immediately and explicitly when GOOGLE_SERVICE_ACCOUNT_JSON is missing.
- Live authenticated Sheet writes and visual readback require the service account and destination sharing; they have not been verified locally.
- Notion migration requires reading the original database; it is not inferred from the code archive.

The workflow runs the full test suite before every scheduled or manual Sheet mutation. See Actions for deployed run results.
