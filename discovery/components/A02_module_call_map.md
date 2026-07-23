## Module Roster — VIVE Reconciliation
Generated: 2026-07-23 by BCE Stage 2 Session A (CC)
Note: these IDs are permanent. Do not reassign at later sessions.

**Methodology adaptation note (flagged for engineer confirmation):** VIVE's UI is server-rendered Jinja2 templates behind FastAPI routes — there is no client-side routing, no client-side component tree, and no client-side state store (session state lives server-side). The PBVI-011 UI taxonomy (`route`/`page`/`layout`/`component`/`store`) is designed for SPA frontends and doesn't map cleanly here. Judgment call applied: FastAPI routers are classified `serving` (they are the request entry points *and* the render boundary — the route handler IS the "page"), `web/worker.py` is `pipeline` (background batch processing), and `web/app.py`/`deps.py`/`queries.py`/`start.py` are `infra` (bootstrap, shared utilities, data-access layer). `web/static/app.js` is treated as a page-local UI resource, not a separate module, since it has no independent responsibility beyond one page's upload UX. Templates (`web/templates/*.html`) are presentation artifacts bundled with their owning router, not independently modeled. Flagged as **P2 open item** for engineer sign-off — if this project later adds a client-side framework, the standard U-prefix taxonomy should apply then.

| ID | Module Name | Source File | Layer |
|---|---|---|---|
| M-001 | auth router | web/routers/auth.py | serving |
| M-002 | dashboard router | web/routers/dashboard.py | serving |
| M-003 | exceptions router | web/routers/exceptions.py | serving |
| M-004 | jobs router | web/routers/jobs.py | serving |
| M-005 | reports router | web/routers/reports.py | serving |
| M-006 | review_queue router | web/routers/review_queue.py | serving |
| M-007 | upload router | web/routers/upload.py | serving |
| M-008 | users router | web/routers/users.py | serving |
| M-009 | web app entry | web/app.py | infra |
| M-010 | web shared deps | web/deps.py | infra |
| M-011 | web query layer | web/queries.py | infra |
| M-012 | web launcher | web/start.py | infra |
| M-013 | background job worker | web/worker.py | pipeline |
| M-014 | document intake pipeline | notebooks/01_document_intake.py | pipeline |
| M-015 | mock ERP CLI entry | notebooks/02_generate_mock_erp.py | pipeline |
| M-016 | matching CLI entry | notebooks/03_run_matching.py | pipeline |
| M-017 | report CLI entry | notebooks/04_generate_report.py | pipeline |
| M-018 | full pipeline orchestrator | scripts/run_full_pipeline.py | pipeline |
| M-019 | lakehouse schema setup | notebooks/00_setup_lakehouse_schema.py | infra |
| M-020 | document understanding engine | src/ai/document_understanding_engine.py | pipeline |
| M-021 | Azure OpenAI client | src/ai/azure_openai_client.py | pipeline |
| M-022 | Claude (Haiku 4.5) client | src/ai/claude_client.py | pipeline |
| M-023 | Claude Sonnet 4.6 client | src/ai/claude_sonnet_client.py | pipeline |
| M-024 | Azure Document Intelligence client | src/ai/document_intelligence_client.py | pipeline |
| M-025 | Gemini client | src/ai/gemini_client.py | pipeline |
| M-026 | Mistral client | src/ai/mistral_client.py | pipeline |
| M-027 | OCR extractor | src/ai/ocr_extractor.py | pipeline |
| M-028 | pdfplumber fallback | src/ai/pdfplumber_fallback.py | pipeline |
| M-029 | explanation service | src/ai/explanation_service.py | pipeline |
| M-030 | AI client contract | src/ai/base_client.py | infra |
| M-031 | AI client factory | src/ai/client_factory.py | infra |
| M-032 | AI audit logger | src/ai/audit_logger.py | infra |
| M-033 | lakehouse connection | src/lakehouse/connection.py | infra |
| M-034 | SQLite migration runner | src/lakehouse/migrations.py | infra |
| M-035 | Azure SQL schema creator | src/lakehouse/azure_sql_migrations.py | infra |
| M-036 | matching engine | src/matching/engine.py | pipeline |
| M-037 | mock ERP generator | src/mock_erp/generator.py | pipeline |
| M-038 | invoice normalization | src/normalization.py | pipeline |
| M-039 | Blob Storage client | src/storage/blob_client.py | infra |
| M-040 | provider-chain smoke test | scripts/test_provider_chain.py | infra |
| M-041 | review-queue cleanup script | check_queue.py | infra |
| M-042 | Azure-SQL-detection probe | check_subprocess.py | infra |
| M-043 | worker simulation (basic) | test_worker_sim.py | infra |
| M-044 | worker simulation (path-exact) | test_worker_sim2.py | infra |

