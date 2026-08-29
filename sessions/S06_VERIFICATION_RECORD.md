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
| TC-1 | Exceptions list | Populates with real data from Session 5's matching output | `exceptions.spec.ts` | PASS |
| TC-2 | Search by vendor name | Filters correctly | `exceptions.spec.ts` | PASS |
| TC-3 | Pagination | Shows 50 rows per page when more than 50 exist | `exceptions.spec.ts` | PASS |
| TC-4 | `possible_duplicate_correction` category | Never appears in the list | `exceptions.spec.ts` | PASS |

Plus an `amount_mismatch`-through-the-real-pipeline case, and 4 more added during this
task's challenge review (no-bulk-selection, LIKE-wildcard escaping, load-error+Retry —
below). 9/9 test scenarios pass.

### Challenge Agent Output

```
## Challenge Agent — Tasks 6.2 + 6.3

### Untested Scenarios
| # | Scenario | Why it matters | Requirement at risk |
|---|----------|----------------|-------------------|
| 1 | Column sorting (Vendor/Statement/Invoice Ref/Date marked Sortable: Y in UI_SURFACE.md's List Configuration) is not implemented anywhere — no clickable header, no sort state, no API param | If intended, a silent gap; if descoped, undocumented (unlike search/pagination, which have explicit "resolved default" language) | UI_SURFACE.md List Configuration |
| 2 | No test exercises a vendor_slug/invoice_ref containing % or _ through search | Unescaped LIKE wildcards produce broader-than-intended matches — vendor_slug is itself underscore-delimited by construction | Search correctness |
| 3 | An amount_mismatch exception with NULL reference_extracted_at | The "as of" caption would silently omit with no indication it's intentionally absent | The caption's own justification (never a live re-query) |
| 4 | A failed /api/exceptions fetch through the search/pagination client path | Reveals the silent-swallow behavior (Concrete Defect #1) | UI_SURFACE.md Exceptions Error state |

### Unverified Assumptions
| # | Assumption in code | Basis | Testable within task scope |
|---|--------------------|-------|---------------------------|
| 1 | The page query param is always a whole number >= 1; only Number.isFinite && > 0 was checked | api/exceptions/route.ts | Yes |
| 2 | recon.exception.evidence is never SQL NULL, even though migration 005 makes it nullable — JSON.parse(null) doesn't throw, bypassing the try/catch | exceptionDetail.ts | Yes |
| 3 | UI_SURFACE.md's own List Configuration marks BOTH Amount and Date as Default Sort: DESC — an internally conflicting spec; the code silently picks Date | docs/UI_SURFACE.md:277,279 vs. exceptionsList.ts | Not independently testable — a doc ambiguity |
| 4 | Search assumes caller input never contains LIKE metacharacters requiring escaping | exceptionsList.ts | Yes — see Concrete Defect #2 |

### Concrete Defects
| # | Defect | Evidence | Impact |
|---|--------|----------|--------|
| 1 | ExceptionsView.tsx's load() silently discarded failed API responses — only branched on res.ok, nothing on the failure path | ExceptionsView.tsx's load() | A failing search/pagination click left stale/wrong data with zero error indication |
| 2 | exceptionsList.ts's search LIKE clause interpolated raw input without escaping %/_ | exceptionsList.ts | A search term containing "_" (this project's own vendor_slug convention) could match unrelated rows differing by one character |
| 3 | ui_tests/exceptions.spec.ts was missing the "No bulk-selection UI is present" test Task 6.2's own UI test spec explicitly requires | Full file read, no bulk-selection test existed | Underlying UI was correct; the required verification was simply never written |

### Known Untested Scenarios (out of scope — not findings)
- Fabric-mode behavior — assertSqliteMode() hard-blocks it, requires external state
- Session idle-timeout interrupting mid-browse — different session's scope
- Claude-live residual-match path affecting evidence content — requires live credentials
- Real CCC production table name/schema — already flagged as an open question in Session 5
- Multi-user/concurrent access to the same exception row — requires human interaction

### Structural Complexity Check
CLEAN across exceptionsList.ts and exceptionDetail.ts.

### Challenge Verdict
FINDINGS — 3 item(s) require engineer disposition before commit.
```

### Code Review
No new task-scoped invariants. Reviewed against S5's schema wiring (Task 5.4), which this
task only reads from.

### Scope Decisions

**Finding 1 (silent error swallow)** — FIXED. `ExceptionsView.tsx`'s `load()` now sets an
error state on a non-ok response or thrown fetch error, rendering the same inline
`error-boundary`/Retry pattern used globally, with a Retry button that repeats the last
attempted search/page. Verified via new test: a mocked 500 response shows the error, Retry
recovers once the mock is lifted.

