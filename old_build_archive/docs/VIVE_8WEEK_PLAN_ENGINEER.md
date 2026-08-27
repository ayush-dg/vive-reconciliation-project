# VIVE Reconciliation — Ground-Up Rebuild Plan (Web Application)

**Prepared:** 2026-08-16
**Timeline:** 8-week dev build (2026-08-17 → 2026-10-09)
**Decision:** Stop layering enhancements on the current codebase. Rebuild in a **fresh repository**, feature by feature, following the design decisions in `docs/VIVE_Statement_Reconciliation_Architecture_v3_3.md` (the approved "final technical architecture") rather than the current lightweight stack.
**Scope of this doc:** the web application itself, feature by feature — pages, backend endpoints, background jobs, business logic, database schema. No separate "infrastructure setup" phase called out here.
**Supersedes:** `docs/VIVE_2MONTH_BUILD_PLAN.md` and `docs/VIVE_2MONTH_BUILD_PLAN_ENGINEERING.md` — both are now marked superseded, not deleted. The current repo becomes reference-only.
**Companion doc:** `docs/VIVE_REBUILD_PLAN_BUSINESS.md` — same phases, plain-language, no implementation detail.

---


## 1. This is the dev-build timeline, not the go-live timeline

This 8-week plan gets the **application built** — every feature working end to end. It does not, by itself, get the application to production go-live. Two things sit outside this 8-week window, on their own clock:

1. **A handful of open business questions** need sign-off from VIVE/the SOW owner — intake volume assumptions, reference-data scope, re-match timing expectations, and whether NetSuite write-back is even in scope. Send these immediately; they run in parallel with the build and don't block it.
2. **A shadow-mode trial** starts once matching is working (~Week 5) and has to run **3–4 full monthly cycles** — the app scores matches, the AP team keeps working as they do today, and the two are compared — before anything auto-approves or writes back to NetSuite. That's roughly 3–4 months, starting after Week 5, continuing well past the end of this 8-week build.

The 8 weeks below build a fully working application. Go-live follows once the trial above concludes and the open questions are closed — see §3.

---

## 2. Week by week

### Week 1 — Sign-in, home, upload

- **Sign-in page** — single sign-on, no local accounts, session handling
- **Home page** — dashboard shell showing uploaded documents and their status
- **Upload feature** — upload page and endpoint, document record with a tracked status (received → validating → ready → ... → superseded), duplicate detection
- Uploading a document does not itself trigger reconciliation — intake and processing stay decoupled, processing is a deliberate action built in Week 5

**Demo:** sign in, land on the home page, upload a statement, see it tracked with a real status.

---

### Week 2 — Extraction logic

- Backend extraction feature: reads each uploaded PDF and pulls out line-item invoice data using Claude
- Prompt structure keeps document content as data the model reads, never as instructions it follows
- **Math check, mandatory:** extracted line amounts must sum to the statement's stated total before the document moves forward; on failure, automatically re-extract (max 2 attempts) before flagging for review
- Per-field validation (invoice number format, plausible amount, parseable date) — a bad field flags just that field, not the whole line

**Demo:** upload a real statement, watch it get extracted, see a deliberately bad total get caught and flagged automatically.

---

### Week 3 — Extraction hardening + NetSuite/CCC data feed

- Raw extraction output stored permanently and separately from the cleaned-up version, so any bad extraction is traceable back to exactly what the model returned
- Concurrency limit on extraction calls
- A small regression suite of known statements, run automatically on every change to extraction logic
- Scheduled feature pulling open invoices from NetSuite and repair-order data from CCC into the app's own database daily, timestamped per batch
- **Matching will only ever read this synced copy — never call NetSuite or CCC directly at match time**

**Demo:** show the synced NetSuite/CCC data landing daily, and the regression suite catching a deliberately broken extraction change.

---

### Week 4 — Reconciliation logic (matching engine)

- Exact match → tolerance match → rule-based match (PO number, RO number, date window, vendor aliases) — reads only the synced data from Week 3
- Values cleaned up and normalized once, never re-transformed at match time
- Data model for reconciliation runs, work items, matches, match evidence, and exceptions, with version tracking so two reviewers can't silently overwrite each other

**Demo:** run a real statement through matching and see it score against live-synced NetSuite/CCC data.

---

### Week 5 — Shadow mode + Run Management

- Matching goes live in **shadow mode**: it scores every match, nothing auto-approves, the AP team keeps working as today. **The 3–4 month trial clock starts now** (§1) — this runs in parallel with the rest of this build, not blocking it
- **"Start this month's reconciliation" becomes a real feature** — create a run with its own scope (period, vendors, cutoff), preview what's included, lock it in, then process. This connects Upload → Extraction → Matching into one trackable unit instead of files processed individually with no grouping

**Demo:** start a run, watch it process a batch of statements, see shadow-mode scores next to what the AP team decided manually.

---

### Week 6 — Exceptions, audit trail, reviewer workspace core

- Exceptions get a category, an owner, and an aging clock; re-checks can change a category without silently closing or duplicating it
- Every decision — automatic or human — writes to a permanent audit record as it happens
- Reviewer workspace: run management page, exception review page, bulk-approve with total dollar amount shown before confirming, every bulk action individually reversible

**Demo:** review a real exception, see the evidence behind the system's suggestion, bulk-approve a batch, then reverse one of them.

---

### Week 7 — Reviewer controls, permissions, reporting core

- Real distinction between the person who reviews a match and the person who approves it — the app is never the approver
- Dollar threshold above which a second person's approval is required
- Page-level and data-level permissions so a shop manager only sees their own shop's data
- Reporting page: reconciliation results and exception trends by vendor/shop, built off a periodically-refreshed summary table, not live transactional data

**Demo:** log in as two different reviewer roles and show the permission boundary; pull up the reporting dashboard.

---

### Week 8 — Reporting cost visibility + secondary features + wrap-up

- Processing-cost visibility (per vendor, trend over time) on the reporting page
- Whatever capacity allows from: scheduling/retry/failure alerts around the pipeline, exporting the reporting dashboard's output, email notifications on run finish/fail
- Full regression pass across everything built Weeks 1–7; fix anything broken
- Confirm shadow-mode trial (started Week 5) is running cleanly and actually collecting comparison data — this is the thing that continues after this build ends

**Outcome:** a fully working application, end to end — sign-in through reporting — with the shadow-mode trial already ~3 weeks into its 3–4 month run.

---

## 3. What happens after Week 8 — go-live is a separate gate

The application is feature-complete at the end of Week 8. It is **not** ready to go live yet:
- [ ] Shadow-mode trial (started Week 5, roughly Weeks 5–20) completes 3–4 monthly cycles; match-confidence thresholds get set from what was actually measured, not guessed
- [ ] The open business questions from §1 are closed, not just sent
- [ ] Approval-threshold amounts and data-retention policy confirmed by someone on VIVE's side with authority to set them
- [ ] A named production owner assigned — on call, owns the runbook
- [ ] AI-assisted matching (for the hardest residual cases) and NetSuite write-back remain **not scheduled** — both are blocked on governance sign-offs unrelated to this build, and write-back additionally can't go live before the shadow-mode trial above concludes. Once unblocked, each is roughly 1.5–2 weeks of additional build.
