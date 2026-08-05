# RULES — Deliberate Decisions, Do Not Undo

This catalogues decisions in this codebase that were made deliberately, often
after finding out the hard way why the obvious alternative doesn't work.
Each entry has an ID referenced in a code comment at its enforcement point
(`# See RULES.md RULE-XX`), so a future reader who's tempted to "simplify"
or "fix" something here can find the reasoning first.

This is a living document — add a new rule whenever a deliberate decision
gets made or rediscovered, the same way the Progress Log in
`docs/VIVE_Implementation_Context.md` tracks phase status.

---

### RULE-01 — No invoice number suffix stripping

**Rule:** Invoice numbers are stored exactly as extracted, whitespace-trimmed
only. No suffix/prefix normalization, no truncation.

**Why:** Suffix stripping was tried before and removed on purpose — it was
hiding real discrepancies between how the vendor and the ERP numbered the
same invoice. If the two sides genuinely format invoice numbers differently,
that's a real exception to surface, not something to paper over.

**Enforced at:** [`src/normalization.py`](src/normalization.py) —
`normalize_invoice_number()`.

---

### RULE-02 — Cache hit requires `row_count > 0` from a prior successful run

**Rule:** The extraction cache only counts as a hit if a previous run for
this exact `document_hash` completed with at least one row written.

**Why:** A failed extraction (e.g. all providers errored, zero invoices
written) must never be treated as "already processed" — that would silently
skip re-extraction of a document that was never actually parsed.

**Enforced at:** [`notebooks/01_document_intake.py`](notebooks/01_document_intake.py) —
`check_cache()` (`WHERE document_hash = ? AND row_count > 0`).

---

### RULE-03 — Matching engine is 100% deterministic, zero AI involvement

**Rule:** Match/exception decisions are pure Python/SQL. No AI call is ever
consulted to decide whether two invoices match.

**Why:** Financial reconciliation decisions must be reproducible and
auditable on demand — this is a hard invariant of the system, not a
current limitation waiting to be lifted.

**Enforced at:** [`src/matching/engine.py`](src/matching/engine.py) —
the whole file (`classify_match()`, `amounts_match()`, `run_matching()`);
see the module docstring: "AI never touches this."

---

### RULE-04 — Claude Sonnet 4.6 (Azure AI Foundry) + pdfplumber/OCR is the final extraction chain (supersedes three times)

**Rule:** No other AI providers in the extraction chain. Primary: Claude
Sonnet 4.6, via Azure AI Foundry, the whole PDF sent in ONE streaming
call (no page splitting). Column mapping is column-agnostic — done in
Python (`_map_columns()`/`_row_to_invoice()` in `claude_sonnet_client.py`),
not by a shared per-vendor config. Fallback: deterministic pdfplumber,
unchanged, which handles scanned pages internally via per-page OCR.

**Why:** Validated across all 4 sample vendor statements (69-602 rows),
with column-agnostic mapping that correctly disambiguates vendors with
multiple invoice-number-like columns, and reliable document-level
`vendor_name` extraction (as of the vendor_name/statement_date prompt
fix). Supersedes both Azure Document Intelligence and Gemini as primary.
`config/ai/azure_gpt5_*.json`, `config/ai/azure_doc_intel.json`,
`config/ai/gemini.json`, and `config/ai/mistral.json` all remain
registered in `provider_config_paths` as alternate/fallback options,
directly accessible via `get_ai_client()`, but are not part of the active
chain.

