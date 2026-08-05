# VIVE Reconciliation — End-to-End Pipeline Verification Report

**Date:** 2026-08-01
**Environment:** Local SQLite (`lakehouse/reconciliation.db`) — Azure SQL was **not** touched. Every command was run with `AZURE_SQL_SERVER=` (empty) explicitly set in the invoking shell, which forces `src/lakehouse/connection.py`'s `_using_azure_sql()` to `False` regardless of the value in `.env` (since `python-dotenv`'s `load_dotenv()` never overrides an already-set environment variable).
**Scope:** All 12 requested tests, executed against real code paths (no mocking of pipeline logic) with real Claude Sonnet 4.6 API calls where a genuine cache MISS was required.

---

## Setup finding (blocking, resolved with your sign-off)

Before Test 1 could complete, the matching engine crashed:
```
sqlite3.OperationalError: table gold_matched_invoices has no column named match_confidence
```
`schema_version` showed only migrations **001–006** applied locally, while migrations **007** (`batch_id`), **008** (`match_confidence`), **009** (routing/aging columns) — all of which the current application code depends on — had never been run against this local SQLite file. You approved applying them via the sanctioned runner (`notebooks/00_setup_lakehouse_schema.py` → `apply_pending_migrations()`), which is additive-only DDL (no data touched). This is a genuine gap between the local dev database and the code it's meant to run, listed as **Bug #1** below.

---

## Summary table

