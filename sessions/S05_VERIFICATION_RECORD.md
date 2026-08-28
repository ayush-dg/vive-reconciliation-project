**Session:** Session 5 — Matching Service
**Date:** 2026-08-28
**Engineer:** Vaishali

## Task 5.1 — Matching invocation (manual + scheduled)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Manual API trigger | Executes matching against currently eligible StatementLines | N/A | PASS |
| TC-2 | Scheduled batch job | Executes matching on its configured cadence | N/A | PASS |
| TC-3 | Uploading a document (Task 2.2's endpoint) | Does not itself invoke matching — INVARIANT TOUCH: S1 | N/A | PASS |
| TC-4/TC-5 | Manual trigger and scheduled batch invoked concurrently against overlapping eligible documents | Each document matched exactly once, never twice — INVARIANT TOUCH: G5 | N/A | PASS |

Plus TC-6 (unknown document_id returns `not_found`, not a throw), and 3 more added during
this task's challenge review (TC-7, TC-8, TC-9 below). 16/16 checks pass via
`./scripts/test_matching_invocation.sh`.

### Challenge Agent Output

```
## Challenge Agent — Task 5.1

### Untested Scenarios
| # | Scenario | Why it matters | Invariant/requirement at risk |
|---|----------|----------------|-------------------|
| 1 | Process crash between acquireMatchingLock() succeeding and releaseMatchingLock() running | recon_document_lock had no TTL/staleness column and nothing read acquired_at — an abandoned lock row was permanent, the document could never be matched again without manual DB intervention | G5 |
| 2 | acquireMatchingLock()'s catch { return false } on a non-constraint error | Verified empirically: a malformed argument still returned false, identical to legitimate contention — callers couldn't distinguish "another owner holds this" from "this failed for an unrelated reason" | G5 |
| 3 | recon_document_lock.document_id had no FK reference to extracted.document, unlike every other document-linking column in this schema | Verified empirically: a lock could be acquired for a document_id with no row in extracted_document at all | G5 |

### Unverified Assumptions
| # | Assumption in code | Basis | Testable within task scope |
|---|--------------------|-------|---------------------------|
| 1 | The finally { releaseMatchingLock(...) } path correctly releases the lock when matching itself fails | matchDocumentStub() is a hardcoded no-op that can never throw — structurally present but never actually executed under failure | Not testable today without modifying source; re-verify once Task 5.2 replaces the stub |
| 2 | TC-4/TC-5's sequential-call reasoning is fully general | Sound for a single Node.js process (no await inside the critical section, so no interleaving window); says nothing about multi-instance scaling, but that's moot since assertSqliteMode() blocks Fabric mode entirely today | Confirmed sound by inspection for the mode this module actually supports |

### Invariant Coverage Gaps
| Invariant | Enforcement point touched | Tested |
|-----------|--------------------------|--------|
| S1 | documents.ts never imports matchingInvocation.ts | Yes — structural + behavioral |
| G5 | acquireMatchingLock/releaseMatchingLock via recon_document_lock's PRIMARY KEY | Partial — core mutual-exclusion mechanic verified, but abandoned-lock recovery, error/contention conflation, and referential integrity were all gaps |

### Known Untested Scenarios (out of scope — not findings)
- Real deterministic/AI matching logic — Task 5.2/5.3's job, matchDocumentStub() is a deliberate no-op this task
- No live cron/timer invokes run-batch — documented Decision Log entry
- Fabric-mode behavior — assertSqliteMode() blocks it, same precedent as Task 2.4
- True OS-level multi-process concurrency — different deployment topology than this bounded build's sandbox target

### Structural Complexity Check
CLEAN across all functions in matchingInvocation.ts.

### Challenge Verdict
FINDINGS — 3 item(s) require engineer disposition before commit.
```

### Code Review
S1 and G5 reviewed against the challenge output.

### Scope Decisions

**Finding 1 (abandoned lock has no recovery) + Finding 2 (error/contention conflation)** —
FIXED together. `acquireMatchingLock()` rewritten from a plain INSERT-and-catch-conflict
pattern to a single atomic UPSERT (`INSERT ... ON CONFLICT(document_id) DO UPDATE ... WHERE
acquired_at < datetime('now', '-10 minutes')`), checked via `result.changes === 1`. This
simultaneously: (a) makes a lock older than 10 minutes reclaimable (closing the
abandoned-lock gap), and (b) means any non-conflict DB error now throws rather than being
silently reported as "already held" (the UPSERT either succeeds, no-ops with
`changes === 0`, or throws — there is no longer a catch block that could conflate the two).
Verified via new TC-7 (a backdated lock is reclaimable) and TC-8 (a fresh lock is not).

**Finding 3 (no FK on the lock table)** — FIXED. Added
`document_id REFERENCES extracted.document(document_id)` (T-SQL) /
`extracted_document(document_id)` (SQLite) to `recon.document_lock`, matching every other
document-linking column in this schema. Verified via new TC-9.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (FINDINGS)
[x] All FINDINGS dispositioned (3 fixed)
[x] Pre-commit declaration recorded
[x] Code review complete (S1, G5)
[x] Scope decisions documented

**Status:** Completed

---

## Task 5.2 — Deterministic matching (SQL-based)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | StatementLine with a matching NetSuite Bill document number | Produces a Match record, with `reference_run_id`/`reference_extracted_at`/`reference_source_system` populated from the specific NetSuite row matched | N/A | PASS |
| TC-2 | StatementLine with no corresponding NetSuite record | Produces an Exception (category e.g. `NOT_POSTED`), with the same 3 reference columns populated | N/A | PASS |
| TC-3 | Attempt to write a Match with any of the 3 reference columns null | Rejected — INVARIANT TOUCH: S8 (amended) | N/A | PASS |
| TC-4 | Matching logic execution | Never makes a live NetSuite/CCC API call | N/A | PASS |

Plus TC-5/TC-6 (amount-mismatch outcome, `writeMatch` FK rejection), and 4 more added
during this task's challenge review (TC-7–TC-10 below). 19/19 checks pass via
`./scripts/test_deterministic_matching.sh`.

**Scope Decisions made during this task's own build (not fixes, documented up front):**
1. Task 5.2's own spec names only 2 outcomes (matched / NOT_POSTED), but
   `recon.exception.category`'s enum also includes `amount_mismatch`, and UI_SURFACE.md's
   Exception Detail screen expects an amount-mismatch drill-down from
   `recon.exception.evidence`. No other task produces `amount_mismatch` — extended
   deterministic matching to compare amounts once a doc-number match is found (within
   tolerance → Match; outside → unmatched with reason `AMOUNT_MISMATCH`), the only way this
   category is reachable at all.
2. For a NOT_POSTED case, S8 (amended) requires capturing "what state of NetSuite data was
   checked" even though nothing matched. Interpreted as: capture the reference table's own
   most-recently-extracted row overall (`ORDER BY _extracted_at DESC LIMIT 1`) — answering
   "what was the data's state as of this check" in the absence of a specific matched row.
3. `recon.exception.evidence` (not in Task 1.2's original schema) added via migration 005 —
   read back by UI_SURFACE.md's Exception Detail screen.

### Challenge Agent Output

```
## Challenge Agent — Task 5.2

### Untested Scenarios
| # | Scenario | Why it matters | Invariant/requirement at risk |
|---|----------|----------------|-------------------|
| 1 | Case/whitespace mismatch between Silver's normalized_invoice_ref and bill_document_number read raw, no normalization/collation applied on the read side | Every fixture row in every test seeded already-matching case — a real NetSuite row stored differently-cased would silently fall through to NOT_POSTED even though a true match exists | Core recon-key correctness; indirectly S8 |
| 2 | Duplicate bill_document_number values across multiple rows (structurally possible — PK is transaction_id) | findReferenceRowByDocNumber used bare .get() with no ORDER BY/tie-break; which row's S8 data got captured was arbitrary | S8 — reproducibility capture could be non-deterministic |
| 3 | End-to-end AMOUNT_MISMATCH path through runMatchingForDocument -> writeException -> recon_exception | TC-5 only unit-tested matchStatementLine directly; no test confirmed the category/reference columns land correctly through the full pipeline | Task 5.2/5.4 wiring correctness |
| 4 | NOT_POSTED capture when bronze_netsuite_vendorbill has zero rows total | TC-1's seed row was already present by the time TC-2 ran, so the true-empty-table null-capture branch was never hit | S8's "what state was checked" guarantee, true-empty case |

### Unverified Assumptions
| # | Assumption in code | Basis | Testable within task scope |
|---|--------------------|-------|---------------------------|
| 1 | bill_document_number is stored in the same casing/trim convention as Silver's normalized ref | No normalization/COLLATE NOCASE applied on the read side | Yes — differently-cased fixture row |
| 2 | bill_document_number is effectively unique in practice | No uniqueness enforced in the fixture or production table description | Yes — seed two rows, same doc number |
| 3 | A NOT_POSTED exception's watermark being "most recent row overall" is acceptable even for a genuinely empty table | Interpretation stated as a Scope Decision; its all-null edge case untested | Yes — run against a zero-row table |

### Invariant Coverage Gaps
| Invariant | Enforcement point touched | Tested |
|-----------|--------------------------|--------|
| S8 (amended) | findReferenceRowByDocNumber, findLatestReferenceWatermark, writeMatch, writeException | Partial — matched-row capture and no-row-found-against-a-non-empty-table capture tested; NOT NULL enforcement on Match tested. Not tested: true-empty-table watermark, duplicate-doc-number tie-break, case/whitespace false-negative risk. |

### Known Untested Scenarios (out of scope — not findings)
- G5 concurrent-lock behavior — owned and tested by Task 5.1
- Live Claude API call path in residual matching — Task 5.3's own test file
- Real bronze.netsuite_vendorbill production schema/casing — requires live Fabric access
- CCC corroboration-found path — Task 5.3's own fixture/tests

### Structural Complexity Check
CLEAN across deterministicMatching.ts and matchingPipeline.ts (one borderline-but-fine 2-level nesting noted in runMatchingForDocument, a narrow defensive guard not branching logic).

### Challenge Verdict
FINDINGS — 4 item(s) require engineer disposition before commit.
```

### Code Review
S8 (amended) reviewed against the challenge output.

### Scope Decisions

**Finding 1 (casing/whitespace false-negative risk)** — FIXED.
`findReferenceRowByDocNumber`'s SQL now applies `UPPER(TRIM(bill_document_number))` on the
read side, matching Silver's own trim+uppercase normalization, so a real-world casing or
whitespace difference no longer produces a false NOT_POSTED. Verified via new TC-7.

**Finding 2 (duplicate doc-number tie-break)** — FIXED. Added
`ORDER BY _extracted_at DESC LIMIT 1` to the same query, so duplicate
`bill_document_number` rows resolve deterministically to the most-recently-extracted one,
not an arbitrary row. Verified via new TC-8.

**Finding 3 (AMOUNT_MISMATCH untested end-to-end)** — FIXED (test coverage; the pipeline
wiring was already correct). Added TC-9, driving a genuine amount mismatch through
`triggerMatchingForDocument` and confirming the resulting `recon_exception` row's category
and reference columns.

**Finding 4 (true-empty-table watermark untested)** — FIXED (test coverage; the null-return
branch was already correct). Added TC-10, temporarily clearing the fixture table (restored
after) to confirm a NOT_POSTED outcome against a genuinely empty reference table leaves
`reference: null` rather than fabricating a watermark.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (FINDINGS)
[x] All FINDINGS dispositioned (4 fixed)
[x] Pre-commit declaration recorded
[x] Code review complete (S8)
[x] Scope decisions documented

**Status:** Completed

---

## Task 5.3 — AI-assisted residual matching (never auto-approves)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Residual line with CCC RO corroboration | Produces an actionable exception category with a specific suggested action, but is NOT marked as an approved match | N/A | |
| TC-2 | Any code path from this pass | No path allows directly setting a final "matched"/"reconciled" status without deterministic confirmation — INVARIANT TOUCH: AI-write-authority non-negotiable | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: G3; AI-write-authority non-negotiable.

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

## Task 5.4 — Exception category enum + schema wiring

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Every exception-producing path | Writes a valid enum category | N/A | |
| TC-2 | Attempt to write an unrecognized category string | Rejected — INVARIANT TOUCH: S5 | N/A | |
| TC-3 | Any exception created | `owner`/`aging_started_at`/`run_reference` remain NULL | N/A | |
| TC-4 | NOT_POSTED exception (Task 5.2's no-match path) | Carries non-NULL `reference_run_id`/`reference_extracted_at`/`reference_source_system` | N/A | |
| TC-5 | Arithmetic-mismatch exception (Task 3.2) | Leaves the 3 reference columns NULL — never touched reference data | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: S5; S8 (amended).

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
