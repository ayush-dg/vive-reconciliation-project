---
version: v2.9
METHODOLOGY_VERSION: v5.0 (pbvi_core.md)
frozen: true
---

# Claude.md — v2.9 · FROZEN · 2026-08-06

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-07-24 | CD | Brownfield initial |
| v1.1 | 2026-07-24 | Ayush Kumar Sinha | INV-05 amended — narrowed to per-filename to enable parallel worker pool |
| v2.0 | 2026-07-27 | Ayush Kumar Sinha | Full update — new routes, tables, worker pool, batch intake, review queue, match confidence, routing/aging, bulk approve all reflected |
| v2.1 | 2026-08-05 | Ayush Kumar Sinha | **Storage stack amended for the Fabric migration** (see ARCHITECTURE.md v2.1/v2.2): Database line in §4 now reflects the target split — Bronze on Fabric Lakehouse, Silver + Gold on Fabric Warehouse, operational/Recon tables on SQL database in Fabric, SQLite unchanged for local dev. Extraction chain and OCR facts in §4 corrected against live code trace (Claude Sonnet 4.6 confirmed primary; pytesseract confirmed actively wired, not dormant). Terraform added as the IaC tool for Azure/Fabric provisioning. **The routing code itself is not yet built** — this section states the target, same gap tracked in ARCHITECTURE.md §8. |
| v2.2 | 2026-08-05 | Ayush Kumar Sinha (verified via Claude Code, direct code trace) | **Full verification pass on Sections 2, 3, and 5 against live code.** Every invariant, scope-boundary claim, and rule checked — all PASS. Two caveats surfaced and noted inline: (1) INV-04 is enforced by application logic (`01_document_intake.py`'s validation gate) before Bronze/Silver writes, not by a database-level `NOT NULL` constraint — a write path bypassing that code would not be blocked by the schema itself. (2) Rule 1 (full repo-root file paths) is not uniformly followed — one bare-filename reference found in `claude_sonnet_client.py` (spot-check only, not exhaustive). No contradictions found otherwise. |
| v2.3 | 2026-08-05 | Ayush Kumar Sinha | **INV-01 amended: confidence threshold raised from 0.60 to 0.90**, following the same pattern as INV-05's 2026-07-24 amendment. Recorded as an engineer judgment call, explicitly not backed by accuracy/disposition data — see full basis in `INVARIANTS.md` INV-01 (v1.4). This must propagate consistently across the whole repo (config, code, tests, docs) — tracked as a separate implementation task, not embedded here. |
| v2.4 | 2026-08-05 | Ayush Kumar Sinha (verified via Claude Code) | **Implementation of v2.3 completed.** 0.90 propagated across the repo via full audit; 281 passed / 18 failed on re-run, identical to baseline. `pdfplumber_fallback.py`'s 0.65/0.50 row-confidence values were deliberately left unchanged rather than raised to compensate — real consequence: all pdfplumber-fallback rows now route to human review, not just OCR-derived ones. See `INVARIANTS.md` INV-01 v1.5 for full detail. |
| v2.5 | 2026-08-05 | Ayush Kumar Sinha | **Missed reference caught and fixed on final consistency review.** Section 4's "Deterministic fallback" line still stated the old `0.60` gate value and the pre-amendment consequence (only OCR rows routing to review) — this line predated the v2.3/v2.4 threshold change and wasn't in Claude Code's original audit scope because `docs/Claude.md` itself wasn't included in that audit's target list. Corrected to `0.90` and the accurate consequence (all pdfplumber-fallback rows route to review). **This file has not yet been re-verified end-to-end for other similarly missed self-references — treat this fix as one instance found by manual review, not a guarantee no others remain.** |
| v2.6 | 2026-08-06 | Ayush Kumar Sinha (verified via Claude Code, direct code trace) | **Correction: Sections 3 and 4 previously claimed the Fabric routing "Not yet built" / "not yet implemented" — false.** Direct re-read of `src/lakehouse/connection.py` confirms three Recon-classified tables (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`) are already cut over via `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` (lines 75-119, 255-289) — real, env-var-configured (`FABRIC_SQL_ENDPOINT`, `FABRIC_WAREHOUSE_NAME`), not mock/test-only. Corrected: these three tables target **Fabric Warehouse**, not "SQL database in Fabric" as the target-state bullets describe — that phrase now describes only the target end-state. This mismatch is the confirmed root cause of the IDENTITY/concurrency gap tracked as `discovery/RISK_REGISTER.md` R-012 / `discovery/INVARIANT_CATALOGUE.md` IC-19. Remaining Recon-classified tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) and all of Bronze/Silver/Gold remain unmigrated. Triggered by a teammate doc-review flag, verified against live code before editing. |
| v2.7 | 2026-08-06 | Ayush Kumar Sinha (verified via Claude Code) | **Removed Section 2's "Cross-reference (not a sixth GLOBAL invariant...)" footnote for INV-06.** `docs/INVARIANTS.md` INV-06 has been reclassified from GLOBAL to TASK-SCOPED (v1.6) — it no longer claims GLOBAL status, so the footnote hedging that claim against `pbvi_core.md`'s five-invariant ceiling is no longer needed. Section 2 continues to list exactly five GLOBAL invariants (INV-01 through INV-05, per `pbvi_core.md`'s hard ceiling) plus the mandatory CQ-001 complexity invariant, unchanged by this removal — INV-06 was never one of the five listed here to begin with. |
| v2.8 | 2026-08-06 | Ayush Kumar Sinha | **INV-02 amended — narrow Pass-3-only AI exception added** (see `INVARIANTS.md` v1.7 for full basis). Section 2's INV-02 entry updated verbatim to match. Pass 1/Pass 2 remain 100% deterministic, unchanged; Pass 3 (Claude Sonnet 4.6, residual-only after Passes 1-2, ≤10-candidate SQL-retrieved set, schema-validated output only, never auto-approves at any confidence, confidence hard-capped at 0.85) is now a narrowly permitted exception, matching target architecture D4/D5 (`docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3_1.md`). No Pass 3 code was written — this is a documentation-only invariant change. **Recorded honestly: this is the engineer's (Ayush's) decision alone, made without the teammate/Sprint Lead's review — she is currently on leave. Provisional pending her confirmation on return; not yet a joint or fully methodology-compliant sign-off.** |
| v2.9 | 2026-08-06 | Ayush Kumar Sinha (executed via Claude Code) | **Migration completed: the three cut-over tables now live on a real SQL database in Fabric item — R-012/IC-19 resolved for these three.** Sections 3 and 4 updated: `extraction_cache`/`document_intake_log`/`validation_document_review_queue` repointed from Fabric Warehouse to a genuine SQL database in Fabric item (`FABRIC_SQLDB_ENDPOINT`/`FABRIC_SQLDB_NAME`), with real `IDENTITY(1,1)` primary keys — application code no longer computes `MAX(id)+1` for these three. 184 rows migrated (10/15/159, verified before and after via direct `COUNT(*)` and the live `execute_query_fabric()` app path). `get_fabric_connection()` repoint was same-signature — no caller changes, per Rule 6. Full details: `docs/ARCHITECTURE.md` v2.5, `RULES.md` RULE-13. Remaining Recon tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) and all of Bronze/Silver/Gold remain unmigrated — still their own, separate decision. Old Fabric Warehouse copies deliberately left in place, not dropped. |
| v3.0 | 2026-08-23 | Ayush Kumar Sinha (via Claude Code) | **INV-04 amended: `outstanding_amount` no longer required to be non-null in Silver.** `invoice_number` (or `ro_number` fallback) remains the only hard identifier requirement. Direct engineer instruction, confirmed explicitly after the conflict with the prior "never negotiable" wording was surfaced first. Motivated by "View Extracted Data" needing to show every row that reaches Bronze, including blank-amount payment/credit lines previously diverted straight to an `EXTRACTION_INCOMPLETE` exception before ever reaching Bronze. `write_missing_amount_exception()` removed (no remaining call sites); `get_skip_reason()` narrowed to identifier-only; `get_extracted_rows_for_job()` (`web/queries.py`) now reads `bronze_vendor_statement_raw` directly instead of Silver+exceptions. See `INVARIANTS.md` INV-04 v1.8 for full basis. |

---

## Section 1 — System Intent

VIVE Reconciliation extracts line-item data from vendor PDF statements, compares it deterministically against VIVE Collision's ERP records (currently simulated via a mock generator pending live NetSuite access), and surfaces discrepancies for a human AP team to review. It does not itself approve, reject, or execute any payment. Success looks like: every vendor statement's invoices are either matched with high confidence or correctly routed to human review — never silently misclassified either way.

---

## Section 2 — Hard Invariants

**INV-01 (amended 2026-08-05):** Any row whose extraction confidence falls below `0.90` must be routed to human review — never silently pass into Bronze/Silver. **Raised from `0.60`.** Recorded honestly as an engineer judgment call, not a data-validated decision — see `INVARIANTS.md` INV-01 for the full calibration-check basis (82% of the checked database was a stale pre-fix confidence constant; only 2 human dispositions existed in total, too few to judge accuracy). Revisit once real production disposition data exists. **Implemented and verified 2026-08-05:** propagated repo-wide (config, code, tests, docs); full suite re-run at 281 passed / 18 failed, identical to pre-change baseline, no regression. **Known consequence, deliberately not compensated for:** `pdfplumber_fallback.py`'s row-confidence values (0.65/0.50) were left unchanged, so all pdfplumber-fallback rows now route to review regardless of OCR status — see `INVARIANTS.md` INV-01 v1.5.
This is never negotiable.

**INV-02 (amended 2026-08-06):** The matching engine's Pass 1 and Pass 2 remain 100% deterministic — no AI model is ever consulted in these passes, for any reason. This invariant now permits a narrow, explicitly scoped exception for Pass 3 disambiguation only, matching the target architecture's D4/D5 design exactly (`docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3_1.md`):
- Pass 3 may consult Claude Sonnet 4.6 ONLY on the residual left unresolved after Passes 1-2 (target: single-digit percent of lines at steady state).
- Pass 3 reads a SQL-retrieved candidate set capped at ≤10 records.
- Pass 3 output must pass schema validation before use; free-form AI text may never directly drive a match or accounting action.
- Pass 3 output NEVER auto-approves, at any confidence level — this is a permanent design constraint, not a threshold to be tuned. `review_required` must always be `true` for any Pass 3 result.
- Pass 3 confidence is hard-capped at 0.85, strictly below any auto-approve threshold in the system.
- Any implementation of Pass 3 that violates any of the above five constraints is out of scope for this amendment and would require a separate, new invariant decision.

**Basis for this amendment — recorded honestly:** this is the engineer's (Ayush's) decision, made 2026-08-06, WITHOUT the teammate/Sprint Lead's review — she is on leave at the time of this decision. This amendment should be treated as provisional until she confirms or revises it. Do not cite this as a joint or fully methodology-compliant sign-off until that confirmation happens.

**Status:** No Pass 3 code exists yet. Pass 1/Pass 2 remain confirmed deterministic (see `INVARIANTS.md` INV-02 for the 2026-08-05 code-trace verification, which predates this amendment and covers Pass 1/2 only). This amendment records the invariant ahead of implementation — per explicit instruction, no Pass 3 code was written as part of this change.
This is never negotiable — Pass 1/2 determinism and each of the five Pass 3 constraints above are individually non-negotiable. This amendment narrows scope; it does not weaken enforcement.

**INV-03:** No totals/summary row (grand total, subtotal, balance-forward) may ever be ingested and validated as if it were a real invoice line.
This is never negotiable.

**INV-04 (amended 2026-08-23):** `invoice_number` must never be null in any row written to the Silver layer. `outstanding_amount` MAY be null — this requirement was removed by direct engineer instruction, confirmed explicitly after the conflict with the prior wording was surfaced first (see `INVARIANTS.md` INV-04 v1.8 for full basis). A blank amount no longer diverts a row away from Bronze/Silver at extraction time; every row with an invoice identifier reaches Bronze/Silver regardless of amount, and whether it's a genuine exception is now decided by the matching engine (`src/matching/engine.py`), not extraction.
`invoice_number`-never-null remains never negotiable; the `outstanding_amount` clause is the one relaxed.
**Verified 2026-08-23 (Claude Code, direct trace + real-data test):** `write_missing_amount_exception()` (previously raised `EXTRACTION_INCOMPLETE` for a blank `outstanding_amount`) removed, no remaining call sites. `get_skip_reason()` narrowed to identifier-only (`invoice_number` or `ro_number` fallback); `validate_invoice()`'s `required_fields` no longer includes `outstanding_amount` (`config/validation/extraction_rules.json`). **Caveat (unchanged):** `migrations/001_initial_schema.sql:61,69` defines both columns as nullable at the schema level — a write path that bypassed the intake code (e.g. a direct SQL insert) would not be stopped by the database itself. The remaining `invoice_number` check still depends entirely on every write going through the intake gate.

**INV-05 (amended 2026-07-24):** At most one job per distinct `pdf_filename` may be in `PROCESSING` status at any time. Different filenames MAY process concurrently up to `WORKER_POOL_SIZE` (default 3). The original system-wide statement was superseded by direct engineer instruction to enable the parallel worker pool.
This is never negotiable.

**CQ-001:** Each function, method, or handler must have a single stateable purpose. Conditional nesting exceeding two levels is a structural violation.
This is never negotiable.

**Note (v2.1):** none of the five hard invariants change under the Fabric migration. INV-04 in particular (`invoice_number`/`outstanding_amount` never null in Silver) applies regardless of which Fabric item Silver physically sits on — this is a data-quality rule, not a storage-location rule.

**Note (v2.2):** INV-01 through INV-05 all independently verified against live code on 2026-08-05 — all PASS, evidence inline above. CQ-001 is a structural style rule, not machine-checkable, and was not verified.

---

## Section 3 — Scope Boundary

**In scope for build work:**
- `src/ai/` — extraction provider clients
- `src/lakehouse/` — connection, migrations. **The single place that selects the storage backend. Currently two live paths: `get_connection()`/`execute_sql()`/`execute_query()` (Azure SQL vs. SQLite) still serve Bronze/Silver/Gold and four Recon tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`); `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` cut over three Recon tables (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`) to a real **SQL database in Fabric** item as of 2026-08-06 — see changelog v2.9 — matching the target-state table-group routing exactly, no longer Fabric Warehouse. R-012/IC-19 resolved for these three. Completing the migration for the remaining four Recon tables and Bronze/Silver/Gold — see ARCHITECTURE.md §9 — is still an open, explicit build task.**
- `src/matching/` — matching engine
- `src/mock_erp/`, `src/normalization.py`, `src/storage/`
- `web/` — FastAPI app, all routers, worker, queries
- `notebooks/`, `scripts/` — pipeline entry points
- `migrations/` — new numbered migration files only, never hand-edited DDL. **Under the Fabric migration, this becomes three separate migration tracks (Lakehouse, Warehouse, SQL database in Fabric) rather than one — do not merge them into a single migration file (ARCHITECTURE.md §9, requirement 4).**
- `config/` — provider chain, validation rules, matching tolerances, shop_owners.json
- **`terraform/` (new)** — Azure/Fabric resource provisioning, once added to the repo

**Out of scope — do not build without an explicit new enhancement decision:**
- Live NetSuite integration (`src/mock_erp/generator.py` stays until API access is granted)
- Per-vendor column mapping configuration
- Any AI involvement inside `src/matching/engine.py`
- Full role-based permission tiers (Admin/Reviewer split)
- Document-level aggregate confidence gate
- Wiring the mock ERP generator into the dashboard (must remain CLI-only)
- Email alerts (Step 9) — provider decision pending
- Fault isolation per file in a batch (Step 6) — not yet built
- Completing the Fabric routing implementation for the remaining tables — target state is documented (ARCHITECTURE.md §9); three Recon tables are done and on the correct item type (SQL database in Fabric, since 2026-08-06 — see §4 and R-012/IC-19, now resolved for those three), but finishing the remaining four Recon tables plus Bronze/Silver/Gold is a distinct, explicit build task, not something to do incidentally while touching `connection.py` for other reasons.

**Always out of scope:** `sample_data/`, `backup/`, `venv/`, `discovery/` (BCE artifacts).

**Verified 2026-08-05 (Claude Code, direct trace):** every path listed above confirmed to exist at exactly that location; every "out of scope" item confirmed genuinely not built (no live NetSuite calls, no per-vendor config, no AI in `src/matching/engine.py`, no Admin/Reviewer role split — `web/routers/users.py:4` states this directly, no document-level aggregate confidence gate, mock ERP generator not wired into any dashboard route, no email-sending code found repo-wide). One nuance on "fault isolation per file in a batch": confirmed genuinely absent — `web/routers/intake_trigger.py:135-136` loops over blob-created events with no per-event `try/except`, so one bad event can abort the rest of that delivery batch. (Per-job isolation *after* queueing, in `web/worker.py`, does exist — that's a separate, already-built layer and doesn't contradict this gap.)

---

## Section 4 — Fixed Stack

**Language/runtime:** Python 3.12, Docker

**Web framework:** FastAPI >=0.110.0, uvicorn >=0.27.0, Jinja2 >=3.1.0, python-multipart, itsdangerous, bcrypt

**Database — target state (v2.1, Fabric migration):**
- **Bronze** (`bronze_vendor_statement_raw`, `bronze_internal_erp_raw`) → **Fabric Lakehouse**
- **Silver** (`silver_reconciliation_standard`) → **Fabric Warehouse**
- **Gold** (`gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary`) → **Fabric Warehouse**
- **Recon / operational tables** (`jobs`, `exception_dispositions`, `validation_document_review_queue`, `ai_audit_log`, `extraction_cache`, `document_intake_log`, `users`) → **SQL database in Fabric** — kept off Lakehouse/Warehouse because this data carries live financial/audit consequences and needs enforced foreign keys and row-level concurrency (see ARCHITECTURE.md §2.2/§4).
- **SQLite** — local/dev/test, unchanged.
- **Current actual code (updated 2026-08-06 — see changelog v2.9):** `src/lakehouse/connection.py` has two live paths, not one. `get_connection()`/`execute_sql()`/`execute_query()` still select a single **Azure SQL Database** via `AZURE_SQL_SERVER` (or SQLite locally) for Bronze, Silver, Gold, and four Recon tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) — unmigrated, R-012/IC-19 open for any future cut-over of these. `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` cut over the remaining three Recon tables (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`) to a real **SQL database in Fabric** item (`FABRIC_SQLDB_ENDPOINT`/`FABRIC_SQLDB_NAME`) — repointed 2026-08-06 from Fabric Warehouse, matching the target bullet above exactly. **R-012/IC-19 are resolved for these three tables**: SQL database in Fabric supports real `IDENTITY(1,1)` columns (schema created via `scripts/create_fabric_sqldb_schema.py`), so the engine assigns ids now, not `MAX(id) + 1` in application code. 184 existing rows migrated via `scripts/migrate_fabric_data_to_sqldb.py`, verified 10/15/159 before and after. Old Fabric Warehouse copies deliberately left in place as a rollback safety net, not dropped. Completing the migration for the remaining four Recon tables and Bronze/Silver/Gold — see ARCHITECTURE.md §8 for the current-state gap and §9 for the scoped implementation task.

**AI extraction — verified against live code, 2026-08-05:**
- anthropic — **Claude Sonnet 4.6** (active primary, Azure AI Foundry). Confirmed via `config/ai/active_provider.json` (`provider_chain[0] = "claude_sonnet"`) and the actual runtime call path (`document_understanding_engine.py` → `client_factory.py` → `claude_sonnet_client.py`), not config alone.
- anthropic — **Claude Haiku 4.5** — exception/`--explain` narrative only (`explanation_service.py`, `config/ai/claude.json`). Never used for extraction.
- openai — Azure OpenAI (registered, dormant)
- google-genai — Gemini 2.5 Flash (registered, dormant)
- Mistral — direct API (registered, dormant)
- Azure Document Intelligence (registered, dormant, prior primary — confirmed **not** in the active `provider_chain` and not called from the extraction path)

**Deterministic fallback:** pdfplumber (`provider_chain[1]`), **pytesseract — confirmed actively wired** (not dormant): invoked per-page inside `pdfplumber_fallback.py` via `ocr_extractor.py` when a page's native text layer falls under a 500-char threshold. Row confidence: `line_confidence = 0.65` for native/non-OCR pdfplumber rows, `0.50` for OCR-derived rows — **both now below the 0.90 validation gate** (raised 2026-08-05 from 0.60, see INV-01), so **all pdfplumber-fallback rows, OCR-derived or not, route to human review**, not just the OCR ones as before the amendment. `extract_text_with_ocr()` (whole-document OCR) has no callers and is dead code. pdf2image, pypdf also present.

**Storage:** azure-storage-blob (archival to `vivereconciliation` + drop zone `viverecondropzone`) — unchanged by the Fabric migration, which affects structured data only, not blob/file storage.

**Infrastructure-as-code (new, v2.1):** **Terraform** — provisioning tool for Azure/Fabric resources (Lakehouse, Warehouse, SQL database in Fabric, plus existing Azure resources). Not yet present in the repo as of this writing.

**Security note:** the drop-zone webhook (`/api/intake-trigger`) was unauthenticated end-to-end until 2026-07-25 — now fixed in code (shared secret, pinned container, event-count cap); see `discovery/RISK_REGISTER.md` R-009.

**Worker:** 3-thread pool, configurable via `VIVE_WORKER_POOL_SIZE`. AI rate limit via `VIVE_MAX_CONCURRENT_AI_CALLS` (default 2). **Note:** the job queue (`jobs` table) the worker polls is one of the tables moving to the Recon layer (SQL database in Fabric) — worker polling logic itself is unchanged, but its data-access calls will need to route there once the migration lands.

**Testing:** pytest — **281 passed, 18 failed, 0 skipped (299 total)**, verified by live run 2026-08-05. All 18 failures are local-environment specific (17 from Azure CLI auth blocked by this machine's Windows Application Control policy; 1 from a known Windows `NamedTemporaryFile` lock issue) — not code defects. Supersedes an earlier, stale 45/46 figure.

**Key environment variables:** `AZURE_CLAUDE_API_KEY`, `AZURE_CLAUDE_ENDPOINT`, `AZURE_CLAUDE_SONNET_DEPLOYMENT`, `AZURE_CLAUDE_DEPLOYMENT`, `AZURE_SQL_SERVER`, `AZURE_SQL_DATABASE`, `AZURE_SQL_USERNAME`, `AZURE_SQL_PASSWORD`, `AZURE_BLOB_CONNECTION_STRING`, `AZURE_BLOB_DROPZONE_CONNECTION_STRING`, `VIVE_WORKER_POOL_SIZE`, `VIVE_MAX_CONCURRENT_AI_CALLS`, `WEB_SESSION_SECRET`. Fabric Warehouse vars remain, still used by the Bronze/Silver/Gold target design once built: `FABRIC_SQL_ENDPOINT`, `FABRIC_WAREHOUSE_NAME`, `FABRIC_TENANT_ID` (`src/lakehouse/connection.py:102-104` historically; retained for the Warehouse item itself, which still exists — only the three Recon tables' *connection* moved off it). **Added 2026-08-06 (see changelog v2.9):** `FABRIC_SQLDB_ENDPOINT`, `FABRIC_SQLDB_NAME` — the real SQL database in Fabric item now used by `get_fabric_connection()` for `extraction_cache`/`document_intake_log`/`validation_document_review_queue`. Env vars for the remaining target items (Lakehouse, and a SQL database in Fabric item for the other four Recon tables) are not yet defined — exact names TBD when that routing implementation (ARCHITECTURE.md §9) is built. Do not invent or assume names for those ahead of that work.

---

## Section 5 — Rules

**Rule 1:** All file references use full paths from repo root — never bare filenames.
**Verified 2026-08-05 (spot-check, not exhaustive):** mostly followed — one counterexample found in `src/ai/claude_sonnet_client.py:565-566`, which references `pdfplumber_fallback.py:_extract_invoice_row()` as a bare filename instead of `src/ai/pdfplumber_fallback.py`. Worth a cleanup pass but not treated as a structural violation.

**Rule 2:** All files inside any enhancement package carry their ENH-NNN prefix.

**Rule 3:** Dashboard KPI cards must live-query `gold_exceptions` for exception counts — never trust the `gold_reconciliation_summary` snapshot directly.

**Rule 4:** All pipeline subprocesses (run_full_pipeline.py and all notebooks) must call `load_dotenv(os.path.join(PROJECT_ROOT, ".env"))` with an explicit path — bare `load_dotenv()` silently fails to find `.env` when invoked as a subprocess from a different working directory, causing the process to fall back to SQLite instead of Azure SQL.

**Rule 5:** Job claiming must use the atomic `UPDATE ... WHERE NOT EXISTS` guard in `web/queries.py:claim_next_pending_job()` — never a two-step SELECT then UPDATE.

**Rule 6 (new, v2.1):** Any code change touching `src/lakehouse/connection.py` for the Fabric migration must be scoped exactly as described in ARCHITECTURE.md §9 — table-group routing only. Do not fold in unrelated fixes, and do not silently resolve cross-table-group transaction assumptions (e.g. a transaction spanning a Bronze write and a Recon write); flag them and confirm with the engineer first.