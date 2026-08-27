---
version: v1.0
status: DRAFT — based on live investigation against the Fred Beans Parts vendor, 2026-08-17/18
---

# NetSuite ERP Ingestion & Reconciliation — Investigation Summary & Runbook

## 1. Purpose of this document

This documents an end-to-end investigation into pulling real ERP data from NetSuite and
reconciling it against vendor statements, using **Fred Beans Parts** as the test vendor.
It exists so a new engineer can:

1. Understand *why* the reconciliation numbers looked wrong at first, and why they were wrong
   in a different way than they first appeared.
2. Reproduce every step from scratch against a fresh environment.
3. Avoid re-discovering the same five bugs and two false leads that consumed most of the
   investigation time.

Read section 3 (Problems & Fixes) even if you only care about the runbook — several steps in
the runbook exist *because* of a specific bug, and skipping the "why" will make the runbook
feel arbitrary.

---

## 2. What we set out to do

Ingest real vendor-bill and vendor-credit data from NetSuite for one vendor (Fred Beans Parts)
into VIVE's reconciliation database, so that vendor statement PDFs uploaded through the
pipeline could be matched against real ERP data instead of mock data.

This touches three systems:
- **NetSuite** (source of truth for bills/credits/payments) — accessed via SuiteQL and the
  REST Record API, both authenticated with OAuth 1.0a Token-Based Authentication.
- **The reconciliation pipeline** (`src/`, `notebooks/`, `scripts/`) — AI extraction of vendor
  PDFs into Bronze/Silver, deterministic matching into Gold.
- **Azure SQL** (`vivevoucher-db`) — where Bronze/Silver/Gold tables live.

---

## 3. Problems found, and how each was solved

Presented in the order they were hit. Each one blocked the next step, so this is also
roughly the order to expect them in if you start over.

### 3.1 — Credentials file wasn't named `.env`

**Problem:** NetSuite API credentials (`ACCOUNT_ID`, `CONSUMER_KEY`, `CONSUMER_SECRET`,
`TOKEN_ID`, `TOKEN_SECRET`) were sitting in a file named `env 7` inside `netsuite_ingest/`,
not `.env`.

**Why it mattered:** `.gitignore` only excludes the literal name `.env`. A file named
`env 7` was untracked-but-visible to git — one `git add -A` away from committing live API
secrets to the repo.

**Fix:** Renamed to `netsuite_ingest/.env`. `python-dotenv`'s bare `load_dotenv()` also
requires this exact name to auto-discover the file.

**Do this first, always:** before touching any credentials file, confirm it's named exactly
`.env` and that `.gitignore` covers it.

---

### 3.2 — Missing Python dependency

