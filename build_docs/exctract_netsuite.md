## 1. Runbook: how to redo/extend this from scratch

### Step 1 — Set up NetSuite API access
**What:** Confirm `netsuite_ingest/.env` has `ACCOUNT_ID`, `CONSUMER_KEY`, `CONSUMER_SECRET`,
`TOKEN_ID`, `TOKEN_SECRET`. Install `requests_oauthlib`.
**Why:** Every subsequent step depends on this.
**How to verify:** Run `netsuite_ingest/netsuite-query-record 1.py vendor --limit 1` and
confirm a 200 response.

### Step 2 — Confirm the AI extraction provider is live before trusting any extraction
**What:** Check `ai_audit_log` for the target statement's `DOCUMENT_UNDERSTANDING` row —
`success=1`, no `DeploymentNotFound` or similar error.
**Why:** A silently-degraded extraction (fallen back to `pdfplumber`) produces
garbage that looks like a data problem but is actually an infra problem.
**How:** `SELECT * FROM ai_audit_log WHERE statement_id = '<id>' AND interaction_type = 'DOCUMENT_UNDERSTANDING'`.

### Step 3 — Resolve every entity ID for the target vendor, not just one
**What:** Query `vendor` for every entity whose name/address matches the target vendor
(e.g. `WHERE UPPER(entityid) LIKE '%FRED BEANS%'`). Record every entity ID found.
**Why:** Querying only one entity silently drops real data.
**How:** `netsuite-query-record 1.py vendor --where "UPPER(entityid) LIKE '%<VENDOR>%'"`.

### Step 4 — Pull vendorbill/vendorcredit for ALL of that vendor's entity IDs, WITH payment status
**What:** For each entity ID from Step 3, run `scripts/load_netsuite_erp_data.py`
(**after applying the enhancement in Section 6.1** — adding `BUILTIN.DF(status)` to the
SELECT and looping over multiple entity IDs).
**Why:**  status is the single most important field this investigation
found, and single-entity scoping silently loses data.
**How:** Paginate via URL query string (`?limit=&offset=`), never embedded SQL `OFFSET` —
 Write via a single reused connection with `fast_executemany` —  Dedupe
`record_id` collisions in Python before insert 

### Step 5 — Run the vendor statement through extraction
**What:** `python notebooks/01_document_intake.py --pdf <path> --statement-id <id>`.
**Why:** Populates Bronze/Silver on the vendor-statement side so matching has something to
compare against.
**Watch for:** the confidence-contamination bug is fixed , but if you're working from a
copy of this codebase that predates that fix, verify with:
```sql
SELECT COUNT(*) FROM bronze_vendor_statement_raw
WHERE statement_id = '<id>' AND CAST(raw_outstanding_amount AS FLOAT) = extraction_confidence
```
This should be exactly 0. If it's not, the fix in `src/ai/claude_sonnet_client.py`'s
`_fallback_amount()` (skip the `"confidence"` key) hasn't been applied.

### Step 6 — Run matching, then filter exceptions through payment status before triaging
**What:** `python scripts/run_full_pipeline.py --pdf <path>` (runs intake + matching + report
in one command), or `src/matching/engine.py`'s `run_matching()` directly if intake already
ran.
**Why:** Matching alone will still flag a "Paid In Full" bill as an exception if the
statement's amount doesn't match the bill total — this is expected and NOT a
matching-engine bug. Cross-reference each exception's invoice number against the ingested
`payment_status` field before treating it as a real problem.

### Step 7 — For any exception on a genuinely "Open" bill, trace it via `/apply` before
escalating
**What:** For the specific bill's internal `id`:
```
GET /record/v1/vendorBill/{id}/item
GET /record/v1/vendorPayment/{paymentId}/apply/doc={id},line=0    (for each candidate payment)
GET /record/v1/vendorCredit/{creditId}/apply/doc={id},line=0      (for each candidate credit)
```
Candidate payments/credits: search `vendorpayment`/`vendorcredit` for the same entity in a
plausible date window around the bill's `trandate`, then check each one's `/apply` items
for a `doc` matching this bill's id.
**Why:** This is the only trustworthy way to explain a real discrepancy — never infer it
from credit/bill tranid similarity .