**Per-row confidence is genuine, not hardcoded (fixed 2026-07-24 for the
active primary — see `discovery/RISK_REGISTER.md` R-001,
`discovery/components/C10_claude_sonnet_client.md`):**
`ClaudeSonnetClient`'s `EXTRACTION_PROMPT` explicitly asks the model for a
per-row `"confidence"` field (0.0-1.0) with calibration guidance, and
`_row_to_invoice()` parses it via `_parse_confidence()` — `line_confidence`
is the model's own self-assessment, not the `ROW_CONFIDENCE = 0.75`
constant (that constant now feeds only the document-level
`extraction_confidence.overall` field, never per-row `line_confidence`).
Confirmed with live data: pre-fix statements (before 2026-07-24) show
`extraction_confidence` exactly `0.75` with zero variance across every row
(e.g. `STMT-6C0D52DA`, 202/202 rows); post-fix statements show genuine
variance — `KSI Noakers 053126.pdf` (`STMT-928FF303`, 2026-08-01) came back
with 4 distinct confidence values across 69 rows (0.91-0.95), and a
genuinely degraded scanned document (`Very_Dirty_Scanned_Reconciliation.pdf`)
came back at 0.35-0.60 across 132 rows — a real, model-elicited signal that
discriminates by document difficulty rather than a habitual default. If the
model omits the field or returns something unparseable/out-of-range,
`_parse_confidence()` falls back to `FALLBACK_LINE_CONFIDENCE = 0.40`
(below the `0.60` threshold), so an untrustworthy signal still routes to
human review per RULE-10. `GeminiClient` and `MistralClient` (both dormant,
not in the active provider chain) still hardcode `ROW_CONFIDENCE = 0.75`
for `line_confidence` — this fix applies only to the active primary.

**Superseded text (kept for history — fabricated-confidence era, accurate
until 2026-07-24):** "**Known gap, tracked separately (see
`discovery/RISK_REGISTER.md` R-001, `discovery/INVARIANT_CATALOGUE.md`
IC-15):** unlike the Document Intelligence and gpt-5-mini eras,
`ClaudeSonnetClient` does not request or elicit a genuine per-row
confidence value — `line_confidence` is a hardcoded `0.75` constant, which
always clears the `0.60` human-review threshold regardless of actual
extraction quality. Accepted as a known risk as of 2026-07-24 (Critical
severity, tracked against Sprint 1 planning), not fixed as part of this
rule update."

**Corrected 2026-08-01** (pipeline verification follow-up,
`PIPELINE_VERIFICATION_REPORT.md` Finding 7): the gap above was fixed the
same day it was logged (2026-07-24, per `discovery/RISK_REGISTER.md` R-001)
but this rule's wording was never updated afterward, so it kept describing
already-fixed code as broken for over a week. Caught when a real end-to-end
pipeline run showed genuine per-row confidence variance (0.91-0.95 across
69 rows) rather than a flat constant. `docs/VIVE_Implementation_Context.md`
Section 3 and its Section 7 open-items table had the identical stale claim
and were corrected in the same pass.

**Superseded text (kept for history — Document Intelligence era):** "No
other AI providers in the extraction chain. Primary: Azure Document
Intelligence, `prebuilt-layout` model, the whole PDF sent in ONE call (no
page splitting — prebuilt-layout handles multi-page and scanned documents
natively via its own internal OCR). Its generic table output (rows/cells,
no semantic field labels) is mapped to the Universal Financial Document
Schema by reusing the same column-header interpreter the pdfplumber
fallback already used (`_find_header_row` / `_map_columns` /
`_extract_invoice_row`) — see RULE-07. Fallback: deterministic pdfplumber,
unchanged, which handles scanned pages internally via per-page OCR. Why:
Azure OpenAI gpt-5-mini (the prior primary) took 90-180s per page; a live
test of Document Intelligence's `prebuilt-layout` against the same sample
vendor statement (`sample_data/ASTCollex0526.pdf`) completed the full
4-page document in 14 seconds with equivalent table/column coverage.
`prebuilt-invoice` was explicitly rejected first — built for one invoice
per document, not a table of many invoices per page, with no field for
dealer-specific `ro_number`/`work_order_number` at all. Two structural
quirks this client works around, found only by live-testing against all 3
real sample statements: (1) header detection runs independently on every
table first, since whether a later page's table has its own header or is a
headerless continuation varies by vendor; (2) a trailing totals footer row
can trip the header-detection keyword scan, so a header match found
anywhere but at/near the top of a table (`HEADER_MAX_DATA_START` in
`document_intelligence_client.py`) is rejected as a false positive."

