# VIVE Edge Cases — Consolidated

## 1. Authentication & Access

| Edge case                                      | Handling                                                               |
| ---------------------------------------------- | ---------------------------------------------------------------------- |
| **Login/authentication fails**                 | Show clear error; no application state is created or modified.         |
| **Authenticated but unauthorized**             | Return `403`; expose no reconciliation data.                           |
| **Session expires during an action**           | Require re-authentication; don't repeat or partially apply the action. |
| **User opens stale/duplicate browser session** | Server-side state/version checks prevent stale updates.                |

**Covers:** admin unable to log in, expired sessions, multiple tabs, unauthorized access.

---

# 2. Upload & Document Integrity

| Edge case                                           | Handling                                                |
| --------------------------------------------------- | ------------------------------------------------------- |
| **Invalid/unreadable file**                         | Mark `CANNOT_PROCESS`; show reason to operator.         |
| **File is incomplete while being uploaded**         | Don't process until upload is complete/stable.          |
| **Same content uploaded again**                     | SHA-256 detects duplicate; don't re-extract.            |
| **Different content but same vendor/period/entity** | Flag possible duplicate/correction for human decision.  |
| **Missing/ambiguous metadata**                      | `NEEDS_METADATA` / `NEEDS_CLASSIFICATION`; don't guess. |
| **Corrected statement received**                    | Create new document/version; preserve previous result.  |

This covers corrupt PDFs, wrong extensions, duplicate filenames, duplicate PDFs, missing entity/vendor/period, and corrected statements without having a separate edge case for every file format.

The architecture already treats the database document registry as the status source of truth and uses content hashing for duplicate discovery.  

---

# 3. Extraction & OCR

| Edge case                                                | Handling                                                               |
| -------------------------------------------------------- | ---------------------------------------------------------------------- |
| **Claude unavailable / timeout / transient failure**     | Retry safely.                                                          |
| **Claude returns malformed or incomplete output**        | Reject extraction and retry.                                           |
| **Arithmetic/structural validation fails**               | Retry once.                                                            |
| **Second extraction still fails**                        | `OCR_LOW_CONFIDENCE`; human review.                                    |
| **Document content attempts prompt injection**           | Treat extracted content strictly as data; never as instructions.       |
| **Worker fails after extraction but before persistence** | Idempotency allows safe retry without duplicating the business result. |

So instead of separately tracking "bad date", "bad amount", "missing field", "malformed JSON", etc., they all fall under **invalid extraction output**.

The arithmetic, structural, and confidence gates are already defined in the architecture. 

---

# 4. Matching

This is the most important group.

| Edge case                                  | Handling                                                                               |
| ------------------------------------------ | -------------------------------------------------------------------------------------- |
| **No candidate found**                     | `MATCH_NOT_FOUND` → human review.                                                      |
| **Multiple plausible candidates**          | `AMBIGUOUS_MATCH` → show candidates; human selects.                                    |
| **Candidate fails deterministic checks**   | Exception; don't force a match.                                                        |
| **Amount/date/vendor/invoice discrepancy** | Apply configured matching rules/tolerance; otherwise exception.                        |
| **Same NetSuite bill already matched**     | Reject second match / `POSSIBLE_DUPLICATE`.                                            |
| **Matching data unavailable or stale**     | Don't guess or fall back silently; wait for valid Silver snapshot or trigger re-match. |
| **AI produces invalid/invented candidate** | Reject AI output; it may only select from supplied candidates.                         |

This collapses many of the previous cases into the actual matching decision types.

The architectural principle is explicitly:

> **Decline to guess. A clean exception beats a confident wrong match.** 

And the one-bill/one-line constraint is explicitly enforced. 

---

# 5. Live NetSuite / CCC Verification

Since you mentioned wanting this feature, I'd give it its **own category**.

| Edge case                                            | Handling                                                                            |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **User requests live lookup**                        | Allow explicit live verification.                                                   |
| **Live API unavailable**                             | Show "Live verification unavailable"; existing reconciliation remains unchanged.    |
| **Live result differs from reconciliation snapshot** | Show both values and identify the snapshot/live distinction.                        |
| **Live lookup finds a record absent from snapshot**  | Treat as new evidence; require explicit re-match/correction.                        |
| **User wants to use live result**                    | Create explicit re-match/correction action; don't silently mutate historical match. |

The important invariant is:

> **Live ERP data may supplement a reconciliation decision, but cannot silently modify the authoritative historical result.**

This lets you have a useful **"Check NetSuite Live"** button without breaking reproducibility.

---

# 6. Exception Management

| Edge case                                  | Handling                                                            |
| ------------------------------------------ | ------------------------------------------------------------------- |
| **Exception has invalid/missing category** | Reject; category must use approved enum.                            |
| **Exception cannot currently be resolved** | Leave `OPEN`; retain reason/evidence.                               |
| **Exception is resolved twice**            | State transition/idempotency check prevents duplicate resolution.   |
| **Another process/user resolves it first** | Reject stale update; show latest state.                             |
| **User wants to reverse a decision**       | Create an explicit correction/reversal rather than erasing history. |