**Module-worthiness note (BCE-009) for M-040 through M-044:** these are not `*.unit.test.ts`-style assertion tests — each makes a real, traceable call into a registered module as its primary mechanism: M-040 instantiates real AI clients via `client_factory.get_ai_client()`; M-041 issues a real `DELETE`/`SELECT` against the live database via `connection.py`; M-042 and M-043/M-044 spawn real subprocesses that exercise `connection.py` and the full pipeline (`scripts/run_full_pipeline.py`) respectively. All five meet the module-worthiness bar and are registered under `infra`, consistent with the reconciliation.ts/resolve_golden_set.ts precedent this heuristic is modeled on. `src/pipeline/` and `src/validation/` contain only empty `__init__.py` files — no module assigned; see Session A0 note.

**`azure_claude_sonnet.json` correction:** Session A0 flagged `config/ai/azure_claude_sonnet.json` as possibly orphaned. Confirmed orphaned during Session A — a repo-wide grep for `azure_claude_sonnet` returns zero references outside the codebase map itself. `client_factory.py`'s `provider_config_paths` only registers `claude_sonnet_extraction.json` under the `claude_sonnet` key. This file is dead configuration, not read by any code path. Recorded as a RISK_REGISTER cleanup candidate, not carried forward as an open question.

**Duplicate sample PDF correction:** Session A0 flagged `sample_data/KSI Noakers 053126.pdf` vs `sample_data/KSI_Noakers_053126.pdf` as a likely duplicate. Confirmed via SHA-256 checksum — both files are byte-identical. The spaced-filename version (mtime 2026-07-22) postdates the underscored original (mtime 2026-07-17) and matches the exact filename `test_worker_sim2.py` uses to mimic the web upload router's filename-preserving save behavior — this is testing residue, not two distinct vendor statements. No code defect; noted for housekeeping only.

---

## Section 1 — Internal Call Table