**Superseded text (kept for history — gpt-5-mini era):** "No other AI
providers in the extraction chain. Primary: Azure OpenAI gpt-5-mini via the
Responses API, PDF sent as a per-page inline base64 `input_file` block
(medium reasoning effort, 180s per-page timeout — sending a whole
multi-page statement in one call was found to time out even at 600s;
per-page calls complete reliably). Fallback: deterministic pdfplumber,
which handles scanned pages internally via per-page OCR. Originally Claude
(Haiku 4.5) held this slot; vendor consolidation onto Azure OpenAI was a
committed decision independent of accuracy, so a real 3-model comparison
(gpt-5-mini, gpt-5-nano, gpt-5.1) was run against sample vendor statements
using the actual production `VISION_PROMPT` extraction schema — gpt-5-mini
passed the accuracy gate and Claude was retired from the active chain."

**Superseded text (kept for history — Claude era):** "No other AI providers
in the extraction chain. Primary: Claude Vision (PDF sent directly).
Fallback: deterministic pdfplumber, which handles scanned pages internally
via per-page OCR. Settled decision (`docs/VIVE_Implementation_Context.md`
Section 3). Gemini and Groq were removed in this session specifically to
enforce this — having three AI providers with an inconsistent fallback
order was itself a source of confusion (see the OCR-fix and
provider-removal work in the Progress Log)."

**Enforced at:** [`config/ai/active_provider.json`](config/ai/active_provider.json)
(`"provider_chain": ["claude_sonnet", "pdfplumber"]`),
[`src/ai/client_factory.py`](src/ai/client_factory.py) — `get_ai_client()`,
[`config/ai/claude_sonnet_extraction.json`](config/ai/claude_sonnet_extraction.json),
[`src/ai/claude_sonnet_client.py`](src/ai/claude_sonnet_client.py).

**Corrected 2026-07-24** (BCE Stage 3 documentation sweep, engineer-confirmed):
this rule previously described Azure Document Intelligence as the final
chain — stale relative to `active_provider.json`, which has named
`claude_sonnet` as `provider_chain[0]` since before this correction. Part
of a coordinated 6-location sweep (see `discovery/ANNOTATION_CHECKLIST.md`
P1-S3-002) — the other five locations were `docs/VIVE_Implementation_Context.md`
Section 3, `src/ai/gemini_client.py`, `src/ai/client_factory.py`'s inline
comments, `src/ai/ocr_extractor.py`, and `notebooks/04_generate_report.py`.

---

### RULE-05 — Mock ERP generator and its suggestion workflow are CLI-only, forever

**Rule:** `src/mock_erp/generator.py` and the `scenario_config.json`
suggestion workflow (auto-suggested exception targets printed after intake)
are only ever invoked via `notebooks/02_generate_mock_erp.py` (and
`scripts/run_full_pipeline.py`). This must **never** be wired into a
dashboard or any web entry point — even after a dashboard exists.

**Why:** It's a developer/QA tool for verifying the matching engine
correctly catches deliberately-planted errors, not something any of the
real dashboard's 5-10 end users should ever see or touch.

**Enforced at:** [`src/mock_erp/generator.py`](src/mock_erp/generator.py) —
enforced by *absence*: there is no HTTP-facing wrapper around it, and none
should be added. Entry points: [`notebooks/02_generate_mock_erp.py`](notebooks/02_generate_mock_erp.py).

---

### RULE-06 — No live NetSuite integration; mock ERP is a deliberate placeholder

**Rule:** Internal ERP data is simulated by the mock ERP generator. Building
a real NetSuite integration is out of scope until VIVE Collision grants API
access — do not attempt it preemptively.

