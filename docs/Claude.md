---
version: v3.1
METHODOLOGY_VERSION: v5.0 (pbvi_core.md)
frozen: true
---

# Claude.md — v3.1 · FROZEN · 2026-10-30

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
| v3.1 | 2026-10-30 | Vaishali Rao Yellur (via Claude Code) | **Dead content removed.** Sections 1, 3 and 4 rewritten against current code: matching is against NetSuite (Fabric copy or SuiteAnalytics Connect, `src/matching/fabric_matching.py`), not a mock ERP; storage now spans SQLite / Azure SQL / SQL database in Fabric / Fabric Lakehouse / Fabric Warehouse; Gemini, Mistral, Azure OpenAI and Document Intelligence removed from the stack (deleted 2026-10-30); per-vendor Python extractors and Terraform (`deploy/`) listed as built. Out-of-scope items that have since been built (live NetSuite, per-vendor config) and mock-ERP items dropped. Pointers to deleted files (`INVARIANTS.md`, `RULES.md`, `discovery/`, removed scripts) and the dated verification notes removed; invariant wording unchanged. Rule 6 no longer points to the removed ARCHITECTURE.md §9 migration prompt. |

---

## Section 1 — System Intent

VIVE Reconciliation extracts line-item data from vendor PDF statements, compares it deterministically against VIVE Collision's NetSuite vendor bills and credits, and surfaces discrepancies for a human AP team to review. It does not itself approve, reject, or execute any payment; the optional NetSuite write-back (`docs/NETSUITE_WRITEBACK.md`) only marks bills/credits as reconciled or flags exceptions. Success looks like: every vendor statement's invoices are either matched with high confidence or correctly routed to human review — never silently misclassified either way.

---

## Section 2 — Hard Invariants

**INV-01 (amended 2026-08-05):** Any row whose extraction confidence falls below `0.90` must be routed to human review — never silently pass into Bronze/Silver. **Raised from `0.60`.** Recorded as an engineer judgment call, not a data-validated decision; revisit once real production disposition data exists. **Known consequence, deliberately not compensated for:** `src/ai/pdfplumber_fallback.py`'s row-confidence values (0.65/0.50) were left unchanged, so all pdfplumber-fallback rows route to review regardless of OCR status.
This is never negotiable.

**INV-02 (amended 2026-08-06):** The matching engine's Pass 1 and Pass 2 remain 100% deterministic — no AI model is ever consulted in these passes, for any reason. This invariant permits a narrow, explicitly scoped exception for Pass 3 disambiguation only, matching the target architecture's D4/D5 design (`docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3.1.md`):
- Pass 3 may consult Claude Sonnet 4.6 ONLY on the residual left unresolved after Passes 1-2 (target: single-digit percent of lines at steady state).
- Pass 3 reads a SQL-retrieved candidate set capped at ≤10 records.
- Pass 3 output must pass schema validation before use; free-form AI text may never directly drive a match or accounting action.
- Pass 3 output NEVER auto-approves, at any confidence level — this is a permanent design constraint, not a threshold to be tuned. `review_required` must always be `true` for any Pass 3 result.
- Pass 3 confidence is hard-capped at 0.85, strictly below any auto-approve threshold in the system.
- Any implementation of Pass 3 that violates any of the above five constraints is out of scope for this amendment and would require a separate, new invariant decision.

**Basis for this amendment:** the engineer's (Ayush's) decision, made 2026-08-06, without the Sprint Lead's review (on leave at the time). Treat as provisional until she confirms or revises it.

**Status:** No Pass 3 code exists. This amendment records the invariant ahead of implementation.
This is never negotiable — Pass 1/2 determinism and each of the five Pass 3 constraints above are individually non-negotiable. This amendment narrows scope; it does not weaken enforcement.

**INV-03:** No totals/summary row (grand total, subtotal, balance-forward) may ever be ingested and validated as if it were a real invoice line.
This is never negotiable.

