

## 1. Document invariants

These protect the integrity of uploaded statements.

### D1. A document's content hash is immutable

Once a PDF is registered:

```text
document_id → content_sha256
```

the hash must never change.

If the file changes, it is a **new document/version**, not an update to the existing document.

### D2. Same content cannot be processed twice

```text
UNIQUE(content_sha256)
```

Therefore:

> One physical PDF content → at most one registered document.

The architecture explicitly makes SHA-256 the primary idempotency mechanism. 

### D3. A corrected statement cannot overwrite the old statement

If vendor sends:

```text
June statement v1
June statement v2
```

then:

```text
v1.superseded_by = v2
v1 remains immutable
```

The reconciliation result associated with v1 must remain available. 

### D4. Every reconciliation-eligible document must be registered

You should never have:

```text
statement_line → document that doesn't exist
```

### D5. Document status must represent a valid lifecycle state

For example:

```text
Received
→ Validating
→ Ready
→ Assigned to Run
→ Processed
```

or terminal/problem states such as:

```text
Duplicate
Invalid
Needs Metadata
Needs Classification
Superseded
```

No arbitrary status should exist outside the state machine. 

---

# 2. Extraction invariants

These are particularly important because bad extraction can create fake financial discrepancies.

### E1. Every extraction attempt belongs to exactly one document

```text
ExtractionAttempt.document_id → valid Document
```

### E2. Extraction attempts are append-only

You don't modify:

```text
attempt 1
```

after the fact.

Instead:

```text
Document X
 ├── Attempt 1
 └── Attempt 2
```

The Bronze layer retains every attempt. 

### E3. Maximum extraction attempts = 2

If arithmetic validation fails:

```text
attempt 1 → retry
attempt 2 → if failure → OCR_LOW_CONFIDENCE
```

Never:

```text
attempt 1 → 2 → 3 → 4 → ...
```

### E4. Arithmetic invariant

For every valid statement:

```text
Σ extracted_line.amount
    = statement.stated_total
```

within whatever formally defined arithmetic tolerance applies.

This is explicitly a mandatory gate. 

### E5. Structural validity invariant

A line promoted to Silver must satisfy required structural constraints:

```text
required fields present
AND dates parse
AND amounts numeric
AND confidence >= floor
```

### E6. Invalid extraction cannot silently enter Silver

If:

```text
arithmetic_failed
OR structural_validation_failed
OR confidence_below_floor
```

then:

```text
NOT eligible for Silver
```

### E7. Bronze must contain the extraction attempt before validation decides its fate

This is important for auditability:

```text
Extraction
   ↓
Bronze write
   ↓
Validation
```

not:

```text
Extraction
   ↓
Validation
   ↓
Bronze only if successful
```

The architecture explicitly says Bronze records every attempt, including failures. 

---

# 3. Statement-line invariants

### S1. Every StatementLine belongs to exactly one statement

```text
statement_line.statement_id
```

must always reference a valid statement.

### S2. Every StatementLine belongs to exactly one document/version

This is critical for traceability.

```text
statement_line
 → statement
 → document
 → document_version
```

### S3. Statement-line amounts are immutable after extraction

If extraction produces:

```text
$1,250
```

you shouldn't silently change it to:

```text
$1,200
```

Instead, a new extraction/version should explain where the new value came from.

### S4. Silver contains normalized data

Normalization must happen **before matching**, not dynamically during matching. This is explicitly D8. 

---

# 4. Reference-data invariants

The biggest one:

### R1. Matching never calls NetSuite or CCC directly

The matching service can only use:

```text
Silver
```

not:

```text
NetSuite live API
CCC live API
```

This guarantees reproducibility. 

### R2. Every match references a specific snapshot

A match must know:

```text
netsuite_snapshot_version
ccc_snapshot_version
```

So historical matching can answer:

> "What data did we actually use when making this decision?"

### R3. Frozen snapshots cannot change

Once a Run freezes:

```text
NetSuite snapshot
CCC snapshot
```

they must remain immutable. 

### R4. Historical matches must never depend on today's ERP state

If NetSuite changes tomorrow, yesterday's reconciliation result must not magically change.

---

# 5. Reconciliation Run invariants

These are some of the most important system-level invariants.

### RUN1. Every Work Item belongs to exactly one Run

```text
statement_work_item.run_id → reconciliation_run
```

### RUN2. A Run has immutable scope after freeze

Scope includes things like:

```text
legal entity
period
vendor scope
AP cutoff
document set
```

Once frozen:

> The Run's scope cannot silently change.



### RUN3. A document arriving after freeze cannot enter an existing Run

It must go into:

```text
supplementary run
```

or:

```text
new run
```

### RUN4. Run configuration is immutable