**Why:** NetSuite API access isn't available yet. The mock/real split is
deliberately isolated so the eventual swap is narrow: both sides already
share the same Silver schema, distinguished only by `record_source`.

**Enforced at:** [`src/lakehouse/connection.py`](src/lakehouse/connection.py) —
"the only file that knows the storage backend" (see RULE-13 — this is now
Azure SQL or SQLite, not SQLite-only); the
`record_source` column (`VENDOR_STATEMENT` vs `INTERNAL_ERP`) in
`silver_reconciliation_standard`. Full rationale: `docs/VIVE_Implementation_Context.md` Section 2.

---

### RULE-07 — No per-vendor onboarding/configuration

**Rule:** Column mapping is universal — there is no per-vendor config file
or setup step before a new vendor's statement can be processed.

**Why:** Deliberate design goal: any vendor statement PDF, any layout,
works without a human configuring column mappings for that vendor first.

**Enforced at:** [`src/ai/claude_sonnet_client.py`](src/ai/claude_sonnet_client.py) —
`_map_columns()`, the actual live enforcement point for the current
active provider (see RULE-04);
[`src/ai/pdfplumber_fallback.py`](src/ai/pdfplumber_fallback.py) — `_map_columns()`, the
deterministic fallback path.

**Corrected 2026-07-24** (BCE Stage 3, engineer-signed-off): this rule
previously cited `src/ai/document_understanding_engine.py`'s `VISION_PROMPT`
as the enforcement point — that prompt is confirmed not read by the current
active provider (`ClaudeSonnetClient` sends its own embedded prompt
instead; see RULE-04). The underlying rule (no per-vendor config) was never
false — only the citation was stale.

---

### RULE-08 — No full Admin/Reviewer role separation

**Rule:** Now that per-user logins exist (Phase 3, built), there is
deliberately only one flat permission level — no Admin vs. Reviewer tiers.

**Why:** Everyone using the dashboard does the same job today. Per-user
logins exist so `resolved_by`/`disposed_by` on a disposition means something
real, not to gate access by role.

**Enforced at:** [`web/routers/users.py`](web/routers/users.py) and
[`web/deps.py`](web/deps.py) — `require_login()` — enforced by absence of
any role/permission check anywhere in either file or the request path. Any
authenticated user, including one added by another non-admin user, can add
or remove any other user (self-removal excepted). Check any future PR that
introduces role/permission checks against this rule and against
`docs/VIVE_Implementation_Context.md` Sections 4 and 5 before merging it.

**Corrected 2026-07-24** (BCE Stage 3, engineer-signed-off): this rule
previously stated per-user logins were "unbuilt as of this writing" — false
as of Phase 3's completion (`users`/`jobs` tables, login/logout, user
management all built and functional). The flat-permission design intent
this rule describes is confirmed still accurate in the now-built code —
only the build-status premise was stale.

---

### RULE-09 — Confidence gate and "AI looks odd" flag are deferred, not built preemptively

**Rule:** A document-level confidence gate and an AI advisory "this looks
odd" flag are explicitly not being built now.

**Why:** Only build these if a real, observed case shows today's per-row
confidence handling actually lets something bad through. Building ahead of
a real trigger risks solving a problem that may never materialize, in a way
that's hard to validate without a real failure case to test against.

**Enforced at:** Not yet built. Trigger conditions are documented in
`docs/VIVE_Implementation_Context.md` Section 4, Phase 5 — check those
conditions before starting either of these.

---

### RULE-10 — OCR-derived invoice rows get confidence 0.50, deliberately below the 0.60 validation threshold

**Rule:** When `extract_with_pdfplumber()`'s fallback OCRs a scanned page and
converts the OCR text into a pseudo-table, every row extracted from that
page gets `line_confidence = 0.50` — as opposed to `0.65` for rows from
pdfplumber's real (geometry-based) table extraction.