**INV-04 (amended 2026-08-23):** `invoice_number` must never be null in any row written to the Silver layer. `outstanding_amount` MAY be null — this requirement was removed by direct engineer instruction. Every row with an invoice identifier (`invoice_number`, or the `ro_number` fallback) reaches Bronze/Silver regardless of amount, and whether it's a genuine exception is decided by matching (`src/matching/fabric_matching.py`), not extraction. **Caveat:** the check lives in the intake code (`get_skip_reason()` in `notebooks/01_document_intake.py`, `config/validation/extraction_rules.json`), not a schema constraint — a write path that bypassed intake would not be stopped by the database.
`invoice_number`-never-null remains never negotiable; the `outstanding_amount` clause is the one relaxed.

**INV-05 (amended 2026-07-24):** At most one job per distinct `pdf_filename` may be in `PROCESSING` status at any time. Different filenames MAY process concurrently up to `WORKER_POOL_SIZE` (default 3). The original system-wide statement was superseded by direct engineer instruction to enable the parallel worker pool.
This is never negotiable.

**CQ-001:** Each function, method, or handler must have a single stateable purpose. Conditional nesting exceeding two levels is a structural violation.
This is never negotiable.

---

## Section 3 — Scope Boundary

**In scope for build work:**
- `src/ai/` — Claude extraction/explanation clients, pdfplumber + OCR fallback
- `src/extraction/` — per-vendor Python extractors (`src/extraction/python_library/adapter.py` maps them)
- `src/validation/` — statement-level validation gate
- `src/lakehouse/` — the single place that selects the storage backend (see Section 4)
- `src/matching/` — matching (`src/matching/fabric_matching.py`)
- `src/netsuite/` — NetSuite reads (Fabric copy or SuiteAnalytics Connect) and write-back
- `src/rerun/`, `src/storage/`, `src/normalization.py`, `src/vendor_identity.py`, `src/shop_owners.py`
- `web/` — FastAPI app, all routers, worker, queries
- `notebooks/`, `scripts/` — pipeline entry points and admin tools
- `dbt/vive_recon/` — Silver models, macros and seeds
- `migrations/` — new numbered migration files only, never hand-edited DDL
- `config/` — provider chain, validation rules, NetSuite overrides/locations, vendor aliases, shop_owners.json
- `deploy/` (Terraform: App Service dev/prod, mailbox Logic App) and `azure-functions/mailbox-sync`

**Out of scope — do not build without an explicit new enhancement decision:**
- Any AI involvement inside `src/matching/` (beyond the INV-02 Pass 3 exception)
- Full role-based permission tiers (Admin/Reviewer split)
- Email alerts — provider decision pending
- Fault isolation per file in a batch — `web/routers/intake_trigger.py` loops over blob-created events with no per-event `try/except`, so one bad event can abort the rest of that delivery. (Per-job isolation after queueing, in `web/worker.py`, does exist.)

**Always out of scope:** `sample_data/`, `venv/`.

---

## Section 4 — Fixed Stack

**Language/runtime:** Python 3.12, Docker (built with `az acr build`, run on Azure App Service)

**Web framework:** FastAPI >=0.110.0, uvicorn >=0.27.0, Jinja2 >=3.1.0, python-multipart, itsdangerous, bcrypt

**Storage (current, 2026-10-30):**
- **SQLite** — local/dev/test (`lakehouse/reconciliation.db`, built from `migrations/`).
- **Azure SQL** — when `AZURE_SQL_SERVER` is set: `jobs`, `exception_dispositions`, `users`, `ai_audit_log` and the older `gold_*` tables, via `get_connection()`/`execute_sql()`/`execute_query()` in `src/lakehouse/connection.py`.
- **SQL database in Fabric** — when `FABRIC_SQLDB_ENDPOINT` is set: `extraction_cache`, `document_intake_log`, `validation_document_review_queue`, via `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()`.
- **Fabric Lakehouse** — Bronze (`bronze.raw_statement`, `src/lakehouse/bronze_raw.py`), Silver (`silver.statement_line`, built by dbt or `src/lakehouse/silver_build.py`), and the nightly NetSuite copy (`bronze.netsuite_vendorbill`/`vendorcredit`/`vendor`).
- **Fabric Warehouse** — matching results (`silver.recon_matched_invoices`/`recon_exceptions`/`recon_summary`, written by `src/matching/fabric_matching.py`).