A Run should permanently know:

```text
rule_version
prompt_version
model_version
netsuite_snapshot_version
ccc_snapshot_version
```

### RUN5. Run idempotency

The architecture defines the Run idempotency key as:

```text
legal_entity
+ period
+ run_type
+ ap_cutoff
```

Therefore, the same logical Run request should not accidentally create duplicate Runs. 

### RUN6. Re-running must never overwrite previous results

Instead:

```text
Version 1
   ↓
Version 2
   ↓
Version 3
```

Each version remains queryable. 

### RUN7. A failure in one Work Item cannot corrupt other Work Items

If:

```text
Work Item A = success
Work Item B = extraction failure
Work Item C = success
```

the entire Run should not become globally corrupted.

The expected outcome is something like:

```text
Completed with Exceptions
```

not:

```text
Entire Run = Failed
```



---

# 6. Matching invariants

This is probably the most important category.

### M1. Matching is deterministic-first

The ordering must remain:

```text
P1 Exact
   ↓
P2 Rules
   ↓
P3 AI
   ↓
Exception
```

AI cannot jump ahead and override deterministic matching. 

### M2. P3 cannot invent a candidate

If SQL retrieves:

```text
Bill A
Bill B
Bill C
```

Claude can only choose among:

```text
A / B / C
```

It cannot invent:

```text
Bill X
```

The application rejects candidate IDs outside the supplied candidate set. 

### M3. P3 is never auto-approvable

Even:

```text
confidence = 0.999
```

doesn't matter.

If:

```text
match_method = P3
```

then:

```text
human_review_required = TRUE
```

This is a permanent architectural invariant. 

### M4. AI cannot directly change financial state

The fundamental invariant:

```text
AI → recommendation
Human → approval
```

never:

```text
AI → financial write
```

The requirements explicitly make this a permanent non-negotiable. 

---

# 7. The strongest matching invariant: one bill → one statement line

The architecture explicitly requires:

```text
netsuite_bill_id UNIQUE
```

Therefore:

> A NetSuite bill can satisfy at most one statement line across all statements.

Example:

```text
Statement A
  INV-123 → Bill 999

Statement B
  INV-456 → Bill 999   ❌
```

The second attempt becomes:

```text
POSSIBLE_DUPLICATE
```



This is a **hard database invariant**, not merely application logic.

---

# 8. Duplicate/reconciliation invariants

### DUP1. Same vendor + invoice + amount appearing again must be detectable

Cross-statement duplicate detection must identify repeated financial lines. 

### DUP2. Different content does not automatically mean different business statement

This is important.

Two PDFs can have:

```text
different hashes
same vendor
same period
same entity
```

You cannot automatically assume:

> "They're both valid."

The bounded build specifically flags this as possible duplicate/correction rather than silently processing both. 

### DUP3. A legitimate correction must preserve the original

Never delete the old reconciliation simply because a corrected statement arrived.

---

# 9. Exception invariants

### EX1. Every unresolved line must have an explicit exception state

No:

```text
statement line = unmatched
```

with no explanation.

It should become:

```text
Exception
 + category
 + reason
 + evidence
```

### EX2. Exception must belong to a Work Item / Run

In the full architecture:

```text
exception
 → work_item
 → run
 → document
 → statement
 → line
```

### EX3. Exception history is append-only

If exception changes:

```text
OPEN
→ ASSIGNED
→ IN_REVIEW
→ RESOLVED
```

the old states must remain in history.

The architecture has a dedicated `exception_history` table for this. 

### EX4. Exception aging cannot be silently reset

If an exception is reassigned, you shouldn't accidentally reset:

```text
created_at
aging_start
```

unless the business rule explicitly says so.

---

# 10. Evidence invariants

### EV1. Every match must have explainable evidence

A match isn't just:

```text
match_score = 0.94
```

It should retain the individual evidence components.

For example:

```text
invoice_match = true
vendor_match = true
amount_match = true
RO_match = true
```

The architecture explicitly says every scoring component is stored. 

### EV2. Every AI decision retains its raw structured output

If Claude says:

```json
{
  "candidate_ap_record_id": "AP-912",
  "confidence": 0.94
}
```

that output must be preserved.

### EV3. Evidence cannot be modified to justify a later decision

Historical evidence should be immutable.

---

# 11. Approval invariants

These apply to the **full v3.3 target**, not the bounded first-build slice.

### A1. AI can never be an approver

```text
approver != AI
```

### A2. Preparer cannot approve their own work

```text
preparer_id != approver_id
```

This is the segregation-of-duties invariant. 

### A3. High-dollar approvals require two humans

If:

```text
amount > configured_threshold
```

then:

```text
approval_count >= 2
```