**Why:** OCR-derived rows infer column boundaries from whitespace in flat
text, not real table geometry — inherently less reliable. `0.50` is
deliberately below the `0.60` confidence threshold in
`config/validation/extraction_rules.json`, so **every OCR-extracted invoice
always fails `validate_invoice()`'s confidence check and routes to the human
review queue — it can never silently auto-pass into Bronze/Silver.** This is
intended behavior, consistent with "never silently succeed" — not something
to "fix" by raising the confidence score once OCR accuracy is judged good
enough on the same PDFs.

**Enforced at:** [`src/ai/pdfplumber_fallback.py`](src/ai/pdfplumber_fallback.py) —
`extract_with_pdfplumber()` (`row_confidence = 0.50 if page_num in ocr_pages_used else 0.65`),
checked downstream by [`notebooks/01_document_intake.py`](notebooks/01_document_intake.py) —
`validate_invoice()` (`confidence_threshold`, from `config/validation/extraction_rules.json`).

**Context:** Added because the OCR fallback path previously existed but had
no consumer — Tesseract would run, but its output never reached the
deterministic table parser (see Progress Log). Fixing that gap meant OCR
output could newly reach Bronze/Silver, so the confidence tagging above was
added at the same time to keep the "never silently succeed" invariant intact
for this newly-functional path.

---

### RULE-11 — No "fuzzy prefix" matching level

**Rule:** The matching engine does not match invoices on a truncated
invoice-number prefix (e.g. first 6 characters) plus amount. Level 1
requires an exact invoice number match; anything short of that falls
through to Level 2 (RO + amount) or an exception.

**Why:** An earlier version matched on a truncated prefix plus amount,
intended to catch revision suffixes that survived normalization. In
practice, vendor invoice numbers commonly share a long common prefix
(e.g. `"SIN122..."`) and flat per-line-item fees repeat constantly, so
that heuristic cross-matched unrelated invoices whenever their prefix
*and* amount coincidentally lined up — silently hiding genuinely missing
invoices behind an unrelated match. Level 1 (exact `invoice_number`, via
`invoice_number_normalized`) already covers genuine suffix normalization
once a vendor-specific profile is configured; Level 2 (RO + amount) is
the correct fallback otherwise.

**Enforced at:** [`src/matching/engine.py`](src/matching/engine.py) —
`classify_match()`, the `NOTE` comment directly above the Level 2 (RO +
amount) branch.

---

### RULE-12 — Schema changes go through a new numbered migration file

**Rule:** Every lakehouse schema change is a new file under `migrations/`
(`NNN_description.sql`, zero-padded to 3 digits) — never a manual edit to
an existing migration file, never a direct `ALTER`/`CREATE` run by hand
against the database, and never a change to `notebooks/00_setup_lakehouse_schema.py`
itself (it only calls the migration runner now).

**Why:** Before this, all schema DDL lived directly in
`00_setup_lakehouse_schema.py`, with no record of what had changed when or
in what order. That's fine for a single always-fresh dev database, but
breaks down the moment more than one environment or more than one person
needs to apply the same sequence of changes reliably — the numbered,
tracked migration history is what makes "what schema state is this
database in" an answerable question instead of a guess.

**Enforced at:** [`src/lakehouse/migrations.py`](src/lakehouse/migrations.py) —
`apply_pending_migrations()` (discovery + application + `schema_version`
bookkeeping), [`migrations/`](migrations/) (the migration files themselves),
[`notebooks/00_setup_lakehouse_schema.py`](notebooks/00_setup_lakehouse_schema.py)
(the only thing that should call the runner — it should never contain DDL directly again).

---

### RULE-13 — Azure SQL is the production backend; SQLite stays for local dev/tests