**Problem:** `requests_oauthlib` (needed for NetSuite's OAuth 1.0a signing) wasn't installed.

**Fix:** `pip install requests_oauthlib`. Not yet in `requirements.txt` — add it if this
ingestion path becomes permanent.

---

### 3.3 — Claude Sonnet deployment briefly returned `DeploymentNotFound`

**Problem:** The primary AI extraction provider (`claude-sonnet-4-6` on Azure AI Foundry,
resource `vive-reconciliation-new-resource`) returned a 404 `DeploymentNotFound` on every
call. This silently degraded every upload to the deterministic `pdfplumber` fallback, which
produced garbage extractions (wrong vendor name, most rows missing an amount).

**Root cause:** The deployment genuinely didn't exist / wasn't active on that Azure resource
at the time. This was **not** a code bug — verified by calling the Anthropic SDK directly
against the same endpoint/deployment name from `.env` and getting the same error.

**Fix:** Someone with access to the Azure AI Foundry resource created/activated the
deployment. Confirmed resolved by re-running the identical direct API call and getting a
real response.

**Lesson:** If extraction quality suddenly craters (garbled vendor names, most rows failing
validation), check `ai_audit_log` for `DOCUMENT_UNDERSTANDING` rows with `success=0` before
assuming it's an extraction-logic bug. It might be an infrastructure outage one layer down.

---

### 3.4 — SuiteQL pagination via embedded `OFFSET` silently does nothing

**Problem:** `scripts/load_netsuite_erp_data.py`'s first version paginated by appending
`ORDER BY id OFFSET {n} ROWS FETCH NEXT {size} ROWS ONLY` directly into the SQL text. A
3-day test window returned 11,700+ rows and kept climbing — an infinite loop.

**Root cause:** NetSuite's `/services/rest/query/v1/suiteql` endpoint, called with the
`Prefer: transient` header (required for this integration role), **silently ignores a
SQL-level `OFFSET`** and always returns page 1. Confirmed directly: requesting `OFFSET 0`
and `OFFSET 100` with the same query returned byte-identical results both times.

**Fix:** Paginate via the **URL query string** instead —
`POST .../suiteql?limit=100&offset=200`, with the `q` field in the body holding an
un-paginated `SELECT ... ORDER BY id` (no `OFFSET`/`FETCH` in the SQL itself). This form
returns accurate `hasMore`/`totalResults` in the response and genuinely pages through the
result set.

**Why this matters for anyone extending the ingestion script:** if you add a new SuiteQL
query anywhere in this codebase and it needs more than one page of results, use the query
string form. Never trust an embedded `OFFSET` against this endpoint.

---

### 3.5 — Row-by-row `execute_sql()` writes are too slow for bulk loads

**Problem:** After fixing pagination, writing ~250 rows to `bronze_internal_erp_raw` /
`silver_reconciliation_standard` via the existing `execute_sql()` helper looked "stuck" —
actually just very slow (~0.5s per statement, measured directly).

**Root cause:** `src/lakehouse/connection.py`'s `execute_sql()`/`execute_query()` open a
**brand-new Azure SQL connection on every single call**. Fine for the rest of the pipeline's
call volume (a few dozen calls per statement); prohibitive at thousands of rows (would have
taken ~1.8 hours for the full company-wide load).

**Fix:** `scripts/load_netsuite_erp_data.py` opens **one connection** via the same public
`get_connection()`, and uses `cursor.executemany()` with `cursor.fast_executemany = True`
(a pyodbc-specific flag). Measured: 500 rows in 1.87s vs. ~242s row-by-row — about 130x
faster. This does **not** touch `src/lakehouse/connection.py` itself (per RULE-6 — Fabric
migration scoping — the same caution applies generally: don't casually change the shared
connection helper for a one-off script's performance needs).

**When to reach for this pattern:** any script writing more than a few hundred rows to
Azure SQL. Below that, the per-call connection overhead doesn't matter.

---

### 3.6 — Duplicate `record_id` on a company-wide load

**Problem:** Loading Fred Beans' entire company-wide bill/credit history (not scoped to one
statement) hit a `UNIQUE KEY constraint` violation on `silver_reconciliation_standard`.

**Root cause:** `record_id` is a hash of `(statement_id, invoice_number, outstanding_amount)`.
Across a large enough company-wide window, a handful of distinct NetSuite bills/credits
legitimately share the same `(invoice_number, amount)` pair.

**Fix:** Deduplicate in Python before the bulk insert — build a dict keyed by `record_id`
(last write wins), same semantics as `load_voucher_data.py`'s `INSERT OR REPLACE`, just
implemented in Python so the fast `executemany()` path (a plain `INSERT`, not a `MERGE`)
still works.

---

### 3.7 — THE BIG ONE: confidence score silently used as a dollar amount

**Problem:** Extraction on the first real, large test document produced an extremely low
match rate (13.85%), with a suspicious number of exceptions carrying an invoice amount of
exactly **$0.90 or $0.95**.

**Investigation:** Queried Bronze directly and found **86 of 231 rows (37%) had
`outstanding_amount` exactly equal to `extraction_confidence`** — statistically impossible
for real invoice data. Of those 86 contaminated rows, 85 became false exceptions (49 Amount
Mismatch, 36 Invoice Missing).

**Root cause:** `src/ai/claude_sonnet_client.py`'s `_fallback_amount()` — used when the
model's normal column-mapped `outstanding_amount` field comes back null — scans every value
in the row for something shaped like currency (`\d.\d\d`). It never excluded the row's own
`"confidence"` field, which the model *always* returns as a decimal like `0.90` or `0.95`.
That value passes the currency-shape regex just as easily as a real dollar figure, so it
got silently adopted as the invoice amount instead of correctly failing validation and
routing to human review.

**Fix:** One line — skip the `"confidence"` key in `_fallback_amount()`'s candidate scan.
See the comment left in that function for the exact reasoning.

**Impact after the fix, same document:** match rate went from 13.85% → 58.29% (32 → 109
matched, out of 231/187 total after re-validation). Contaminated-row count went to zero.

**Why this is the most important fix in this document:** every other finding in this
investigation (the wrong-entity issue, the "Paid In Full" discovery, the credit-naming
unreliability) was only discoverable *after* this fix, because before it, roughly a third
of the extracted data was fabricated noise drowning out the real signal.

**Lesson for future extraction-client work:** any "value-based fallback" that scans a raw
model-returned row for a plausible-looking value must explicitly exclude every field the
row schema uses for metadata (currently just `confidence`, but check the prompt schema
before adding new metadata fields). A currency-shape regex is not a business-value guarantee.

---

### 3.8 — Chased a "split invoice" pattern that turned out to be a printing artifact

**What it looked like:** The same invoice number appeared multiple times in one statement's
extracted data, each occurrence with a different dollar amount — exactly what a genuine
"invoice paid across 3-4 separate payments" scenario would look like. This led to a proposal
to add a "Level 3: aggregated invoice match" to the deterministic matching engine (sum
statement lines sharing an invoice number, compare the sum to the ERP total).

**Investigation before building anything:** Checked the *review queue* (not just Bronze) for
one repeating invoice number (`9154082`). Found: one valid row in Bronze (real amount), and
the other occurrences correctly rejected — one as an exact `DUPLICATE_RECORD`, one as
`MISSING_MANDATORY_FIELD` (amount genuinely unreadable). This is Fred Beans' statement
literally printing the same invoice twice (once in an aging-ledger section, once in a
"circle invoices being paid" list), not the vendor billing in installments.

**Conclusion: after fixing 3.7, zero invoice numbers appear more than once in Bronze for this
document.** The dedup/rejection logic that already existed handles this correctly on its own.

**Decision: did not build Level 3 aggregation matching.** It would have been real complexity
solving a scenario that, once checked against actual data, doesn't occur in this document.

**Process lesson, worth repeating to the team:** a pattern that looks exactly like a real
business scenario in aggregate statistics can be a data-quality artifact. Verify against the
review queue / raw extraction, not just the summary numbers, before designing new matching
logic around it.

---

### 3.9 — `transactionline` / `previoustransactionlinelink` are not accessible

**Problem:** Needed to see which specific payment or credit applied to which specific bill
(required for true early-payment-discount visibility and genuine split-payment detection).

**What was tried:** Direct SuiteQL queries against `transactionline` and
`previoustransactionlinelink`, multiple casings/spellings, both bare and quoted table names.

**Result:** `Record 'transactionline' was not found` on every attempt, re-verified live
(not just trusted from memory) later in the investigation with identical results.

**Conclusion:** This is a **permissions gap on the integration role**, not a naming or syntax
issue (confirmed by testing spelling variants — a genuinely wrong table name gives the exact
same generic error, so we ruled that out explicitly). Closing it requires a NetSuite admin
granting SuiteQL view access to these record types to this role — a request outside this
investigation's scope.

---

### 3.10 — Confirmed Fred Beans doesn't use NetSuite's Term-based discount at all

**Hypothesis tested:** Could the early-payment discount be computed ourselves from the
vendor's payment `terms` (e.g. "2% 10 Net 30"), avoiding the need for `transactionline`
entirely?

**What was found:** NetSuite's `term` record type *is* accessible and genuinely defines two
discount-bearing terms in this account ("1% 10 Net 30", "2% 10 Net 30"). But across **all
42,854 Fred Beans bills**, only 1 has any `terms` value set at all (and it's "Due on
receipt" — no discount). Zero bills use either discount-bearing term.

**Conclusion:** This shortcut doesn't exist for this vendor. Whatever discounts appear on
Fred Beans' payment vouchers are applied manually/ad-hoc by AP staff, not computed from a
Term policy — ruling out one candidate solution with direct evidence rather than assumption.

---

### 3.11 — BREAKTHROUGH: the REST Record API's `apply` subresource exposes what SuiteQL can't

**What changed the investigation:** A teammate produced a full manual trace of one invoice
(`9281714X2`) using a **different NetSuite API surface** — the REST Record API
(`/services/rest/record/v1/...`), not SuiteQL. Specifically:

```
GET /record/v1/vendorBill/{billId}/item                    -- the bill's line items
GET /record/v1/vendorPayment/{paymentId}/apply              -- every bill a payment applied to
GET /record/v1/vendorPayment/{paymentId}/apply/doc={billId},line=0   -- the specific application
GET /record/v1/vendorCredit/{creditId}/apply/doc={billId},line=0     -- ditto, for a credit
```

**Verified live, same OAuth1 credentials, no new permissions needed** — all four calls
succeeded and returned real data matching the manual trace exactly (`amount: 62.73`,
`amount: 199.84`, `refNum: "9281714X2"`).

**Why this matters:** this is application-level linkage — "this payment/credit applied $X
to *this specific bill*" — which is exactly the data `transactionline` would have given us,
reached through a completely different, already-accessible API surface.

**The correct outstanding-balance formula, derived from this:**
```
Outstanding = vendorbill.total
            - SUM(vendorpayment_apply.amount WHERE doc = bill.id)
            - SUM(vendorcredit_apply.amount WHERE doc = bill.id)
```

---

### 3.12 — Credit-memo tranid naming does NOT reliably indicate which bill it settles

**What was assumed (and was wrong):** A credit memo named e.g. `CM9403325` settles the bill
named `9403325` — this seemed reasonable given the payment-voucher PDF groups them
adjacently, and it held true for the very first traced example (`CM9205221` did apply to
`9281714X2`... but even there, that credit's *total* ($274.14) didn't match what applied to
that one bill ($199.84) — it was split across two bills).

**What broke the assumption:** Traced `CM9403325` (chosen because its name matches bill
`9403325` exactly) via its full `/apply` list. **It never applied to bill 9403325 at all** —
it applied entirely to three unrelated bills (`9479190`, `9467517`, `9470718`).

**Conclusion:** Credit-memo naming is coincidental relative to which bill(s) it actually
offsets. **The only trustworthy source of bill-credit/bill-payment linkage is the `/apply`
subresource — never infer it from tranid similarity.**

**A related discovery from the same trace:** a single credit memo can apply across
**multiple different bills** in varying amounts. This is the genuine version of the
"split payment" scenario originally proposed in 3.8 — it's real, it just lives on the
credit/payment-application side, not on the vendor-statement side, which is why the 3.8
investigation (which only looked at statement data) didn't find it.

---

### 3.13 — THE SECOND BIG ONE: `vendorbill.status` tells you settlement state directly

**What was tried next:** Since brute-force reverse-tracing "what settled this bill" is
expensive (no direct "find applications for bill X" query — you have to search candidate
payments/credits and check each one's `/apply` list), checked whether the bill record
itself carries a simpler settlement signal.

**What was found:** `GET /record/v1/vendorBill/{id}` returns a `status` field that is a rich,
human-readable label — `"Paid In Full"` or `"Open"` — completely different from what SuiteQL's
plain `status` column shows (`'B'`/`'A'`, coarse approval-workflow codes only).

**Critically, this is bulk-queryable via SuiteQL too**, via NetSuite's display-function
wrapper:
```sql
SELECT id, tranid, BUILTIN.DF(status) AS payment_status FROM vendorbill WHERE ...
```
Confirmed on 43,213 rows in a single query — no per-record REST calls needed at scale.

**The number that reframes everything:** across all of Fred Beans' bills (both known
entities, 18706 and 590648):

| Status | Count | % |
|---|---|---|
| Paid In Full | 41,823 | 96.8% |
| Open | 1,390 | 3.2% |

**All 5 bills spot-checked in this investigation — including two filed under the wrong
entity and one whose apparent credit match was a naming coincidence — were confirmed
"Paid In Full."**

**Conclusion:** a large share of what this investigation was calling "Invoice Missing" or
"Amount Mismatch" exceptions are very likely not real reconciliation problems — they're
genuinely-settled bills that the ingestion has no way to recognize as settled, because it
only ever pulled `total` and never checked payment status. The vendor's own printed
statement is frequently stale relative to NetSuite's live settlement state; that's a normal
timing lag, not a data error.

---

### 3.14 — One vendor, multiple NetSuite entity IDs

**Problem:** Some invoice numbers genuinely don't exist under entity `18706` (the entity ID
this investigation used throughout for "Fred Beans Parts"), but exist under entity `590648`
("FRED BEANS PARTS PRIMARY") — a sibling vendor sub-record for the same real-world vendor.

**Why this happens:** NetSuite lets one real vendor have multiple entity records (we found
five distinct Fred Beans entities early in this investigation: `18706`, `590648`, `5653`,
`20186`, `344272`). Which one a given bill lands under depends on how it was entered/imported
(this account imports via Celigo), not on any rule visible from the bill itself.

**Current gap:** `scripts/load_netsuite_erp_data.py` takes a single `--entity-id` argument
and only pulls that one entity. Any bill filed under a sibling entity is invisible to the
ingestion even though it genuinely exists and belongs to the same vendor.

**Fix not yet implemented** — see Section 6.

---

## 4. The corrected mental model

Before this investigation, the implicit model was:

> vendor statement `outstanding_amount` should equal NetSuite `vendorbill.total` for the
> same invoice number.

The corrected model, built from the findings above:

> A vendor statement's stated "amount due" for an invoice is only meaningful once you know
> whether NetSuite considers that specific bill **Open** or **Paid In Full**. If Paid In
> Full, any nonzero amount on the statement is very likely staleness, not a discrepancy — and
> if you need to know *why* it's paid in full, the only trustworthy source is the
> `vendorpayment`/`vendorcredit` `/apply` subresource chain, never tranid-name similarity.
> Also: check every known entity ID for the vendor, not just one, before concluding an
> invoice is missing.

---

## 5. Runbook: how to redo/extend this from scratch

### Step 1 — Set up NetSuite API access
**What:** Confirm `netsuite_ingest/.env` has `ACCOUNT_ID`, `CONSUMER_KEY`, `CONSUMER_SECRET`,
`TOKEN_ID`, `TOKEN_SECRET`. Install `requests_oauthlib`.
**Why:** Every subsequent step depends on this. See 3.1/3.2.
**How to verify:** Run `netsuite_ingest/netsuite-query-record 1.py vendor --limit 1` and
confirm a 200 response.

### Step 2 — Confirm the AI extraction provider is live before trusting any extraction
**What:** Check `ai_audit_log` for the target statement's `DOCUMENT_UNDERSTANDING` row —
`success=1`, no `DeploymentNotFound` or similar error.
**Why:** See 3.3. A silently-degraded extraction (fallen back to `pdfplumber`) produces
garbage that looks like a data problem but is actually an infra problem.
**How:** `SELECT * FROM ai_audit_log WHERE statement_id = '<id>' AND interaction_type = 'DOCUMENT_UNDERSTANDING'`.

### Step 3 — Resolve every entity ID for the target vendor, not just one
**What:** Query `vendor` for every entity whose name/address matches the target vendor
(e.g. `WHERE UPPER(entityid) LIKE '%FRED BEANS%'`). Record every entity ID found.
**Why:** See 3.14. Querying only one entity silently drops real data.
**How:** `netsuite-query-record 1.py vendor --where "UPPER(entityid) LIKE '%<VENDOR>%'"`.

### Step 4 — Pull vendorbill/vendorcredit for ALL of that vendor's entity IDs, WITH payment status
**What:** For each entity ID from Step 3, run `scripts/load_netsuite_erp_data.py`
(**after applying the enhancement in Section 6.1** — adding `BUILTIN.DF(status)` to the
SELECT and looping over multiple entity IDs).
**Why:** See 3.13 and 3.14 — status is the single most important field this investigation
found, and single-entity scoping silently loses data.
**How:** Paginate via URL query string (`?limit=&offset=`), never embedded SQL `OFFSET` —
see 3.4. Write via a single reused connection with `fast_executemany` — see 3.5. Dedupe
`record_id` collisions in Python before insert — see 3.6.

### Step 5 — Run the vendor statement through extraction
**What:** `python notebooks/01_document_intake.py --pdf <path> --statement-id <id>`.
**Why:** Populates Bronze/Silver on the vendor-statement side so matching has something to
compare against.
**Watch for:** the confidence-contamination bug is fixed (3.7), but if you're working from a
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
statement's amount doesn't match the bill total (see 3.13) — this is expected and NOT a
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
from credit/bill tranid similarity (see 3.12).

### Step 8 — Do not build new matching-engine logic from a pattern alone
**What:** Before proposing a matching-engine change (new match level, new aggregation rule),
check the review queue and raw Bronze data for the specific rows driving the pattern.
**Why:** See 3.8 — an apparent "split invoice" pattern was entirely a printing artifact +
the confidence bug, not a real scenario, and would have been solved by building something
unnecessary.

---

## 6. Open items / recommended next steps

### 6.1 — Add `payment_status` to the ingestion script (highest priority)
Add `BUILTIN.DF(status) AS payment_status` to both the `vendorbill` and `vendorcredit`
SELECT statements in `scripts/load_netsuite_erp_data.py`, store it as a new column on
`bronze_internal_erp_raw` / `silver_reconciliation_standard` (needs a migration), and update
`src/matching/engine.py` (or a pre-filter ahead of it) to treat a statement-side discrepancy
against a `Paid In Full` ERP row differently from one against an `Open` row — most likely:
still record it, but with a different `exception_reason` (e.g. `STALE_STATEMENT` vs the
existing `Amount Mismatch`) so AP reviewers aren't burning time on non-problems.

### 6.2 — Support multiple entity IDs per vendor in ingestion
Extend `scripts/load_netsuite_erp_data.py` to accept a list of entity IDs (or resolve them
automatically via a name/address search, per Step 3 of the runbook) instead of one
`--entity-id` argument, and load all of them under the same `vendor_id`/`statement_id`.

### 6.3 — Decide on the true early-payment-discount gap
`transactionline` access is still blocked (3.9), and the terms-based shortcut doesn't apply
to Fred Beans (3.10). With the `/apply` subresource (3.11) now confirmed working, most of
what looked like "invisible discounts" turned out to be traceable credit-memo applications —
re-assess whether a genuine, untraceable early-payment discount still exists anywhere in this
vendor's data, or whether this gap is effectively closed for practical purposes. If a real
gap remains, request `transactionline` SuiteQL access from a NetSuite admin as the accurate
long-term fix.

### 6.4 — Re-run the full Lee's Auto Body statement analysis with all fixes applied
Sections 3.13/3.14 were confirmed on a 5-invoice sample. Once 6.1 and 6.2 are implemented,
re-run the full ~172-invoice statement end to end and get real, complete numbers on how many
of the current exceptions resolve.

---

## 7. Reference

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
- `src/ai/claude_sonnet_client.py` — `_fallback_amount()` bug fix (3.7)
- `scripts/load_netsuite_erp_data.py` — new script, built and iteratively fixed (3.4, 3.5, 3.6)
- `netsuite_ingest/.env`, `netsuite_ingest/netsuite-query-record 1.py` — credentials + ad hoc
  query tool