and the second approver must be a different authorized human.

### A4. Cannot approve an invalid/failed match

For example:

```text
AI_OUTPUT_INVALID
OCR_LOW_CONFIDENCE
AMBIGUOUS
```

cannot accidentally transition to approved without the required human workflow.

### A5. Approval is tied to the exact version

If:

```text
Work Item v1
```

was approved, then:

```text
Work Item v2
```

created through re-match must **not inherit that approval automatically**.

This follows directly from the versioning model.

---

# 12. Optimistic concurrency invariants

This is where `ROWVERSION` matters.

### C1. Every mutable Match has a version

```text
match.rowversion
```

### C2. Every mutable Exception has a version

```text
exception.rowversion
```

### C3. Stale writes must fail

Suppose:

```text
User A reads version 5
User B reads version 5

User A updates → version 6
User B updates version 5 → ❌
```

User B must get a concurrency conflict, not overwrite User A.

The database enforces this with `ROWVERSION`. 

### C4. Bulk approval must check every row

A bulk approval cannot simply say:

```text
UPDATE matches SET approved = 1
```

It must verify each row's expected version.

If one changed:

```text
exclude it
report conflict
```

rather than silently overwriting it. 

---

# 13. Audit invariants

These are absolutely critical for a financial system.

### AUD1. Every financial decision produces an audit record

```text
automatic decision → audit
human decision → audit
override → audit
approval → audit
rejection → audit
```

### AUD2. Audit ledger is append-only

Never:

```text
UPDATE audit_ledger
DELETE audit_ledger
```

### AUD3. Audit records identify the exact decision context

An audit record should retain:

```text
run_id
work_item_id
document_id
document_version
statement_line_id

source values
extracted values

candidate records
rules evaluated

AI model
AI prompt version
AI output
confidence

human decision
reviewer
timestamp

final status
```

The architecture explicitly defines this structure. 

### AUD4. Technical logs cannot replace financial audit

OpenTelemetry tells you:

> "What did the service do?"

Audit ledger tells you:

> "What financial decision was made, using what evidence, and who approved it?"

Those are separate invariants/responsibilities. 

---

# 14. Historical immutability invariants

These are extremely important.

### H1. Completed reconciliation results cannot be overwritten

### H2. Previous Work Item versions remain queryable

```text
v1 → v2 → v3
```

all remain.

### H3. Frozen snapshots remain queryable

### H4. Audit records remain queryable

### H5. Original PDF remains immutable

The architecture explicitly treats the original Blob PDF as the genuinely irreplaceable artifact. 

### H6. `recon` cannot be rebuilt like Gold

This is a major architectural invariant:

```text
gold → rebuildable
recon → NOT rebuildable
```

because rebuilding recon could destroy workflow/approval history. 

---

# 15. Normalization invariants

### N1. Same logical identifier must normalize consistently

For example:

```text
INV-00123
INV 00123
inv00123
```

should resolve to the same normalized representation if the normalization rules say they are equivalent.

### N2. Matching cannot apply ad-hoc normalization

Normalization should happen in Silver.

Otherwise two matching workers could potentially use different normalization behavior.

### N3. Normalization version must be traceable

If normalization rules change, historical matching should still tell you which normalization logic was used.

---

# 16. Tolerance invariants

### T1. Tolerance must be explicit

For example:

```text
max($5, 0.5%)
```

not:

```text
"close enough"
```

### T2. Absorbed variance must be recorded

If:

```text
invoice = $1000
statement = $1003
tolerance = $5
```

then the $3 difference isn't invisible.

It must be recorded.

### T3. Tolerance cannot silently become approval

Tolerance is evidence for a deterministic decision, not a mechanism for hiding differences.

---

# 17. Reporting invariants

### REP1. Reporting must not modify reconciliation state

```text
Gold/reporting
      ↓
read only
      ↓
Recon
```

not the other way around.

### REP2. Reporting cannot directly become the authoritative financial state

`recon` remains authoritative.

### REP3. Gold can be rebuilt without affecting Recon

This is one of the reasons they're separated. 

### REP4. Reporting should not compete with live AP transactional workload

The target architecture uses materialized Gold + Power BI import to isolate reporting load. 

---

# 18. Security invariants

### SEC1. No local application accounts

Authentication is through:

```text
Entra ID
```

### SEC2. Users can only access authorized shops/entities

The target architecture explicitly requires shop-scoped row-level authorization in the data access layer. 

### SEC3. AI has no financial write permission

This should ideally be enforced technically through identity/permissions, not just application code.

### SEC4. Matching service has no reason to call live ERP

Therefore its credentials/identity should not have live NetSuite/CCC mutation capability.

### SEC5. Financial decisions require an identifiable actor