That's enough. We don't need separate cases for "user clicks save and network fails", "user clicks twice", "two tabs", etc.—those are manifestations of **idempotency/concurrency**, which belong in the implementation invariant rather than the business edge-case catalog.

---

# 7. Run & Processing

| Edge case                                      | Handling                                                           |
| ---------------------------------------------- | ------------------------------------------------------------------ |
| **No eligible documents**                      | Don't execute; show empty run.                                     |
| **Some documents are invalid/excluded**        | Show them during Run Preview; continue with eligible documents.    |
| **Same Run submitted twice**                   | Run idempotency returns the existing Run.                          |
| **Document arrives after Run scope is frozen** | Exclude from existing Run; process in later/supplementary Run.     |
| **One Work Item fails**                        | Continue remaining Work Items.                                     |
| **Worker crashes / item remains processing**   | Lease/reaper detects stale processing and retries or marks failed. |
| **Run partially succeeds**                     | Complete with exceptions; preserve individual Work Item outcomes.  |

The architecture explicitly separates Run-level outcome from individual Work Item failure. 

---

# 8. NetSuite / CCC Ingestion

| Edge case                                    | Handling                                                                        |
| -------------------------------------------- | ------------------------------------------------------------------------------- |
| **API timeout/rate limit/temporary failure** | Retry with backoff.                                                             |
| **Authentication failure**                   | Stop source ingestion and alert; don't publish incomplete data.                 |
| **Malformed/schema-changed response**        | Reject/quarantine ingestion; don't promote invalid data.                        |
| **Partial/paginated response**               | Don't mark snapshot complete until completeness checks pass.                    |
| **Duplicate records**                        | Deduplicate using source identity.                                              |
| **One source succeeds while another fails**  | Track source freshness independently; don't represent failed source as current. |
| **Ingestion runs twice**                     | Idempotent ingestion prevents duplicate records.                                |

These can all be treated as **source ingestion failure/incomplete snapshot**, rather than 10 different edge cases.

The architecture defines NetSuite/CCC as daily ingestion into Bronze → Silver and keeps matching downstream of that boundary. 

---

# 9. Database / Infrastructure Failure

| Edge case                                 | Handling                                                                  |
| ----------------------------------------- | ------------------------------------------------------------------------- |
| **Database unavailable**                  | Retry safe operations; don't acknowledge work until persistence succeeds. |
| **Transaction partially fails**           | Roll back; no partial business state.                                     |
| **Request succeeds but response is lost** | Idempotency makes client retry safe.                                      |
| **Worker crashes during processing**      | Lease/retry mechanism recovers it.                                        |
| **Duplicate queue message**               | Idempotency key prevents duplicate business effect.                       |
| **Concurrent update**                     | Ownership/version check rejects stale or competing update.                |

This one category replaces a large number of low-level failure permutations.

---

# 10. Reporting

| Edge case                                        | Handling                                                                         |
| ------------------------------------------------ | -------------------------------------------------------------------------------- |
| **Report refresh fails**                         | Keep last successful ReportView and expose freshness/error state.                |
| **Report is empty**                              | Distinguish "zero records" from "refresh failed".                                |
| **Report is behind reconciliation**              | Display reporting timestamp/cutoff.                                              |
| **Report data disagrees with reconciliation UI** | Identify snapshot/version mismatch; don't modify recon to make the report agree. |
| **Reporting becomes expensive**                  | Keep reporting against ReportView/Gold, not transactional `recon`.               |

---

# 11. Security / Integrity

I'd keep this short because several cases are already covered elsewhere.

| Edge case                                               | Handling                                                 |
| ------------------------------------------------------- | -------------------------------------------------------- |
| **Malicious document content**                          | Treat as untrusted input; sandbox/limit processing.      |
| **Prompt injection**                                    | G4 prevents document content from becoming instructions. |
| **Unauthorized record/candidate requested through API** | Backend validates authorization and candidate ownership. |
| **AI invents a candidate/action**                       | Schema validation rejects it.                            |
| **Secrets appear in logs**                              | Redact credentials/tokens.                               |

---

# The resulting edge-case model

Instead of **150 individual cases**, you now have roughly **50 meaningful cases across 11 categories**:

```text id="e7nq1m"
1. Authentication & Access
2. Upload & Document Integrity
3. Extraction & OCR
4. Matching
5. Live ERP Verification
6. Exception Management
7. Run & Processing
8. NetSuite/CCC Ingestion
9. Database & Infrastructure
10. Reporting
11. Security & Integrity
```

And that's much better for your project because each category maps naturally to an **implementation/test suite**.

### The rule I'd use

Don't write an edge case for every manifestation of a failure.

For example, these:

```text id="h8m3ys"
Claude timeout
Claude 500
Claude connection reset
Claude unavailable
```

are one edge-case family:

> **Extraction service unavailable → retry safely → terminal failure after retry policy.**

Likewise:

```text id="m2w0k7"
two tabs
double click
retry after timeout
duplicate queue message
worker retry
```

are one family:

> **Duplicate/concurrent execution → idempotency + ownership/version check.**

That keeps the architecture **clean rather than becoming a 200-line catalog of permutations**.