**Session:** Session 3 — Extraction Service
**Date:** 2026-08-27
**Engineer:** Vaishali

## Task 3.1 — Vendor identification, extraction routing, and attempt recording

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Document matching a registered vendor's signature | Routes to deterministic pdfplumber path, lands in that vendor's `extracted.stmt_<vendor_slug>` | N/A | |
| TC-2 | Document from a vendor not in registry | Routes to Claude-primary path without error, provisional vendor record created | N/A | |
| TC-3 | Successful extraction | Writes one attempt row, `arithmetic_pass=true`, `document.vendor_id`/`statement_period` populated | N/A | |
| TC-4 | Failed extraction (arithmetic mismatch) | Still writes an attempt row, `arithmetic_pass=false`, BEFORE retry logic fires — INVARIANT TOUCH: S10 | N/A | |
| TC-5 | Modify an existing attempt row via application layer | Fails — INVARIANT TOUCH: G1 | N/A | |
| TC-6 | Different document, same vendor/period/entity (now known) | Version-chained — `is_latest_version` flip, `previous_statement_id` set, no human flag — INVARIANT TOUCH: S2 | N/A | |
| TC-7 | Two documents, same vendor/period | Never both show `is_latest_version = true` | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
[Required — S10, G1, S2.]

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

## Task 3.2 — Arithmetic and structural validation gate

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Lines sum correctly, valid dates/amounts | Eligible for matching, regardless of confidence | N/A | |
| TC-2 | Lines sum incorrectly | Not eligible, triggers retry path | N/A | |
| TC-3 | Line missing invoice_number, no ro_number fallback | Not eligible, triggers retry path | N/A | |
| TC-4 | Low-confidence but structurally/arithmetically valid | Proceeds to Silver | N/A | |
| TC-5 | Blank-amount (credit/payment) line, valid invoice_number | Reaches Silver, not diverted | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: G2 (amended).

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

## Task 3.3 — Bounded retry logic (max 2 attempts, then OCR_LOW_CONFIDENCE)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Attempt 1 fails, attempt 2 succeeds | Proceeds to matching-eligible | N/A | |
| TC-2 | Attempt 1 fails, attempt 2 fails | Flagged `OCR_LOW_CONFIDENCE`, no 3rd attempt — INVARIANT TOUCH: S7 | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: S7.

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

## Task 3.4 — Prompt injection defense (data vs. instructions)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Normal statement content | Extracts correctly | N/A | |
| TC-2 (security) | PDF containing instruction-like text ("ignore previous instructions...") | Does not deviate from normal extraction — injected text extracted as data — INVARIANT TOUCH: G3 | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: G3 (GLOBAL).

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

## Task 3.5 — Extraction-method summary endpoint

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Document extracted entirely via claude_sonnet | Summary with only that key populated | N/A | |
| TC-2 | Document with some pdfplumber-fallback rows | Both providers shown with correct counts | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: None new (relies on Task 3.1/3.2's provider field).

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

## Task 3.6 — Silver normalization (`extracted` → `silver.statement_line`)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Document passes validation gate | Produces one or more `silver.statement_line` rows | N/A | |
| TC-2 | Document fails validation | Produces zero `silver.statement_line` rows | N/A | |
| TC-3 | Any produced row | Tagged with normalization logic version — INVARIANT TOUCH: S6 | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: S6.

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