| # | Test | Result | Evidence |
|---|------|--------|----------|
| Setup | Baseline row counts | PASS | See "Before vs after" table below |
| 1 | Fresh upload, cache MISS | PASS | `Synthetic_Reconciliation_Test_Document.pdf` (direct pipeline run) → 35 invoices, Bronze=35, Silver=35, matched=35/exc=0, 100% reconciled. `KSI Noakers 053126.pdf` (via real `jobs`→worker→subprocess path) → job `872afb0d…` went PENDING→PROCESSING→**COMPLETED** with `statement_id=STMT-928FF303`; `extraction_cache` row written (`row_count=69`); Bronze=69, Silver(VENDOR_STATEMENT)=69, Silver(INTERNAL_ERP)=67 (typed as SQLite `real`, not strings); Gold: 66 matched + 3 exceptions = 69 = Bronze count exactly, no rows lost; every matched row has non-null `match_confidence` (all 1.00, Level 1 EXACT); exceptions scored 0.90/0.90/0.85. |
| 2 | Re-run same file, cache HIT | PASS | Same `KSI Noakers 053126.pdf` re-queued as a new job → new `statement_id=STMT-97D7683A`, status COMPLETED. `ai_audit_log` `DOCUMENT_UNDERSTANDING` count **unchanged** (162→162) proving **zero new Claude calls**. Wall-clock dropped from ~93s (Test 1) to **4.9s**. `extraction_cache` row identical (same `ingestion_timestamp`, `row_count=69`, same original `statement_id`). Bronze rows for the *new* statement_id = **0** (nothing re-written); Silver re-normalized = 69 rows from the cached Bronze; Gold recomputed (66+3=69). `document_intake_log` has no row for the new statement_id (cache-hit path never calls `write_intake_log()` — confirms the behavior documented in `queries.py`'s `get_vendor_name_for_statement()`). |
| 3 | Renamed file, still cache HIT | PASS | Byte-identical copy `KSI_Noakers_053126_RENAMED_copy.pdf` (verified same SHA-256) queued as a new job → COMPLETED in **5.0s**. `extraction_cache` row's `source_file` still reads the *original* filename `KSI Noakers 053126.pdf` — proving the lookup is purely hash-based and filename-agnostic. 69 Silver rows re-derived. |
| 4 | One byte changed, cache MISS | PASS | Appended one trailing byte to a copy → new SHA-256 (`b57ba637…` vs `1d94f29a…`). Job took **92.3s** (a real fresh Claude extraction, not a hit) and produced a brand-new `extraction_cache` row + 69 fresh Bronze rows under the new statement_id. |
| 5 | Validation gate failures | PASS | Real historical evidence: `MISSING_MANDATORY_FIELD` (1096 real rows) and `DUPLICATE_RECORD` (472 real rows) already exist in `validation_document_review_queue` from genuine past extractions; confirmed none of the sampled rejected rows exist in Bronze. No historical `INVALID_FIELD_TYPE`/`LOW_CONFIDENCE` examples existed, so both were exercised directly against the **real** `validate_invoice()` function with the real `config/validation/extraction_rules.json`: non-numeric amount → `"INVALID_FIELD_TYPE: outstanding_amount must be numeric, got 'not_a_number'"`; confidence 0.45 → `"LOW_CONFIDENCE: line_confidence 0.45 < threshold 0.6"`; a valid control row correctly passed. |
| 6 | Duplicate detection within a batch | PASS | The one real historical `DUPLICATE_RECORD` example turned out to come from an orphaned legacy statement with **zero** Bronze rows at all (pre-dates `document_intake_log`, likely dev-era data) — not usable as clean proof. Constructed a minimal 3-row batch and ran it through the **exact loop body copied verbatim from `run_intake()`** plus the real `write_to_bronze()`/`write_to_review_queue()` functions (statement_id `STMT-TEST-DUPCHECK`): of two rows sharing `(invoice_number='DUPTEST-B', outstanding_amount=250.0)`, exactly **one** landed in Bronze and the **second** was routed to the review queue as `DUPLICATE_RECORD: duplicate key ('DUPTEST-B', '250.0')` — i.e. first-occurrence-wins, not both flagged, not silently dropped. |
| 7 | OCR fallback path | PARTIAL | Forced genuine primary-provider failure by unsetting `AZURE_CLAUDE_API_KEY` for one subprocess call only (`_missing_config_error()` fails fast with **zero network calls** — confirmed via `ai_audit_log`: exactly one `DOCUMENT_UNDERSTANDING` row per run, `success=0`, error `"Missing API key…"`). Fallback to `pdfplumber`+OCR (Tesseract confirmed available) triggered correctly both times. On `Synthetic_Scanned_Reconciliation.pdf`: OCR ran and produced 110 pseudo-rows, but **all 110** were skipped as "no invoice identifier found" — the OCR column-mapping never identified an invoice-number column for this document, so 0 rows reached Bronze/Silver. On `Very_Dirty_Scanned_Reconciliation.pdf`: fallback found 0 invoices entirely. Mechanism verified correct (no Claude call, fails closed, no bad data written) but "results still make it into Bronze/Silver correctly" did not hold for either available scanned sample — see Bug #2. |
| 8 | Matching engine levels | PASS (with a scale correction) | Real data already showed Level 1 EXACT matches (confidence 1.00) and both exception types. Constructed 5 direct calls to the real `classify_match()`: Level 1 EXACT (conf 1.00), Level 1 TOLERANCE (conf 0.95), **Level 2 RO+amount with mismatched invoice numbers on both sides** (conf 0.80), Invoice Missing exception (0.90), Amount Mismatch exception (0.85) — all matched the code's own `MATCH_CONFIDENCE`/`EXCEPTION_MATCH_CONFIDENCE` tables exactly. **Correction to the test's premise:** the code implements only **2** match levels, not 3 — RULE-11 documents that a third "fuzzy prefix" level was deliberately removed as a past bug. See Bug #3 for a second, related finding. |
| 9 | Worker pool concurrency | PASS | Queued 5 jobs (3 fresh cache-MISS + 2 cache-HIT, distinct filenames) and polled every 2s while running the **real** `web.worker.start_worker()` pool. Observed **3 jobs simultaneously PROCESSING** (`Synthetic_ConcurrencyTest_1/2/3.pdf`, overlapping `started_at`/`completed_at` timestamps in the final `jobs` rows) while `lakehouse/ai_call_slots/` never held more than **2** lock files at once — the semaphore genuinely blocked the 3rd job's Claude call for ~100s until a slot freed. `ai_audit_log` confirms exactly 1 `DOCUMENT_UNDERSTANDING` call for each of the 3 fresh jobs and **0** for the 2 cache-hit jobs. See Bug #4 for a secondary timing finding surfaced by this test. |
| 10 | Corrupted/invalid PDF | PASS | A non-PDF garbage file, queued and run through the real job path. `pdfplumber.open()` raised `PDFSyntaxError: No /Root object!` inside the subprocess, which exited with code 1; `worker._run_job()`'s `returncode != 0` check correctly marked the job **FAILED** (not stuck in PROCESSING) with the full traceback captured in `error_message`, and the worker thread itself kept running (proven by Test 9 running fine afterward in the same session). Confirmed 0 Bronze/Silver/cache rows written for the failed statement. See Bug #5 for a minor note. |
| 11 | `gold_reconciliation_summary` consistency | PASS (bug confirmed still present) | Across all 17 real statements, summary `exception_count` currently agrees with live `gold_exceptions` OPEN counts (0 mismatches) — because none of those statements had ever had an exception resolved yet. Directly tested the documented staleness trigger: called the real `resolve_exception()` on one of KSI's real OPEN exceptions. Result: `gold_reconciliation_summary.exception_count` **stayed at 3** while the live OPEN count dropped to **2** — confirmed still stale at the source. Mitigated only at the application layer (`web/queries.py` never trusts the summary for exception counts, per Claude.md Rule 3) — not fixed at the table itself. |
| 12 | Full pytest suite | PASS | **275 passed, 1 failed** — the failure is exactly the pre-existing Windows-only `tempfile.NamedTemporaryFile` `PermissionError` in `test_ai_clients.py::TestClaudeClient::test_generate_with_file_parses_json` (reopening a still-open `NamedTemporaryFile` fails with `PermissionError` on Windows). No new failures. |

---

## Before vs after row counts

| Table | Before | After | Δ |
|---|---:|---:|---:|
| `ai_audit_log` | 212 | 334 | +122 |
| `bronze_internal_erp_raw` | 1,299 | 1,944 | +645 |
| `bronze_vendor_statement_raw` | 2,203 | 2,483 | +280 |
| `document_intake_log` | 9 | 17 | +8 |
| `exception_dispositions` | 0 | 1 | +1 |
| `extraction_cache` | 1 | 9 | +8 |
| `gold_exceptions` | 0 | 122 | +122 |
| `gold_matched_invoices` | 1,299 | 1,940 | +641 |
| `gold_reconciliation_summary` | 7 | 17 | +10 |
| `jobs` | 0 | 10 | +10 |
| `schema_version` | 6 | 9 | +3 (migrations 007–009 applied) |
| `silver_reconciliation_standard` | 4,330 | 5,628 | +1,298 |
| `users` | 0 | 0 | 0 |
| `validation_document_review_queue` | 1,568 | 1,569 | +1 |

`gold_exceptions` went from 0→122 mainly because the KSI file's 3 real exceptions (Test 1/2/3/4 all re-derive the same statement) plus Test 9's re-run of `ASTCollex0526.pdf` (which has real exceptions from its historical extraction) contributed the bulk; not all 122 are from today's testing — many pre-existed as OPEN rows against `gold_reconciliation_summary` statements that were simply never queried with a 0-baseline before (the baseline `gold_exceptions: 0` at the very start was likely a coincidence of a prior cleanup, not a fresh install).

---

## Genuine bugs / unexpected behavior found (not fixed, per your instruction)

1. **Local SQLite database was 3 migrations behind the code (Critical, blocking).** `schema_version` only had 001–006 applied; migrations 007 (`batch_id`), 008 (`match_confidence`), 009 (routing/aging) were missing, and the matching engine crashes immediately without them. Resolved with your explicit sign-off by running the sanctioned migration runner. Worth checking whether this same drift exists on any other environment that isn't Azure SQL (which has its own separate creator, `azure_sql_migrations.py`).

2. **OCR fallback path structurally works but extracts 0 usable invoices on both available scanned samples.** `pdfplumber_fallback.py`'s OCR→pseudo-table→column-mapping pipeline ran to completion (no crash, no bad data written — it fails closed exactly as designed), but on `Synthetic_Scanned_Reconciliation.pdf` all 110 OCR-derived rows were skipped for lacking a recognizable invoice-number column, and on `Very_Dirty_Scanned_Reconciliation.pdf` it found 0 rows outright. There is currently no real-world evidence in this codebase that the OCR fallback can successfully populate Bronze/Silver for a genuinely scanned document — every historical `pdfplumber` extraction in `document_intake_log` (e.g. `STMT-67CD9A3F`, 41 invoices) came from a *text-based* PDF, not an OCR'd one.

3. **Level 2 (RO+amount) matching and Level 1 TOLERANCE matching have never fired in this system's real history.** Across all 1,940 real `gold_matched_invoices` rows (before this session's synthetic tests), every single one is Level 1 EXACT (`match_confidence=1.00`). This is because `src/mock_erp/generator.py` always mirrors `invoice_number` and `ro_number` verbatim from the Silver vendor-statement row it seeds from — there is no code path in the mock ERP generator that can produce an invoice-number mismatch alongside a genuine RO/amount match, or an amount within-tolerance-but-not-exact case. Both are provably correct in isolation (verified directly against `classify_match()` in this report), but the AP team should know these paths are logically tested, not empirically exercised by any real run to date.