| Edge | Call Site (file:line) | Sync/Async |
|---|---|---|
| M-009 --[CALLS]--> M-013 | web/app.py:33 (`start_worker()` in `lifespan()`) | S |
| M-009 --[CALLS]--> M-001 | web/app.py:53 (`include_router`) | S |
| M-009 --[CALLS]--> M-002 | web/app.py:54 | S |
| M-009 --[CALLS]--> M-003 | web/app.py:55 | S |
| M-009 --[CALLS]--> M-006 | web/app.py:56 | S |
| M-009 --[CALLS]--> M-007 | web/app.py:57 | S |
| M-009 --[CALLS]--> M-005 | web/app.py:58 | S |
| M-009 --[CALLS]--> M-008 | web/app.py:59 | S |
| M-009 --[CALLS]--> M-004 | web/app.py:60 | S |
| M-009 --[CALLS]--> M-010 | web/app.py:26 (imports `LoginRequired`) | S |
| M-001 --[CALLS]--> M-010 | web/routers/auth.py:16 (`render`) | S |
| M-001 --[CALLS]--> M-011 | web/routers/auth.py:17,29 (`get_user_by_email`) | S |
| M-002 --[CALLS]--> M-010 | web/routers/dashboard.py:12 | S |
| M-002 --[CALLS]--> M-011 | web/routers/dashboard.py:13 (`get_kpis`, `get_recent_runs`, `get_active_jobs`) | S |
| M-003 --[CALLS]--> M-010 | web/routers/exceptions.py:15 | S |
| M-003 --[CALLS]--> M-011 | web/routers/exceptions.py:16 (`get_vendor_summaries`, `resolve_exception`, etc.) | S |
| M-004 --[CALLS]--> M-010 | web/routers/jobs.py:12 | S |
| M-004 --[CALLS]--> M-011 | web/routers/jobs.py:13 (`get_active_jobs`, `get_job_history`) | S |
| M-005 --[CALLS]--> M-010 | web/routers/reports.py:12 | S |
| M-005 --[CALLS]--> M-011 | web/routers/reports.py:13 (`get_all_runs`, `get_statement_report`) | S |
| M-006 --[CALLS]--> M-010 | web/routers/review_queue.py:22 | S |
| M-006 --[CALLS]--> M-011 | web/routers/review_queue.py:23 (`get_review_queue_vendors`, `action_review_item`) | S |
| M-007 --[CALLS]--> M-010 | web/routers/upload.py:18 | S |
| M-007 --[CALLS]--> M-011 | web/routers/upload.py:19,72 (`create_job`) | S |
| M-008 --[CALLS]--> M-010 | web/routers/users.py:13 | S |
| M-008 --[CALLS]--> M-011 | web/routers/users.py:14 (`list_users`, `create_user`, `delete_user_by_email`) | S |
| M-010 --[CALLS]--> M-011 | web/deps.py:33 (`sidebar_context` — `get_open_exceptions_count`, `get_pending_review_count`) | S |
| M-013 --[CALLS]--> M-011 | web/worker.py:42,77,89,104 (`claim_next_pending_job`, `update_job_status`, `get_vendor_name_for_statement`) | S |
| M-013 --[CALLS]--> M-018 | web/worker.py:53 (`subprocess.run(["scripts/run_full_pipeline.py", ...])`) | A (subprocess, polled every 30s) |
| M-018 --[CALLS]--> M-014 | scripts/run_full_pipeline.py:73 (`load_notebook` exec of `01_document_intake.py`, then `run_intake()`) | S |
| M-018 --[CALLS]--> M-037 | scripts/run_full_pipeline.py:95-97 (`generate_mock_erp`, `normalize_erp_to_silver`) | S |
| M-018 --[CALLS]--> M-036 | scripts/run_full_pipeline.py:106 (`run_matching`) | S |
| M-018 --[CALLS]--> M-017 | scripts/run_full_pipeline.py:115 (`load_notebook` exec of `04_generate_report.py`, then `generate_report()`) | S |
| M-014 --[CALLS]--> M-020 | notebooks/01_document_intake.py:55 (`DocumentUnderstandingEngine`, `extract_pdf_text`) | S |
| M-014 --[CALLS]--> M-033 | notebooks/01_document_intake.py:56 (`execute_sql`, `execute_query`) | S |
| M-014 --[CALLS]--> M-038 | notebooks/01_document_intake.py:57 (`normalize_invoice_number`) | S |
| M-014 --[CALLS]--> M-039 | notebooks/01_document_intake.py:58,530 (`BlobStorageClient().upload_pdf()`) — **confirmed wired at Step 8 of `run_intake()`; corrects Session A0's provisional note that this looked unwired** | S |
| M-015 --[CALLS]--> M-037 | notebooks/02_generate_mock_erp.py:37 | S |
| M-016 --[CALLS]--> M-036 | notebooks/03_run_matching.py:32 | S |
| M-016 --[CALLS]--> M-033 | notebooks/03_run_matching.py:33 | S |
| M-017 --[CALLS]--> M-033 | notebooks/04_generate_report.py:34 | S |
| M-017 --[CALLS]--> M-029 | notebooks/04_generate_report.py:35,106-107 (`ExplanationService(...).explain_all_open_exceptions()`, only under `--explain`) | S |
| M-020 --[CALLS]--> M-031 | src/ai/document_understanding_engine.py:37,188 (`client_factory.get_ai_client()`, no provider arg) | S |
| M-020 --[CALLS]--> M-028 | src/ai/document_understanding_engine.py:38,226 (`extract_with_pdfplumber`) | S |
| M-020 --[CALLS]--> M-032 | src/ai/document_understanding_engine.py:39,195 (`log_ai_call`) | S |
| M-031 --[CALLS]--> M-022 | src/ai/client_factory.py:39 (conditional: `provider_name == "claude"`) | S |
| M-031 --[CALLS]--> M-026 | src/ai/client_factory.py:48 (conditional: `"mistral"`) | S |
| M-031 --[CALLS]--> M-023 | src/ai/client_factory.py:56 (conditional: `"claude_sonnet"` — **this is the branch taken by default given `active_provider.json`'s `provider_chain[0]`**) | S |
| M-031 --[CALLS]--> M-025 | src/ai/client_factory.py:67 (conditional: `"gemini"`) | S |
| M-031 --[CALLS]--> M-021 | src/ai/client_factory.py:76 (conditional: `"azure_gpt5_mini"/"azure_gpt5_nano"/"azure_gpt5_1"`) | S |
| M-031 --[CALLS]--> M-024 | src/ai/client_factory.py:85 (conditional: `"azure_doc_intel"`) | S |
| M-024 --[CALLS]--> M-028 | src/ai/document_intelligence_client.py:39-44 (imports `_extract_header_info`, `_extract_invoice_row`, `_find_header_row`, `_map_columns`) | S |
| M-028 --[CALLS]--> M-027 | src/ai/pdfplumber_fallback.py:49 (`is_ocr_available`, `ocr_page`) | S |
| M-032 --[CALLS]--> M-033 | src/ai/audit_logger.py:14 (`execute_sql`) | S |
| M-029 --[CALLS]--> M-031 | src/ai/explanation_service.py:26,148 (`client_factory.get_ai_client("claude")` — hardcoded, independent of `provider_chain`) | S |
| M-029 --[CALLS]--> M-032 | src/ai/explanation_service.py:27,162 (`log_ai_call`) | S |
| M-029 --[CALLS]--> M-033 | src/ai/explanation_service.py:28 (`execute_sql`, `execute_query`) | S |
| M-037 --[CALLS]--> M-033 | src/mock_erp/generator.py:24 (`execute_sql`, `execute_query`) | S |
| M-037 --[CALLS]--> M-038 | src/mock_erp/generator.py:223 (`normalize_invoice_number`, inside `normalize_erp_to_silver`) | S |
| M-036 --[CALLS]--> M-033 | src/matching/engine.py:29 (`execute_sql`, `execute_query`) | S |
| M-019 --[CALLS]--> M-033 | notebooks/00_setup_lakehouse_schema.py (obtains connection before running migrations) | S |
| M-019 --[CALLS]--> M-034 | notebooks/00_setup_lakehouse_schema.py (`apply_pending_migrations`) | S |
| M-035 --[CALLS]--> M-033 | src/lakehouse/azure_sql_migrations.py:32 (`get_connection`) | S |
| M-040 --[CALLS]--> M-031 | scripts/test_provider_chain.py:6 (`get_ai_client`, `get_provider_chain`) | S |
| M-041 --[CALLS]--> M-033 | check_queue.py:5,8,12 (`execute_sql`, `execute_query`) | S |
| M-042 --[CALLS]--> M-033 | check_subprocess.py:6 (subprocess exercises `_using_azure_sql()`) | A (subprocess) |
| M-043 --[CALLS]--> M-018 | test_worker_sim.py:8 (subprocess) | A (subprocess) |
| M-044 --[CALLS]--> M-018 | test_worker_sim2.py:13 (subprocess, mirrors web/worker.py's exact path construction) | A (subprocess) |

## Section 2 — Startup Sequence

**Web application (`uvicorn web.app:app`, via `web/start.py` locally or `startup.sh` in Azure App Service):**

| Step | Module (M-NNN) | Action | Failure Mode |
|---|---|---|---|
| 1 | M-009 | Load `.env`, construct FastAPI app, add `SessionMiddleware` (falls back to a hardcoded dev secret if `WEB_SESSION_SECRET` unset) | NON-FATAL (dev secret fallback is a security smell, not a crash — see RISK_REGISTER) |
| 2 | M-009 | Mount `/static`, register `LoginRequired` exception handler | STARTUP-FATAL if `web/static/` directory is missing |
| 3 | M-009 → M-001..M-008 | Register all 8 routers | STARTUP-FATAL on any router import error |
| 4 | M-009 → M-013 | `lifespan()` calls `start_worker()` — spawns the daemon polling thread | NON-FATAL — `start_worker()` itself has no failure path observed; the thread body catches all exceptions internally once running |

**Database schema bring-up (separate, manual operational step — not part of the web app's own startup):**

| Step | Module (M-NNN) | Action | Failure Mode |
|---|---|---|---|
| 1 | M-019 | Run `notebooks/00_setup_lakehouse_schema.py` | STARTUP-FATAL for that script's own run — raises `MigrationError` on first failing migration, does not proceed |
| 2 | M-019 → M-034 (SQLite) or manual M-035 run (Azure SQL) | Apply all pending numbered migrations / create Azure SQL schema | Same as above — migration failure rolls back and halts |

## Section 3 — Async Boundaries

| Producer (M-NNN) | Consumer (M-NNN) | Mechanism | Failure behaviour |
|---|---|---|---|
| M-007 (upload router, HTTP request) | M-013 (background worker thread) | `jobs` table row (status PENDING), polled every 30s via `claim_next_pending_job()` | If the worker thread ever dies unexpectedly (not observed as reachable — every exception in `_worker_loop` is caught and logged), no supervisor restarts it and no liveness check exists; jobs would silently stop being claimed. **No stale-job requeue exists** — see Layer Boundary Map note below, a documented-but-unbuilt gap. |
| M-013 (worker thread) | M-018 (`scripts/run_full_pipeline.py`, subprocess) | `subprocess.run(..., timeout=1800)` | Non-zero exit or no `"Statement ID:"` match in output → job marked FAILED with the last 4000 chars of combined stdout/stderr. A hung subprocess is killed at the 30-minute cap. |
| M-004 (`/jobs` JSON endpoint) | Browser (`web/static/app.js`, not a Python module) | HTTP polling, client-initiated | Not a server-side async boundary between M-NNN modules — included here for completeness of the async picture, not as a CALLS edge. |

---

## Section 4 — Layer Boundary Reconciliation (A01 input)

See discovery/TOPOLOGY.md Section A01 for the assembled Layer Boundary Map. Key findings from source reads that inform it:

1. **VISION_PROMPT is dead code for the currently active provider — confirmed to be a real extraction-quality risk, not cosmetic (engineer-requested follow-up, 2026-07-23).** `document_understanding_engine.py` builds a detailed, carefully-tuned `VISION_PROMPT` (column-mapping semantics, mixed-prefix handling, confidence calibration) and passes it to `primary_client.generate_with_file(pdf_path, VISION_PROMPT)`. The actual active primary, `ClaudeSonnetClient` (M-023), ignores the passed `prompt` parameter entirely and always sends its own much shorter, self-contained `EXTRACTION_PROMPT` instead (same pattern for `GeminiClient`/`MistralClient` — only `ClaudeClient` (Haiku) and `AzureOpenAIClient` honor the passed prompt). Side-by-side comparison found concrete regressions, not just a shorter prompt:
   - **Confidence is fabricated, not measured.** VISION_PROMPT asks the model for a genuine per-row `line_confidence` with explicit calibration rules, which is what routes a doubtful row to human review via the 0.60 threshold (RULE-10's "never silently succeed" principle). EXTRACTION_PROMPT never asks for confidence at all, and `claude_sonnet_client.py:521` hardcodes `"line_confidence": ROW_CONFIDENCE` (`ROW_CONFIDENCE = 0.75`, a constant) on every row regardless of actual legibility. Since 0.75 > 0.60, every row Claude Sonnet extracts always passes validation — including a row it was genuinely unsure about. This defeats the safety net for the two specific failure modes VISION_PROMPT's "MIXED PREFIX PATTERNS" and "UNREADABLE PAGES" clauses were written to catch (both real, previously-observed bugs per the Implementation Context history) — EXTRACTION_PROMPT has no equivalent instructions, and there is no confidence field for the model to express doubt in even if it wanted to. `page_number` is also hardcoded to `1` for every row (single whole-document call, no per-page tracking), so page-level unreadability has no signal path at all on this provider.
   - **No totals-row exclusion.** VISION_PROMPT explicitly tells the model to capture the grand total separately, never as an invoice line. EXTRACTION_PROMPT has no such instruction, and — unlike `pdfplumber_fallback.py`'s explicit `"total"/"balance"/"subtotal"` keyword skip in `_extract_invoice_row` — `claude_sonnet_client.py` has no equivalent filter. A summary/total row with a number-like value and an amount could be ingested as a fake invoice.

   **Cross-checked against `gemini_client.py` and `mistral_client.py` (engineer-requested, 2026-07-23):** grepped both files for `total`/`balance`/`subtotal` and inspected every hit's actual role. **Filter absent in both — confirmed definitively, not just by analogy to Sonnet:**
   - `gemini_client.py`: 4 matches, all incidental. `OUTSTANDING_KEYWORDS` (line 124) includes `"balance"` as a *column-header* keyword for mapping a header like "Balance" to the `outstanding_amount` field — a mapping concern, not a row-content filter. The other three matches are a token-usage log line (`usage.total_token_count`) and two occurrences of a computed `statement_total = sum(...)` used only to populate `statement_total_as_printed` in the output schema — an aggregate the code calculates itself, not a detector for a totals row printed in the source PDF. `_rows_to_invoices()` converts every dict-shaped row into an invoice unconditionally (its only skip condition is `if not isinstance(row, dict): continue`) — no keyword check, no exclusion of any kind.
   - `mistral_client.py`: 6 matches, all incidental. Two are prompt text (`"Balance, Outstanding, Net etc"` — a column-mapping hint for the model, not a row filter); the rest are an unrelated `total_attempts` retry counter and the same self-computed `statement_total = sum(...)` pattern as Gemini. The row loop in `generate_with_file()` appends every row via `self._row_to_invoice(row, page_num, row_num)` with no conditional skip at all — not even a type check.
   - **Verdict for RISK_REGISTER: all three fabricating LLM clients (ClaudeSonnetClient, GeminiClient, MistralClient) share the identical gap — zero totals/summary-row exclusion, at both the prompt level and the code level.** Only `pdfplumber_fallback.py` (and, by extension, `document_intelligence_client.py`, which reuses `pdfplumber_fallback`'s `_extract_invoice_row` and therefore inherits its `"total"/"balance"/"subtotal"` skip) has this protection. This is a systemic gap across the three newer whole-document-JSON clients, not a Sonnet-specific defect — same shape as the confidence-fabrication finding above.
   - **Column mapping is narrower, not absent.** `_map_columns`'s keyword lists cover common cases, with a value-based fallback — but only for `invoice_number` and `outstanding_amount`. An unfamiliar header for `ro_number`/`po_number`/`work_order_number`/`description`/`shop`/`due_date` gets no fallback and returns `null`, where VISION_PROMPT told the model to reason semantically about unfamiliar columns for every field. The one instruction that did carry over intact: preferring the invoice-number column without account-code prefixes.
   **[STAGE-2-DIVERGENCE — 2026-07-23]:** upgraded from an initial "possibly cosmetic" read to a confirmed RISK_REGISTER candidate (recommend P1 or P2, not P3) — the currently-active provider silently defeats the confidence-gated human-review mechanism the rest of the system is designed around. Flagged as a MODULE_CONTRACTS.md Known Fragility candidate for Session B/C/G, and as a priority RISK_REGISTER item for Session E.

   **Live-data confirmation (engineer-requested, 2026-07-23):** queried `lakehouse/reconciliation.db` (local SQLite dev/test — `AZURE_SQL_SERVER` is configured in `.env` but was not checked; a separate Azure SQL check may be warranted). Four statements have been processed via `claude_sonnet` since it became active (`STMT-5596CFFF`, `STMT-0E8900BE`, `STMT-63ED4C76`, `STMT-6C0D52DA`); only `STMT-6C0D52DA` (asTech/ASTCollex0526.pdf, 202 invoices) has reached Gold. All 202 `gold_matched_invoices` rows for it trace back to Bronze rows with `extraction_confidence` exactly `0.75` — 100%. Across all 1,510 Bronze rows ever written under `claude_sonnet/claude-sonnet-4-6` (all 4 statements), every single one is exactly `0.75` — zero variance, confirming the hardcoded constant with production/test data, not just static analysis. That one reconciled statement came back 100% matched with zero exceptions — not evidence the gap is safe, since no signal ever existed to have caught a genuinely-uncertain-but-wrong row in the first place.

   **Cross-provider audit extending this finding beyond ClaudeSonnetClient (engineer-requested, 2026-07-23):** checked all six registered provider clients for whether `line_confidence` is genuinely model-elicited or fabricated. Confirmed via grep + call trace (`_try_parse_json`/`_row_to_invoice` paths), not inference:
   - **Genuine, model-elicited confidence (honors `VISION_PROMPT`, no hardcoding):** `ClaudeClient` (Haiku 4.5, IP-002) and `AzureOpenAIClient` (gpt-5-mini/nano/5.1, IP-003). Both call `_try_parse_json()` → `json.loads(text)` and return the model's parsed JSON unmodified — no `ROW_CONFIDENCE` constant, no per-row line_confidence assignment anywhere in either file. AzureOpenAIClient only overwrites `page_number` per page; `line_confidence` passes through untouched.
   - **Fabricated — hardcoded constant, model never asked for confidence at all:** `ClaudeSonnetClient` (IP-001, active primary), `GeminiClient` (IP-005), `MistralClient` (IP-006) — all three define `ROW_CONFIDENCE = 0.75` and assign it to every row; all three send an `EXTRACTION_PROMPT`-style prompt that never requests a confidence field from the model.
   - **Fabricated for a structurally different, more defensible reason:** `DocumentIntelligenceClient` (IP-004, a prior primary) — also `ROW_CONFIDENCE = 0.75` hardcoded, but `prebuilt-layout` is pure table-geometry extraction, not an LLM, so there is no model self-assessment to elicit in the first place (the file's own comment acknowledges this is "not a benchmarked/tuned value"). The downstream effect is identical (every row clears the 0.60 threshold regardless of table-detection ambiguity), but the "fabrication" is an assigned default rather than a discarded real signal.
   - **Not fabricated, but coarse:** `pdfplumber_fallback.py` (always-available last resort, not a registered AI provider) genuinely varies confidence by extraction path — 0.65 for real geometry-based rows vs. 0.50 for OCR-derived rows, the latter deliberately below threshold by design (RULE-10). This is the one extraction path where the confidence gate does real work.
   - **Severity implication:** 4 of 6 registered providers fabricate confidence (Sonnet, Gemini, Mistral, Doc Intelligence); only 2 (Haiku-Claude, Azure OpenAI gpt-5 family) have a genuine signal. Three of the four fabricating clients have each held the "active primary" role at different points in this project's history (Doc Intelligence, briefly Gemini per its own docstring, now Sonnet) — meaning the confidence gate has likely been a no-op for most of this system's operating history on the primary extraction path, not a defect specific to the current provider. Recommend RISK_REGISTER state this as a single systemic finding across providers, not a per-client bug list.

   **Azure SQL confirmation, aggregate-only (engineer-requested, 2026-07-23):** the same aggregate-only check (GROUP BY extraction_model, COUNT, MIN/MAX confidence — no vendor/invoice/statement content queried) was run against the shared Azure SQL instance (`AZURE_SQL_SERVER` configured in `.env`). Findings are materially larger than the local dev database: **2,120 `gold_matched_invoices` rows and 4 `gold_exceptions` rows** (2,124 total Gold-layer rows) trace back to `claude_sonnet` Bronze rows — **100% exactly `0.75` confidence**, across **13 distinct statements** (of 23 total statements with any Gold matches in that database — more than half). Whether this Azure SQL instance holds real production traffic or shared dev/test activity was not conclusively determined (no vendor/invoice/statement content was queried, per instruction) — aggregate signals lean dev/test: a `fake`/`fake-model` value appears in `document_intake_log.extraction_method` (not a real registered provider — a test-fixture artifact), only 2 users exist and were created 10 minutes apart on the same day, and total volume (15 intake-log entries, 10 jobs, all COMPLETED) is modest for a claimed 79-shop operation. Engineer should confirm definitively before this number is finalized in RISK_REGISTER.md, but treat 2,124 affected Gold rows as the working figure pending that confirmation.

2. **The AI provider chain contradiction is now confirmed at the call-site level, not just the config file.** `document_understanding_engine.py:188` calls `client_factory.get_ai_client()` with no provider argument, which resolves to `provider_chain[0]` from `active_provider.json` — `"claude_sonnet"` → `ClaudeSonnetClient` (M-023). This is the actual, executing primary. **[STAGE-2-DIVERGENCE — 2026-07-23]:** RULES.md RULE-04 and docs/VIVE_Implementation_Context.md Section 3 both state Azure Document Intelligence is primary; `gemini_client.py`'s own docstring and `client_factory.py`'s own inline comments both state Gemini is primary; `claude_sonnet_client.py`'s own docstring states it is *not* in the active chain; `ocr_extractor.py`, `document_understanding_engine.py`'s own docstring, and `notebooks/04_generate_report.py`'s docstring all state Azure OpenAI gpt-5-mini is primary. All are stale relative to the code that actually executes. Recommended resolution: engineer confirms Claude Sonnet 4.6 is intentionally the current primary, then a single documentation/comment sweep updates all six stale locations in one pass (tracked as a RISK_REGISTER item, not re-litigated file-by-file).

3. **`web/routers/upload.py` and `web/worker.py` never call `BlobStorageClient` directly** — the actual call happens one layer down, inside `notebooks/01_document_intake.py`'s `run_intake()` (Step 8), which `scripts/run_full_pipeline.py` invokes for every job the worker dispatches. So Blob Storage archival **is** live end-to-end for every web-uploaded PDF, contradicting docs/VIVE_Implementation_Context.md's "Not wired into the pipeline yet" (dated 2026-07-15). **[STAGE-2-DIVERGENCE — 2026-07-23]:** corrects Session A0's own provisional note, which had flagged this as "worth confirming" based only on not finding the call in the web layer — Session A's full-pipeline trace finds it one hop further down.

4. **No stale-job requeue logic exists**, despite docs/VIVE_Implementation_Context.md Phase 3 explicitly specifying it ("any job stuck in PROCESSING past a timeout... gets automatically re-queued"). `web/queries.py`'s job-related functions (`create_job`, `claim_next_pending_job`, `update_job_status`, `get_active_jobs`, `get_job_history`) contain no timeout-based requeue query. A job that reaches PROCESSING and then never completes (e.g. a killed worker process, though the 30-minute subprocess timeout mitigates most cases) would block `claim_next_pending_job()`'s `NOT EXISTS (... status = 'PROCESSING')` guard forever, since nothing else can claim while one row is stuck PROCESSING. **This is a genuine, code-confirmed gap**, not just a doc staleness — recommend a RISK_REGISTER entry (P2: no immediate incident, but a real single point of stall for the whole queue).