### Step 8 — Do not build new matching-engine logic from a pattern alone
**What:** Before proposing a matching-engine change (new match level, new aggregation rule),
check the review queue and raw Bronze data for the specific rows driving the pattern.
**Why:**  an apparent "split invoice" pattern was entirely a printing artifact +
the confidence bug, not a real scenario, and would have been solved by building something
unnecessary.

---

## 2. Open items / recommended next steps

### 2.1 — Add `payment_status` to the ingestion script (highest priority)
Add `BUILTIN.DF(status) AS payment_status` to both the `vendorbill` and `vendorcredit`
SELECT statements in `scripts/load_netsuite_erp_data.py`, store it as a new column on
`bronze_internal_erp_raw` / `silver_reconciliation_standard` (needs a migration), and update
`src/matching/engine.py` (or a pre-filter ahead of it) to treat a statement-side discrepancy
against a `Paid In Full` ERP row differently from one against an `Open` row — most likely:
still record it, but with a different `exception_reason` (e.g. `STALE_STATEMENT` vs the
existing `Amount Mismatch`) so AP reviewers aren't burning time on non-problems.

### 2.2 — Support multiple entity IDs per vendor in ingestion
Extend `scripts/load_netsuite_erp_data.py` to accept a list of entity IDs (or resolve them
automatically via a name/address search, per Step 3 of the runbook) instead of one
`--entity-id` argument, and load all of them under the same `vendor_id`/`statement_id`.

### 2.3 — Decide on the true early-payment-discount gap
`transactionline` access is still blocke, and the terms-based shortcut doesn't apply
to Fred Beans . With the `/apply` subresource now confirmed working, most of
what looked like "invisible discounts" turned out to be traceable credit-memo applications —
re-assess whether a genuine, untraceable early-payment discount still exists anywhere in this
vendor's data, or whether this gap is effectively closed for practical purposes. If a real
gap remains, request `transactionline` SuiteQL access from a NetSuite admin as the accurate
long-term fix.

### 2.4 — Re-run the full Lee's Auto Body statement analysis with all fixes applied

re-run the full ~172-invoice statement end to end and get real, complete numbers on how many
of the current exceptions resolve.

---

## 3. Reference

### NetSuite API access
- **SuiteQL endpoint:** `POST https://{account_id}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql`
  — paginate via `?limit=&offset=` in the URL, body is `{"q": "<SuiteQL>"}`.
- **REST Record API:** `GET https://{account_id}.suitetalk.api.netsuite.com/services/rest/record/v1/{recordType}/{id}[/{sublist}[/doc={docId},line={n}]]`
- **Auth (both):** OAuth 1.0a, HMAC-SHA256, `realm` = account ID. Same credentials for both
  API surfaces.
- **Headers (SuiteQL only):** `Prefer: transient` is required by this integration role.

### Key field reference
| Field | Record | Meaning |
|---|---|---|
| `tranid` | `vendorbill`, `vendorcredit` | The real invoice/credit number as printed to AP — use this for matching, not `custbody_kes_inv_number` (a different, internal cross-reference field that never appears on the vendor's own statement) |
| `id` | any | NetSuite's internal surrogate key — never shown externally |
| `total` | `vendorbill`, `vendorcredit` | Gross amount — does NOT reflect settlement |
| `status` (REST) / `BUILTIN.DF(status)` (SuiteQL) | `vendorbill` | Settlement status: `Open` / `Paid In Full` |
| `status` (plain SuiteQL) | `vendorbill` | A *different*, coarser code (`'B'`/`'A'`) — approval workflow, not settlement |
| `custbody_cgh_ro` | `vendorbill`, `vendorcredit` | RO number |
| `entity` | `vendorbill`, `vendorcredit`, `vendorpayment` | Which vendor sub-record — check ALL of a vendor's entity IDs, not just one |

### Blocked / inaccessible
- `transactionline`, `previoustransactionlinelink` — `Record not found` regardless of
  spelling/casing. Confirmed a permissions gap, not a naming issue.

### Files touched by this investigation
- `src/ai/claude_sonnet_client.py` — `_fallback_amount()` bug fix
- `scripts/load_netsuite_erp_data.py` — new script, built and iteratively fixed 
- `netsuite_ingest/.env`, `netsuite_ingest/netsuite-query-record 1.py` — credentials + ad hoc
  query tool