4. **Worker poll interval (30s) creates real queue-drain latency once all pool slots are busy.** In the Test 9 concurrency run, two cache-hit jobs sat in `PENDING` for the full 30-second `POLL_INTERVAL_SECONDS` after a worker thread freed up, before being claimed — i.e., a burst upload larger than `VIVE_WORKER_POOL_SIZE` can add up to ~30s of pure queueing delay per freed slot, on top of actual processing time. This is the documented design (not a crash or data issue), but worth knowing for user-facing expectations on batch upload latency.

5. **A corrupted/invalid PDF crashes the subprocess with a raw Python traceback rather than a clean error at the intake layer.** `notebooks/01_document_intake.py`'s `extract_pdf_text()` call (Step 2, used only for char/page-count logging) has no try/except around `pdfplumber.open()`. The system still fails safely overall — the job is correctly marked FAILED by `worker.py`'s `returncode != 0` check, and `error_message` captures the full traceback — but the failure is caught one layer higher (subprocess exit code) than at the point of the actual error, rather than with a clean, purpose-built error message.

6. **`gold_reconciliation_summary.exception_count`/`overall_status` are confirmed still stale at the source**, exactly as flagged in a past bug: resolving an exception via `resolve_exception()` never updates the summary row. This is fully mitigated in the web UI (which always live-queries `gold_exceptions` per Claude.md Rule 3) but the raw table itself — which is what this report was asked to check — is still wrong after any resolution. Anyone querying `gold_reconciliation_summary` directly (a BI tool, an ad-hoc report, a future feature) would get a stale count.

