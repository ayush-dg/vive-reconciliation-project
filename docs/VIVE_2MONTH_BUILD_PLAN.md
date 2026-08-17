# VIVE Reconciliation — 2-Month Build Plan (Dev → Prod-Testing Ready)

**Prepared:** 2026-08-16
**Timeline:** 8 weeks (2026-08-17 → 2026-10-09)
**Team:** 2 engineers, working in parallel tracks
**Goal:** Take the reconciliation web app from its current state to a **prod-testing-ready** application — with real NetSuite data, real logins, a real "start this month's reconciliation" concept, and a real force-match workflow for reviewing exceptions.

> Something new to see every 3–4 days, not just code changes behind the scenes. Each week below ends in a demoable checkpoint.

---

## 1. Where We Are Today

**Already working:**
- Upload → extraction → matching → exceptions review pipeline
- Web app UI matching the approved design across all main screens (login, home, upload, exceptions, detail, reports)
- Automated document intake from cloud storage
- Match confidence scoring on exceptions
- Part of the data platform migration to the new cloud storage is complete

**Still needed — what this plan builds:**
- No "run" concept yet — each statement is tracked on its own, with no month/batch grouping
- No ranked-match workflow — exceptions show a mismatch, not "here are the 3 closest matching invoices, pick one"
- Reconciliation still runs against test/sample data rather than live NetSuite invoices
- An old temporary login shortcut still needs to be removed
- No scheduling, retries, or failure alerts around the pipeline yet (the screens exist, the engine behind them doesn't)
- Two separate decision logs instead of one clean record
- Document status tracking is only partial

---

## 2. Top Priority: Force-Match Against Ranked Invoice Matches

The single most requested feature: when a statement line doesn't match automatically, show the reviewer the closest possible invoice matches — ranked, with a confidence score — so they can pick the right one and confirm it manually instead of getting stuck. Today the system only says "matched" or "no match," with nothing in between.

Because this is the most visible and most valuable feature, it's scheduled at the very front of the plan (Weeks 1–2), ahead of some foundational work that would otherwise come first.

To make that possible, Week 1 first connects the app to live NetSuite invoice data, so the ranked-match demo in Week 2 is working with real invoices, not sample data.

---

## 3. Feature Overview

| Feature | When it ships |
|---|---|
| Live connection to NetSuite invoice data | Week 1 |
| Force-match with ranked invoice suggestions | Week 2 |
| Run management ("start this month's reconciliation") | Weeks 1–3 |
| Real logins for every reviewer, old shortcut removed | Week 3 |
| Statement memory (reprocessed statements keep their history) | Week 4 |
| Automatic scheduling, retries, and failure alerts | Week 4 |
| One unified decision/audit record | Week 5 |
| Full document status tracking | Week 5 |
| Statement-total validation checks | Week 6 |
| Email alerts when a batch finishes or fails | Week 6 |
| Write-back of resolved matches to NetSuite | Week 7 |
| Reporting dashboard | Week 7 |
| Finish moving remaining data to the new cloud storage | Week 8 |
| Final hardening, testing, and sign-off | Week 8 |

---

## 4. Week-by-Week Plan

### Week 1 (Aug 17–21): Connect to live NetSuite data, start run management
- Connect the app to live, open/unmatched invoices from NetSuite
- Confirm the existing upload feature reconciles cleanly against this live data
- Start building run management — the "start this month's reconciliation" concept everything else builds on

**Demo:** Upload a real vendor statement and see it reconciled against live NetSuite invoices, not sample data.

---

### Week 2 (Aug 24–28): Force-match ships
- Ship the ranked-match workflow: for any exception, show the closest matching invoices with a confidence score, and let a reviewer confirm the right one
- Every manual match is recorded, so nothing is overridden silently
- Continue run management build

**Demo — headline milestone:** A reviewer opens an exception, sees ranked invoice suggestions with confidence scores, and confirms the correct match. This is the feature clients specifically asked for.

---

### Week 3 (Aug 31–Sep 4): Run management complete, real logins
- Run management finishes — this month's reconciliation is now a trackable unit with its own status and history
- Remove the old temporary login shortcut; harden logins for every reviewer

**Demo:** Every reviewer signs in with their own account. This month's reconciliation has its own dashboard and history.

---

### Week 4 (Sep 7–11): Statement memory + scheduling
- Reprocessing a corrected statement now keeps its history instead of creating a confusing duplicate — last month's already-reconciled invoices stop reappearing as new mismatches
- Add real scheduling, retries, and failure alerts around the pipeline

**Demo:** Reconciliation runs automatically on schedule; re-uploading a corrected statement updates its existing history instead of creating a phantom new mismatch.

---

### Week 5 (Sep 14–18): One clean audit trail, full document tracking
- Combine the two separate decision logs into one clean, permanent record of every decision made
- Track every uploaded document's status from received through completed

**Demo:** Pick any match and see exactly what happened and who decided it, in one place. Pick any uploaded document and see its full status history.

---

### Week 6 (Sep 21–25): Data quality checks + notifications
- Add a check that catches when extracted invoice numbers don't add up to the statement total, plus other data-quality checks
- Add email alerts the moment a batch finishes or fails

**Demo:** A statement with a total that doesn't add up gets flagged automatically; the team gets an email the moment a run finishes or fails.

---

### Week 7 (Sep 28–Oct 2): Write-back to NetSuite + reporting
- Push resolved, confirmed matches back into NetSuite — tested first against a safe test account, and only after explicit reviewer approval, never automatically. Every write is recorded in the audit trail
- Build the reporting dashboard on top of reconciliation results

**Demo:** A reviewer confirms a match and pushes it back to NetSuite with one click, with a full record of what was written and by whom. Plus a management-facing reporting dashboard.

---

### Week 8 (Oct 5–9): Final hardening → prod-testing ready
- Finish moving the remaining data tables to the new cloud storage
- Full regression testing, no known issues left open
- Build a small set of known test cases that run automatically to catch problems early
- Security check: confirm no leftover shortcuts, logins are solid
- Supervised testing with the client's team on real statements end-to-end, including live NetSuite matching and write-back
- Finalize the deployment and rollback plan
- Scope (not build) a plan for a separate, more complex data source that still needs connecting — sized as future work, not attempted in these 8 weeks

**Outcome:** A prod-testing-ready build, handed to the client's team for supervised testing.

---

## 5. Not in This 2-Month Window (called out, not dropped)

| Item | Status | Why it's out |
|---|---|---|
| AI-assisted matching for the hardest cases | On hold | Needs a sign-off on a recent rule change before it can be scheduled |
| Exporting reports to SharePoint | Pushed to a fast-follow | Bumped to make room for NetSuite write-back, which is higher value and specifically requested |
| A more complex secondary data source | Scoped only | The connection exists but isn't production-ready; Week 8 sizes the follow-on work |
| Automatic email inbox pickup of attachments | Needs confirming | Not confirmed to exist yet — worth checking early, and adding as a fast-follow if it doesn't |
| Admin/user management section | Deprioritized | Intentionally left for later |
| Shop-level mismatch reporting | Future item | Design exists, no build slot in this window — natural next step after reporting ships |
| Flexible filtering beyond shop | Future item | Same as above |

---

## 6. Built to Last, Not Just to Ship

Several of the pieces built in this window — run management, the document registry, the audit/decision log, and the NetSuite connection — are being designed as clean, reusable building blocks rather than one-off, hardcoded features. Client- and system-specific details (like NetSuite's own data format) are kept separate from the core logic. That means if the business builds another reconciliation solution in the future (a different data source, a different client), most of this work can be reused directly instead of rebuilt from scratch.

This doesn't change the schedule — it's simply a quality standard applied while building each piece above.

---

## 7. "Prod-Testing Ready" — Definition of Done

By the end of Week 8:
- [ ] Live NetSuite invoice data connected and reconciling
- [ ] Force-match with ranked suggestions live and in daily use
- [ ] Write-back to NetSuite live, tested safely first, approval-gated, fully logged
- [ ] Every reviewer has their own login; no leftover shortcuts
- [ ] Every month's reconciliation is a trackable, self-contained run
- [ ] Reprocessed statements keep their history — no phantom duplicate mismatches
- [ ] One unified, complete audit trail
- [ ] Statement-total validation catches line-item errors automatically
- [ ] Scheduling, retries, and failure alerts running unattended
- [ ] Reporting dashboard live
- [ ] Remaining data fully migrated to the new cloud storage
- [ ] Full test suite passing; a small set of known cases checked automatically
- [ ] The client's team has run real statements through supervised testing with no blocking issues