**AI extraction:**
- anthropic — **Claude Sonnet 4.6** (primary, Azure AI Foundry): `config/ai/active_provider.json` `provider_chain[0] = "claude_sonnet"`, call path `src/ai/document_understanding_engine.py` → `src/ai/client_factory.py` → `src/ai/claude_sonnet_client.py`.
- anthropic — **Claude Haiku 4.5** — exception/`--explain` narrative only (`src/ai/explanation_service.py`, `config/ai/claude.json`). Never used for extraction.
- Known text-layer vendors bypass AI entirely: `notebooks/01_document_intake.py` routes them to the per-vendor extractors in `src/extraction/python_library/`.

**Deterministic fallback:** pdfplumber (`provider_chain[1]`), with pytesseract OCR invoked per page inside `src/ai/pdfplumber_fallback.py` via `src/ai/ocr_extractor.py` when a page's native text layer falls under a 500-char threshold. Row confidence: `0.65` native, `0.50` OCR — both below the 0.90 gate, so all pdfplumber-fallback rows route to human review.

**NetSuite:** reads from the Fabric copy (default) or live SuiteAnalytics Connect (`NETSUITE_SOURCE=connect`, `src/netsuite/connect_source.py`); write-back is off unless `NETSUITE_WRITEBACK_ENABLED=true` (`docs/NETSUITE_WRITEBACK.md`).

**Storage (files):** azure-storage-blob (archival to `vivereconciliation` + drop zone `viverecondropzone`); mailbox intake via Logic Apps (`deploy/mailbox-logic-app/`).

**Infrastructure-as-code:** Terraform under `deploy/`. State is local to each folder — never delete the `terraform.tfstate*` files.

**Security note:** the drop-zone webhook (`/api/intake-trigger`) requires a shared secret, a pinned container and an event-count cap (fixed 2026-07-25; it was unauthenticated before).

**Worker:** 3-thread pool, configurable via `VIVE_WORKER_POOL_SIZE`. AI rate limit via `VIVE_MAX_CONCURRENT_AI_CALLS` (default 2).

**Testing:** pytest. Local run 2026-10-30: 1833 passed, 52 failed, 47 skipped — all 52 are environment-specific (Azure credentials, missing local tables/PDFs, Tesseract, a Windows file lock), not code defects.

**Key environment variables:** `AZURE_CLAUDE_API_KEY`, `AZURE_CLAUDE_ENDPOINT`, `AZURE_CLAUDE_SONNET_DEPLOYMENT`, `AZURE_CLAUDE_DEPLOYMENT`, `AZURE_SQL_SERVER`, `AZURE_SQL_DATABASE`, `AZURE_SQL_USERNAME`, `AZURE_SQL_PASSWORD`, `AZURE_BLOB_CONNECTION_STRING`, `AZURE_BLOB_DROPZONE_CONNECTION_STRING`, `FABRIC_SQLDB_ENDPOINT`, `FABRIC_SQLDB_NAME`, `NETSUITE_SOURCE`, `NETSUITE_CONNECT_*`, `NETSUITE_WRITEBACK_ENABLED`, `VALIDATION_GATE_ENABLED`, `VIVE_WORKER_POOL_SIZE`, `VIVE_MAX_CONCURRENT_AI_CALLS`, `WEB_SESSION_SECRET`. `.env.example` lists the full set.

---

## Section 5 — Rules

**Rule 1:** All file references use full paths from repo root — never bare filenames.

**Rule 2:** All files inside any enhancement package carry their ENH-NNN prefix.

**Rule 3:** Dashboard KPI cards must live-query exception rows for exception counts — never trust a reconciliation-summary snapshot directly.

**Rule 4:** All pipeline subprocesses (`scripts/run_full_pipeline.py` and all notebooks) must call `load_dotenv(os.path.join(PROJECT_ROOT, ".env"))` with an explicit path — bare `load_dotenv()` silently fails to find `.env` when invoked as a subprocess from a different working directory, causing the process to fall back to SQLite instead of Azure SQL.

**Rule 5:** Job claiming must use the atomic `UPDATE ... WHERE NOT EXISTS` guard in `web/queries.py:claim_next_pending_job()` — never a two-step SELECT then UPDATE.

**Rule 6:** Do not silently resolve cross-store transaction assumptions (e.g. one transaction spanning a Fabric Lakehouse write and an Azure SQL write) — they are different engines; flag them and confirm with the engineer first.