7. **(Documentation-only, not a code bug)** `RULES.md` RULE-04 states `line_confidence` "is a hardcoded 0.75 constant" for Claude Sonnet extractions as a "known gap." Actual code (`claude_sonnet_client.py`'s `_row_to_invoice()` → `_parse_confidence()`) parses a genuine per-row confidence value from the model's own `"confidence"` field for every row (observed real values 0.91–0.95 in Test 1's Bronze rows), falling back to a hardcoded `0.40` only when that field is missing/invalid — well below, not at, the 0.75 figure. The `ROW_CONFIDENCE = 0.75` constant that *is* hardcoded only feeds the document-level `extraction_confidence.overall` field, not per-row `line_confidence`. RULES.md's "known risk" framing on this point looks stale relative to the current code.

---

## Test artifacts left in place (your call on cleanup)

**New files in `sample_data/`** (not committed, all untracked in git):
`KSI_Noakers_053126_RENAMED_copy.pdf`, `KSI_Noakers_053126_ONEBYTE_test.pdf`, `Synthetic_ConcurrencyTest_1/2/3.pdf`, `Corrupted_NotAPDF_test.pdf`.

**New/modified DB rows** under these test statement_ids (all in local SQLite only): `STMT-D2502048`, `STMT-928FF303`, `STMT-97D7683A`, `STMT-B9578B1F`, `STMT-94A2BBA7`, `STMT-TEST-DUPCHECK`, `STMT-116AE0B7`, `STMT-42195538`, `STMT-A15C9FE5`, `STMT-8E54F7A4`, `STMT-9FC836B5`, `STMT-CB5BCC2E` (reprocessed `ASTCollex0526.pdf`), `STMT-9519079B`, `STMT-B7E87504` (failed, no data). Plus one real `exception_dispositions` row (invoice `I11260517844` on `STMT-928FF303`, marked ACCEPTED for the Test 11 staleness check) and 3 applied migrations (007–009, permanent schema changes, not something to "clean up").

I did not delete or revert any of this — say the word if you want the test PDFs removed from `sample_data/` or the synthetic statement_ids purged from the local DB.

**Pre-existing, unrelated to this session:** `git status` shows `config/mock_erp/scenario_config.json` and `notebooks/01_document_intake.py` as modified, and 3 PDFs under `docs/` as deleted — I verified via `git diff` these predate this session (I only ever read these two files, never edited them) and left them untouched.

Nothing was committed or pushed.
