---
version: v2.6
METHODOLOGY_VERSION: v5.0 (pbvi_core.md)
frozen: true
---

# Claude.md — v2.6 · FROZEN · 2026-08-06

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
| v2.6 | 2026-08-06 | Ayush Kumar Sinha (verified via Claude Code) | **Removed Section 2's "Cross-reference (not a sixth GLOBAL invariant...)" footnote for INV-06.** `docs/INVARIANTS.md` INV-06 has been reclassified from GLOBAL to TASK-SCOPED (v1.6) — it no longer claims GLOBAL status, so the footnote hedging that claim against `pbvi_core.md`'s five-invariant ceiling is no longer needed. Section 2 continues to list exactly five GLOBAL invariants (INV-01 through INV-05, per `pbvi_core.md`'s hard ceiling) plus the mandatory CQ-001 complexity invariant, unchanged by this removal — INV-06 was never one of the five listed here to begin with. |

---

## Section 1 — System Intent

VIVE Reconciliation extracts line-item data from vendor PDF statements, compares it deterministically against VIVE Collision's ERP records (currently simulated via a mock generator pending live NetSuite access), and surfaces discrepancies for a human AP team to review. It does not itself approve, reject, or execute any payment. Success looks like: every vendor statement's invoices are either matched with high confidence or correctly routed to human review — never silently misclassified either way.

---

## Section 2 — Hard Invariants

**INV-01 (amended 2026-08-05):** Any row whose extraction confidence falls below `0.90` must be routed to human review — never silently pass into Bronze/Silver. **Raised from `0.60`.** Recorded honestly as an engineer judgment call, not a data-validated decision — see `INVARIANTS.md` INV-01 for the full calibration-check basis (82% of the checked database was a stale pre-fix confidence constant; only 2 human dispositions existed in total, too few to judge accuracy). Revisit once real production disposition data exists. **Implemented and verified 2026-08-05:** propagated repo-wide (config, code, tests, docs); full suite re-run at 281 passed / 18 failed, identical to pre-change baseline, no regression. **Known consequence, deliberately not compensated for:** `pdfplumber_fallback.py`'s row-confidence values (0.65/0.50) were left unchanged, so all pdfplumber-fallback rows now route to review regardless of OCR status — see `INVARIANTS.md` INV-01 v1.5.
This is never negotiable.

**INV-02:** The matching engine makes every match/exception decision through deterministic rules only — no AI model is ever consulted inside the matching step, for any reason. `match_confidence` scoring is also deterministic (rule-based, not AI).
This is never negotiable.

**INV-03:** No totals/summary row (grand total, subtotal, balance-forward) may ever be ingested and validated as if it were a real invoice line.
This is never negotiable.

**INV-04:** `invoice_number` and `outstanding_amount` must never be null in any row written to the Silver layer.
This is never negotiable.
**Verified 2026-08-05 (Claude Code, direct trace):** enforced today via **application-level guard**, not a database constraint — `01_document_intake.py:106-110` rejects any row with a null/empty `invoice_number` or `outstanding_amount` as `MISSING_MANDATORY_FIELD` before it can reach `write_to_bronze()`/Silver. **Caveat:** `migrations/001_initial_schema.sql:61,69` defines both columns as nullable at the schema level — a write path that bypassed the intake code (e.g. a direct SQL insert) would not be stopped by the database itself. The invariant currently depends entirely on every write going through the intake gate.

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
- `src/lakehouse/` — connection, migrations. **Currently the single place that selects SQLite vs. Azure SQL; under the Fabric migration this becomes the place that routes by table group (Bronze/Silver/Gold/Recon) — see ARCHITECTURE.md §9. Not yet built.**
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
- The Fabric routing implementation itself — target state is documented (ARCHITECTURE.md §9), but this is a distinct, explicit build task, not something to do incidentally while touching `connection.py` for other reasons.

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
- **Current actual code** (as of 2026-08-05) still selects a single **Azure SQL Database** via `AZURE_SQL_SERVER`, routed through `pyodbc`, in `src/lakehouse/connection.py`. The Fabric split above is the target, not yet implemented — see ARCHITECTURE.md §8 for the gap and §9 for the scoped implementation task.

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

**Key environment variables:** `AZURE_CLAUDE_API_KEY`, `AZURE_CLAUDE_ENDPOINT`, `AZURE_CLAUDE_SONNET_DEPLOYMENT`, `AZURE_CLAUDE_DEPLOYMENT`, `AZURE_SQL_SERVER`, `AZURE_SQL_DATABASE`, `AZURE_SQL_USERNAME`, `AZURE_SQL_PASSWORD`, `AZURE_BLOB_CONNECTION_STRING`, `AZURE_BLOB_DROPZONE_CONNECTION_STRING`, `VIVE_WORKER_POOL_SIZE`, `VIVE_MAX_CONCURRENT_AI_CALLS`, `WEB_SESSION_SECRET`. **Fabric-specific env vars (Lakehouse/Warehouse/SQL database in Fabric connection strings or workspace IDs) are not yet defined — exact names TBD when the routing implementation (ARCHITECTURE.md §9) is actually built. Do not invent or assume names for these ahead of that work.**

---

## Section 5 — Rules

**Rule 1:** All file references use full paths from repo root — never bare filenames.
**Verified 2026-08-05 (spot-check, not exhaustive):** mostly followed — one counterexample found in `src/ai/claude_sonnet_client.py:565-566`, which references `pdfplumber_fallback.py:_extract_invoice_row()` as a bare filename instead of `src/ai/pdfplumber_fallback.py`. Worth a cleanup pass but not treated as a structural violation.

**Rule 2:** All files inside any enhancement package carry their ENH-NNN prefix.

**Rule 3:** Dashboard KPI cards must live-query `gold_exceptions` for exception counts — never trust the `gold_reconciliation_summary` snapshot directly.

**Rule 4:** All pipeline subprocesses (run_full_pipeline.py and all notebooks) must call `load_dotenv(os.path.join(PROJECT_ROOT, ".env"))` with an explicit path — bare `load_dotenv()` silently fails to find `.env` when invoked as a subprocess from a different working directory, causing the process to fall back to SQLite instead of Azure SQL.

**Rule 5:** Job claiming must use the atomic `UPDATE ... WHERE NOT EXISTS` guard in `web/queries.py:claim_next_pending_job()` — never a two-step SELECT then UPDATE.

**Rule 6 (new, v2.1):** Any code change touching `src/lakehouse/connection.py` for the Fabric migration must be scoped exactly as described in ARCHITECTURE.md §9 — table-group routing only. Do not fold in unrelated fixes, and do not silently resolve cross-table-group transaction assumptions (e.g. a transaction spanning a Bronze write and a Recon write); flag them and confirm with the engineer first.