**Finding 2 (unescaped LIKE wildcards)** — FIXED. Added `escapeLikePattern()` (escapes
`\`, `%`, `_`) and an `ESCAPE '\'` clause on both LIKE comparisons. Verified via new test:
searching for `wildcard_test_<id>` no longer also matches a decoy vendor
`wildcardXtest_<id>` that would coincidentally match if `_` were treated as a wildcard.

**Finding 3 (missing bulk-selection test)** — FIXED. Added the test EXECUTION_PLAN.md's UI
test spec names, confirming zero `input[type="checkbox"]` elements render.

**Unverified Assumption 1 (non-integer page param)** — FIXED. `api/exceptions/route.ts`
now requires `Number.isInteger(page)`, not just `Number.isFinite`.

**Unverified Assumption 2 (NULL evidence uncaught)** — FIXED. `exceptionDetail.ts` now
guards `row.evidence` truthiness before attempting `JSON.parse`, so a NULL row (reachable
only via direct DB manipulation today, since `exceptionWriter.ts`'s single write path
always stringifies evidence) degrades to "no evidence shown" instead of throwing. Verified
via new test seeding a NULL-evidence row directly and confirming the page renders without
hitting the global error boundary.

**Untested Scenario 1 (column sorting not implemented)** — ACCEPTED as an Out of Scope
Observation (recorded in `sessions/S06_SESSION_LOG.md`), not built. Task 6.2's own CC
prompt names only pagination and search as "resolved defaults" — UI_SURFACE.md's generic
per-column `Sortable: Y` metadata reads as descriptive of the standard List-screen shape,
not a literal requirement this task's own text calls for implementing. Flagged for
engineer decision rather than silently built or silently dropped.

**Unverified Assumption 3 (UI_SURFACE.md's own Amount/Date sort conflict)** — Recorded as
an Out of Scope Observation (a planning-doc inconsistency, not a code defect) — Date DESC
(most recent first) is the more defensible default given Amount isn't even sortable in
this build yet.

**Untested Scenario 3 (as-of caption silently absent for NULL reference_extracted_at)** —
ACCEPTED, not fixed. A genuinely unknown timestamp showing no caption (rather than a
fabricated one) is the honest degrade; the drill-down's numeric values remain correct and
visible regardless.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (FINDINGS, shared review with Task 6.3)
[x] All FINDINGS dispositioned (3 fixed, 2 assumptions fixed, 2 accepted/recorded as scope gaps)
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

---

## Task 6.3 — Exception Detail screen

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 6

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Exception with CCC evidence | Related panel shows it populated | `exception-detail.spec.ts` | PASS |
| TC-2 | Exception without CCC evidence | Shows "No CCC confirmation available" | `exception-detail.spec.ts` | PASS |
| TC-3 | `amount_mismatch` exception | Expandable section with statement + NetSuite value | `exception-detail.spec.ts` | PASS |
| TC-4 | Non-amount-mismatch exception | Does not show the drill-down section | `exception-detail.spec.ts` | PASS |
| TC-5 | Any exception | No approve/dispute button renders anywhere | `exception-detail.spec.ts` | PASS |

Plus "Back to list" navigation, and a NULL-evidence regression added during this task's
challenge review (below). 7/7 test scenarios pass.

### Challenge Agent Output
See Task 6.2's entry above — one combined review covered both tasks (`exceptionDetail.ts`
and `exceptionsList.ts` share the same review pass, same rationale as Task 6.1+6.5's
combined review: symmetric, tightly-coupled peers).

### Code Review
No new task-scoped invariants.

### Scope Decisions
Finding 2 (Unverified Assumption 2 — NULL evidence uncaught) belongs to this task's own
`exceptionDetail.ts` — see the full disposition under Task 6.2's Scope Decisions above (the
fix and its regression test are recorded there to avoid duplication, since the challenge
review covered both files together).

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (FINDINGS, shared review with Task 6.2)
[x] All FINDINGS dispositioned (see Task 6.2's entry for the shared fixes)
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

---

## Task 6.4 — Global error/loading state wiring across Home/Exceptions/Exception Detail

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 6

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Simulated slow network | Same spinner style on all three screens | `loading-error-consistency.spec.ts` | PASS (structural — see Scope Decisions) |
| TC-2 | Simulated API failure | Same inline error + Retry pattern on all three screens | `loading-error-consistency.spec.ts` | PASS |

Plus a structural no-override-file check, an SSR not-found cross-screen identity check, and
a genuinely cross-screen client-refetch identity check added during this task's own
challenge review. 4/4 test scenarios pass.

### Challenge Agent Output

```
## Challenge Agent — Task 6.4

### Concrete Defects
| # | Defect | Evidence | Impact |
|---|--------|----------|--------|
| 1 | HomeView.tsx's refresh() had no error handling — a failed /api/documents or /api/home-summary response left stale data with zero user-facing signal, reproducing the exact bug Task 6.2's own review found and fixed for Exceptions | HomeView.tsx refresh() | Contradicts the Error state requirement |
| 2 | DocumentDetailView.tsx's refresh() had the identical silent-failure gap | DocumentDetailView.tsx refresh() | Same |
| 3 | Neither refresh() had its own try/catch, so a network failure inside it was caught by the CALLER's try/catch, producing a misleading "action failed" toast even when the preceding Extract/Reconcile POST actually succeeded | handleExtract/handleReconcile in both files | User told an action failed when it actually started successfully |
| 4 | Exceptions' own Task 6.2 fix hand-duplicated error.tsx's markup with DIFFERENT testids (exceptions-load-error/-retry vs. error-boundary/error-retry) rather than reusing a shared component — combined with Findings 1-2, the four screens exhibited THREE different behaviors on the exact scenario Task 6.4 exists to unify | grep confirmed only 2 hand-written occurrences of .error-boundary in src/ | Directly contradicts this task's own "no screen inventing its own pattern" mandate |

### Untested Scenarios
| # | Scenario | Why it matters |
|---|----------|-----------------|
| 1 | Home's/Document Detail's refresh() failure path — no test exercised it at all |
| 2 | Exceptions' locally-duplicated error UI never compared against error.tsx's rendered output cross-screen |
| 3 | No test asserted a loading indicator during Exceptions' search/pagination or Home/Document Detail's Extract/Reconcile fetch |

### Known Untested Scenarios (out of scope — not findings)
- Real network-latency race to observe the spinner mid-transition — local SQLite fetches are near-instant; already an accepted gap, and dev-test-loading/global-elements.spec.ts already prove the shared mechanism works generically

### Challenge Verdict
FINDINGS — 4 item(s) require engineer disposition before commit.
```

### Code Review
No new task-scoped invariants.

### Scope Decisions

**Findings 1-4 (silent refresh failures on Home/Document Detail, misleading toast, and
Exceptions' own hand-duplicated error UI)** — FIXED together, at the root: extracted a
genuinely shared `src/components/InlineLoadError.tsx` (reusing `error.tsx`'s exact
`error-boundary`/`error-retry` testids and markup) and wired it into all three screens.
`HomeView.tsx`'s and `DocumentDetailView.tsx`'s `refresh()` functions were rewritten to
never throw — each catches its own failure and sets a local error state — so a failed
refresh can no longer be misattributed to the preceding action by the caller's own
try/catch (Finding 3). `ExceptionsView.tsx`'s prior hand-duplicated markup (added during
Task 6.2's own review) was replaced with the shared component. Verified via: two new
per-screen regression tests (`home.spec.ts`, `document-detail.spec.ts`) each confirming a
successful action + failed refresh shows a correct "success" toast alongside the shared
error, with Retry recovering; and one new cross-screen test in
`loading-error-consistency.spec.ts` directly confirming all three screens render
byte-identical `error-boundary` markup for their respective client-refetch failures — the
genuinely direct proof of this task's "one shared pattern" mandate, which no test
previously attempted.

**Untested Scenario 3 (loading indicator during client-side fetches)** — ACCEPTED, not
built or tested. UI_SURFACE.md's "simple spinner" default is specifically the SSR/route-
transition `loading.tsx` mechanism (Session 1); none of Home/Exceptions/Document Detail's
CC prompts call for a distinct in-place spinner during a client-side refetch, and adding
one now would be unrequested scope beyond fixing the actual defects found.

**Test-infrastructure observation (not a code defect):** running the full, now
60-test-strong Playwright suite at this project's default worker concurrency
(`workers: undefined`, i.e. CPU-core-count on this machine) produced transient
`ECONNRESET`/timeout failures under the added load from this session's new tests; the same
tests pass reliably in isolation and at `--workers=2`. Recorded here as a real, growing
resource-contention signal for a future session to consider (e.g. lowering local default
concurrency), not something this task's own code should paper over.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (FINDINGS)
[x] All FINDINGS dispositioned (4 fixed at the root, 1 untested scenario accepted)
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

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