**Rule:** `src/lakehouse/connection.py` picks the backend at connection time
based on whether `AZURE_SQL_SERVER` is set in the environment — Azure SQL
(via `pyodbc`) if set, SQLite otherwise. Callers write backend-agnostic SQL;
`?` placeholders work unchanged on both (pyodbc's default paramstyle is
qmark), and the two SQLite-only constructs this codebase actually uses —
`INSERT OR REPLACE INTO table (...)` and a trailing `LIMIT n` — are rewritten
into T-SQL (`MERGE`, `SELECT TOP n`) inside `execute_sql()`/`execute_query()`
before they reach the driver. New `INSERT OR REPLACE` call sites must add
their table's unique-key columns to `AZURE_UPSERT_KEYS` in that file.

**Why:** Phase 3 requirement to run against a real production database
instead of a local SQLite file, without breaking local development or the
test suite (which never sets `AZURE_SQL_SERVER`, so they keep using SQLite
untouched) or rewriting the SQLite-specific SQL embedded in
`notebooks/01_document_intake.py` and `src/mock_erp/generator.py` — keeping
`connection.py` the single place that knows the backend (RULE-06) meant
absorbing the dialect differences there instead.

**Scoped exception — Fabric Warehouse cut-over (added 2026-08-05):**
`get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()`
in `src/lakehouse/connection.py` are an additive, narrower path — not a
replacement for the Azure SQL/SQLite split above. As of this update they
cover exactly three tables (`extraction_cache`, `document_intake_log`,
`validation_document_review_queue`). Two respects in which this path does
**not** carry the same guarantees as `execute_sql()`/`execute_query()`,
by design, not oversight:
1. **No dialect translation and no connection-drop retry** — callers of
   the Fabric functions must write SQL valid on both SQLite (the local/test
   fallback) and T-SQL directly; `_translate_for_azure()` is never applied
   on this path.
2. **No `IDENTITY` column on the Fabric side for any of the three tables**
   — each write site computes `MAX(id) + 1` in application code, which is
   not concurrency-safe. This is a real, currently-accepted-as-tracked-risk
   gap (`discovery/RISK_REGISTER.md` R-012, `discovery/INVARIANT_CATALOGUE.md`
   IC-19 — IC-19 is deliberately catalogued as *not currently enforced*,
   not as a passing invariant), not a claim that this rule's
   backend-agnostic-callers guarantee still fully holds for these three
   tables. See `discovery/TOPOLOGY.md` A01 row 8 for the full writeup.

Any future extension of the Fabric cut-over to additional tables should
update this note and confirm whether R-012's mitigation has since been
built (a locking/sequence mechanism) before assuming the same gap applies
unchanged.

**Azure SQL connectivity note:** Azure SQL's default "Redirect" connection
policy needs outbound access to ports 11000–11999 in addition to 1433 —
some corporate/ISP networks block that range, which surfaces as a pyodbc
login timeout even though port 1433 itself connects fine. Switching the
server's connectivity setting to "Proxy" (Azure Portal → SQL server →
Networking, or `az sql server conn-policy update --connection-type Proxy`)
routes everything through 1433 and avoids the issue.

**Schema creation:** [`src/lakehouse/azure_sql_migrations.py`](src/lakehouse/azure_sql_migrations.py)
creates the full schema directly in Azure SQL with T-SQL DDL (`NVARCHAR(MAX)`
for `TEXT`, `NVARCHAR(255)` for any column that's `UNIQUE`/indexed — SQL
Server can't key a MAX-length column — `INT` for `INTEGER`, `FLOAT` for
`REAL`, `IDENTITY(1,1)` for `AUTOINCREMENT`). It's a one-shot, re-runnable
creator (guarded by `sys.tables`/`sys.indexes` checks), not a numbered
migration runner like `src/lakehouse/migrations.py` — the SQLite migration
files under `migrations/` remain the source of truth for schema history.

**Enforced at:** [`src/lakehouse/connection.py`](src/lakehouse/connection.py) —
`get_connection()`, `execute_sql()`/`execute_query()`, `AZURE_UPSERT_KEYS`;
[`src/lakehouse/azure_sql_migrations.py`](src/lakehouse/azure_sql_migrations.py).
