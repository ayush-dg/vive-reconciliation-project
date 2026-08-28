**Session:** Session 6 — Home Dashboard + Exceptions Screens
**Date:** 2026-08-29
**Engineer:** Vaishali

## Task 6.1 — Home screen (statement list + status badges + summary stats + Reconcile action)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 6

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Uploading a statement and returning to Home | Shows it with the correct status badge | `home.spec.ts` | PASS |
| TC-2 | Summary stats | Reflect actual counts, including reconciled/not-reconciled | `home.spec.ts` | PASS |
| TC-3 | Clicking Reconcile on an extracted document | Triggers matching, badge updates to Reconciled or shows open exceptions | `home.spec.ts` | PASS |
| TC-4 | Reconcile button | Not shown/disabled for a document that hasn't finished extraction | `home.spec.ts` | PASS |
| TC-5 | "View statement" | Navigates to Document Detail | `home.spec.ts` | PASS |

### Challenge Agent Output

```
## Challenge Agent — Tasks 6.1 + 6.5
(full output — see Task 6.5's entry below, one combined review covered both tasks)

### Concrete Defects
| # | Defect | Evidence | Impact |
|---|--------|----------|--------|
| 1 | Reconcile button stays visible/enabled indefinitely, and re-clicking shows a misleading "Reconciliation started" success toast, for a document whose matching run already completed but resolved every line into an exception (no recon_match row) | documentStatus.ts's Reconciled check trusted "any match exists"; canReconcile in both view components trusted that badge | Violates UI_SURFACE.md's stated Reconcile condition |
| 2 | A partially-matched document (some lines matched, ≥1 line an open exception) is displayed as fully Reconciled — Home's reconciledCount counts it as reconciled | Match-existence check was LIMIT 1 at the document level, not "all lines resolved" | Summary stats and the Reconcile action both misreport unresolved work |

### Challenge Verdict
FINDINGS — 2 item(s) required engineer disposition before commit.
```