Every human action:

```text
who
when
what
before
after
```

must be attributable.

---

# 19. Prompt/AI invariants

### AI1. Statement content is data, not instructions

Extracted document content must be passed as a parameter to a fixed prompt template, rather than concatenated into instructions.

### AI2. AI output must conform to schema

For P3:

```text
decision ∈ allowed enum
confidence ∈ [0,1]
candidate_id ∈ retrieved candidates
reason_codes ∈ approved library
review_required = true
```

### AI3. Invalid AI output becomes an exception

It must not crash the whole work item or accidentally drive an accounting action. 

### AI4. AI-generated free text cannot directly cause a financial action

Structured validated fields only.

---

# 20. Service/idempotency invariants

Every worker should have a stable idempotency key.

| Service      | Invariant key                                              |
| ------------ | ---------------------------------------------------------- |
| Discovery    | `content_sha256`                                           |
| Extraction   | `document_id + attempt_no`                                 |
| Validation   | `document_id + normalization_version`                      |
| Run Creation | `legal_entity + period + run_type + ap_cutoff`             |
| Freeze       | `run_id`                                                   |
| Matching     | `statement_line_id + snapshot_version + work_item_version` |
| Re-match     | `work_item_id + version`                                   |

These are explicitly specified in the service-boundary design. 

The general invariant is:

> **Retrying the same operation must not create an unintended second business effect.**

---

# 21. Period/accounting invariants

### P1. Statement date determines accounting period

A June statement arriving July 3 is still:

```text
June
```

not July.

The architecture explicitly calls this out. 

### P2. Run period must match the documents included

A June Run shouldn't silently include July statements.

### P3. Snapshot cutoff must correspond to the Run

You should always be able to answer:

> "Which ERP state did this Run reconcile against?"

---

# 22. State-machine invariants

You can formalize these as:

```text
Document
Received
   ↓
Validating
   ↓
Ready
   ↓
Assigned
   ↓
Processed
```

and forbid illegal transitions such as:

```text
Processed → Received        ❌
Duplicate → Assigned       ❌
Invalid → Processed        ❌
Superseded → Active        ❌
```

unless a deliberately defined correction/reprocessing operation creates a new version.

Same principle applies to:

```text
Run
WorkItem
Exception
Approval
```

---

# 23. Cross-entity referential invariants

Because `recon` is on SQL database in Fabric, you can enforce real FK relationships.

Examples:

```text
match.run_id → run.id
match.work_item_id → work_item.id
exception.run_id → run.id
exception.work_item_id → work_item.id
work_item.document_id → document.id
work_item.statement_id → statement.id
match.rule_id → rule_library.id
```

The architecture specifically chose SQL database in Fabric because it provides real FK enforcement and transactional guarantees. 

---

# 24. The "big 15" invariants I'd absolutely put into tests

If you're asking this from a **system-design/interview/testing perspective**, you don't need to list 100 things. These are the core invariants I'd make explicit:

| #      | Invariant                                                                         |
| ------ | --------------------------------------------------------------------------------- |
| **1**  | Same PDF content cannot be processed twice — `content_hash` unique                |
| **2**  | Original document/version is immutable                                            |
| **3**  | Every extracted statement passes arithmetic/structural validation before Silver   |
| **4**  | Every Run has frozen, immutable inputs                                            |
| **5**  | Matching never calls NetSuite/CCC live                                            |
| **6**  | Every match references exact ERP snapshot/version                                 |
| **7**  | One NetSuite bill can match at most one statement line                            |
| **8**  | AI can never auto-approve or write financial state                                |
| **9**  | P3 AI can only choose from SQL-retrieved candidates                               |
| **10** | Re-match creates a new version; it never overwrites the old result                |
| **11** | Audit ledger is append-only                                                       |
| **12** | Historical evidence/snapshots/decisions remain immutable                          |
| **13** | Concurrent stale updates are rejected using `ROWVERSION`                          |
| **14** | Preparer cannot approve their own work; high-dollar items require second approval |
| **15** | Gold/reporting rebuilds can never destroy or modify `recon`                       |

And there is one **very important meta-invariant** underneath all of them:

> **The system must always be able to reconstruct why a particular financial reconciliation decision exists, using the exact document version, statement line, reference snapshot, matching rules, model/prompt versions, evidence, and human decision that produced it.**

That is really the central invariant of the whole architecture. The audit ledger and frozen snapshots are specifically designed to preserve that chain. 

**One caveat:** some of these belong to the **full v3.3 target architecture**, while the currently bounded first build explicitly defers Runs, approvals, `ROWVERSION`, and the permanent audit ledger. The first-build architecture calls those out as deliberate deferrals.  