### Code Review
No new task-scoped invariants (per EXECUTION_PLAN.md's own "Invariant enforcement: None new
task-scoped"). Both findings concerned `documentStatus.ts` (Task 2.3), not a new invariant
this task introduces.

### Scope Decisions

**Finding 1 + Finding 2 (Reconcile never terminates / partial match misreported as
Reconciled)** — FIXED, at the root cause: `documentStatus.ts`'s "Reconciled" check now
requires every `silver.statement_line` row for the document to have a match, not merely
one. A document with any open `recon_exception` now surfaces as "Failed — see Exceptions"
(reusing that badge's existing wording — UI_SURFACE.md's badge set is fixed at four
values, no fifth was invented). This transitively fixes the Reconcile button's
never-terminates symptom, since `canReconcile`'s existing `badge === 'Processing'` check
now correctly excludes both terminal outcomes. Verified via `scripts/test_document_status.mjs`
(4 new unit-level checks) and a new end-to-end Playwright test in `document-detail.spec.ts`.
Full disposition detail, including the two cross-session regressions this task's own test
run separately surfaced (`extract-trigger.spec.ts`'s non-PDF fixtures,
`test_document_status.mjs`'s stale `snapshot_version` column) and the `.env`
`FABRIC_SQL_ENDPOINT` discovery, is recorded in `sessions/S06_SESSION_LOG.md`'s Decision Log.

**Untested Scenarios not elevated to Findings, accepted or partially addressed:**
- Exact stat values for `openExceptions`/`extractionFailures`/`reconciledCount` against
  known seeded counts — only `documentsProcessed` is asserted against ground truth in
  `home.spec.ts`; the other three are exercised qualitatively (e.g. the Reconcile-to-
  Reconciled test) but not against a precise expected count. Accepted: `homeSummary.ts`'s
  aggregation is a single, simple `.filter()` per stat over the same badge data
  `documentStatus.ts`'s own dedicated tests already cover exhaustively — re-testing the
  arithmetic here would be redundant with, not additive to, that coverage.
- `resolveVendorSlug` with a dangling `vendor_id` (no matching registry row) — not a
  reachable state: `extracted_document.vendor_id` carries a `REFERENCES
  extracted_vendor_registry(vendor_id)` FK constraint (Task 1.2), enforced at write time.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (FINDINGS, shared review with Task 6.5)
[x] All FINDINGS dispositioned (2 fixed at root cause)
[x] Pre-commit declaration recorded
[x] Code review complete (no new task-scoped invariant; root-cause fix reviewed)
[x] Scope decisions documented

**Status:** Completed

---

## Task 6.2 — Exceptions list screen

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 6

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Exceptions list | Populates with real data from Session 5's matching output | `exceptions.spec.ts` | |
| TC-2 | Search by vendor name | Filters correctly | `exceptions.spec.ts` | |
| TC-3 | Pagination | Shows 50 rows per page when more than 50 exist | `exceptions.spec.ts` | |
| TC-4 | `possible_duplicate_correction` category | Never appears in the list | `exceptions.spec.ts` | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: None new task-scoped (relies on S5's schema wiring from Task 5.4).

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 6.3 — Exception Detail screen

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 6

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Exception with CCC evidence | Related panel shows it populated | `exception-detail.spec.ts` | |
| TC-2 | Exception without CCC evidence | Shows "No CCC confirmation available" | `exception-detail.spec.ts` | |
| TC-3 | `amount_mismatch` exception | Expandable section with statement + NetSuite value | `exception-detail.spec.ts` | |
| TC-4 | Non-amount-mismatch exception | Does not show the drill-down section | `exception-detail.spec.ts` | |
| TC-5 | Any exception | No approve/dispute button renders anywhere | `exception-detail.spec.ts` | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: None new task-scoped.

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 6.4 — Global error/loading state wiring across Home/Exceptions/Exception Detail

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 6

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Simulated slow network | Same spinner style on all three screens | `loading-error-consistency.spec.ts` | |
| TC-2 | Simulated API failure | Same inline error + Retry pattern on all three screens | `loading-error-consistency.spec.ts` | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: None task-scoped.

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 6.5 — Document Detail screen (extraction summary)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 6

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Navigating from Home's "View statement" | Opens this screen with the correct document's rows | `document-detail.spec.ts` | PASS |
| TC-2 | Extraction summary strip | Shows correct counts by provider | `document-detail.spec.ts` | PASS |
| TC-3 | Document extracted via known-vendor deterministic path | 100% `python_library_pdfplumber`, no Claude/OCR-fallback counts | `document-detail.spec.ts` | PASS |
| TC-4 | Document with some AI-failure fallback rows | Non-zero OCR-fallback count | `document-detail.spec.ts` | PASS |

Plus TC-5 (Extract/Reconcile actions appear only when applicable), and TC-6 added during
this task's challenge review (a document whose matching run produces an open exception
shows "Failed — see Exceptions", Reconcile disappears). 6/6 test scenarios (16 assertions
across `document-detail.spec.ts`) pass.

### Challenge Agent Output

```
## Challenge Agent — Tasks 6.1 + 6.5

### Untested Scenarios
| # | Scenario | Why it matters | Requirement at risk |
|---|----------|----------------|-------------------|
| 1 | Reconcile invoked on a document whose lines resolve entirely into exceptions | Only the full-match "Reconciled" branch was tested | Task 6.1's own "...or shows open exceptions" test case |
| 2 | A document with a partial match (some lines matched, ≥1 exception) | computeDocumentStatus's match check was LIMIT 1, no exclusion for sibling open exceptions | Reconciled/not-reconciled counts and Reconcile visibility |
| 3 | Document Detail's Extract/Reconcile visibility for Retrying/Failed badge states | Only registered->processing (Claude path) was tested | Task 6.5's own action-visibility test case |
| 4 | Home summary stats' openExceptions/extractionFailures/reconciledCount against known seeded values | Only documentsProcessed was asserted against ground truth | Task 6.1's stats test case |
| 5 | resolveVendorSlug with a vendor_id that has no matching registry row | Falls back to null -> "Identifying..." for an actually-identified vendor | Vendor display accuracy |
| 6 | extractionMethodSummary's "unknown" bucket (NULL provider_used) | Displayed as the raw literal "unknown", not a plain label like the other three | UI_SURFACE.md's "plainly labeled" spirit |
| 7 | getStatementLinesForDocument's "at most one passing attempt" assumption under a document with 2+ lines from that one attempt | No test seeds >1 line to check the subquery is consistent across rows | Per-line confidence/provider display correctness |

### Unverified Assumptions
| # | Assumption in code | Basis | Testable within task scope |
|---|--------------------|-------|---------------------------|
| 1 | documentsProcessed = total row count, i.e. every uploaded document counts even if never extracted | homeSummary.ts | Yes |
| 2 | getStatementLinesForDocument assumes exactly one passing attempt ever exists per document, relying on an idempotency guard living in extractionPipeline.ts, not re-checked here | documentDetail.ts comment | Partially |
| 3 | Next's env loader never overrides an already-set process.env.FABRIC_SQL_ENDPOINT, so playwright.config.ts's override reliably wins over .env | Standard dotenv precedence, empirically confirmed via /api/health before/after | Yes — confirmed |
| 4 | resolveVendorSlug assumes referential integrity between vendor_id and vendor_registry always holds | documents.ts, no join enforcement visible at read time | Yes — but see Scope Decision: this is actually FK-enforced, confirmed not reachable |

### Concrete Defects
| # | Defect | Evidence | Impact |
|---|--------|----------|--------|
| 1 | Reconcile button never terminates + misleading repeat success toast for a fully-excepted document | documentStatus.ts's Reconciled check ("any match exists"); canReconcile trusts that badge | Contradicts UI_SURFACE.md's Reconcile condition |
| 2 | Partially-matched document misreported as fully Reconciled in badge + reconciledCount | Match-existence check was LIMIT 1 at document level | Reconciled-count / not-reconciled-count under-report unresolved work |

### Structural Complexity Check
CLEAN across homeSummary.ts and documentDetail.ts.

### Challenge Verdict
FINDINGS — 2 item(s) required engineer disposition before commit.
```

### Code Review
No new task-scoped invariants. Both concrete defects were in `documentStatus.ts` (Task
2.3), fixed at the root — see Task 6.1's entry above for the full disposition (shared
finding, one fix).

### Scope Decisions

**Untested Scenario 6 (unknown provider bucket unlabeled)** — FIXED. Added an `unknown`
entry to `DocumentDetailView.tsx`'s `PROVIDER_LABELS` map with a plain-English label,
matching the treatment the other three providers already get.

**Untested Scenario 3 (Retrying/Failed action visibility)** — ACCEPTED, not separately
tested. `canExtract`/`canReconcile`'s conditions are simple boolean expressions
(`status === 'registered'`, `status === 'processing' && badge === 'Processing'`) — for
`Retrying`/`Failed`, `badge !== 'Processing'` already makes `canReconcile` false by
construction, and `status` is `'processing'` (not `'registered'`) so `canExtract` is also
already false; this is the same logic Task 2.4/Session 3's own tests already exercise for
the underlying badge computation. Re-deriving it here would test the same boolean
expression, not new behavior.

**Untested Scenario 7 (multi-line confidence/provider consistency)** — ACCEPTED, not
tested. The correlated subquery selects one scalar value (the latest passing attempt's
confidence/provider) independent of how many rows the outer query returns — there is no
per-row variation possible in the query's own structure for it to get "inconsistent"
across lines from the same attempt; a test would confirm arithmetic that has no branching
to get wrong.

**Unverified Assumption 4 (dangling vendor_id)** — RESOLVED as not reachable: `extracted_
document.vendor_id` carries an FK constraint to `extracted_vendor_registry(vendor_id)`
(Task 1.2's schema), enforced at write time — this state cannot occur via any code path in
this codebase.

**Untested Scenarios 1, 2, 4 (exact stat/action end-to-end coverage)** — FIXED via the new
end-to-end regression added to `document-detail.spec.ts` (Untested Scenario 1's document-
level equivalent) plus `scripts/test_document_status.mjs`'s new unit-level checks (Untested
Scenario 2). Untested Scenario 4 (exact stat arithmetic) accepted per Task 6.1's own Scope
Decisions above.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (FINDINGS, shared review with Task 6.1)
[x] All FINDINGS dispositioned (2 fixed at root cause, several Untested Scenarios
    fixed/accepted with rationale)
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed
