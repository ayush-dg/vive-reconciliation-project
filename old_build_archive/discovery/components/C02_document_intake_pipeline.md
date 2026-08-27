## C02 — Document Intake Pipeline
ID: M-017
Layer: pipeline
Source file: `notebooks/01_document_intake.py`

**Module** — Document Intake Pipeline
**ID** — M-017
**Layer** — pipeline
**Primary Responsibility** — The main intake pipeline: cache check → AI extraction → validation → Bronze write → Silver normalization → intake log → Blob archival → cache update, for one PDF.

**Inputs** — `pdf_path` (file), optional `statement_id`/`statement_period` overrides (CLI args or direct call params).

**Outputs** — Rows in `bronze_vendor_statement_raw`, `silver_reconciliation_standard` (VENDOR_STATEMENT), `document_intake_log`, `extraction_cache`, `ai_audit_log`, `validation_document_review_queue`, `gold_exceptions` (EXTRACTION_INCOMPLETE only); a PDF uploaded to Blob Storage.

**Public Interface**
- `run_intake(pdf_path, statement_id=None, statement_period=None) -> dict` — the primary entry point, called by M-021 and M-050.
- `compute_file_hash(pdf_path)`, `check_cache(document_hash)`, `validate_invoice(invoice, rules)`, `write_to_bronze(...)`, `get_skip_reason(invoice)`, `log_row_skip(...)`, `write_skip_exception(...)`, `write_to_review_queue(...)`, `normalize_to_silver(...)`, `write_intake_log(...)`, `update_intake_log_blob_path(...)`, `derive_vendor_slug_from_filename(pdf_path)`, `derive_vendor_name_from_filename(pdf_path)`, `upload_pdf_to_blob_storage(...)`, `update_cache(...)` — all importable individually (used directly by M-050's integration test).

**Error Behaviour**
- `run_intake()` raises `FileNotFoundError` if the PDF path doesn't exist, and lets `CorruptedPDFError` (from M-024's `extract_pdf_text()`) propagate uncaught to its own caller — both M-021 and the `__main__` block catch `CorruptedPDFError` specifically for a clean exit.
- Every non-critical side effect (Blob upload, cache update, row-skip logging, EXTRACTION_INCOMPLETE exception write) is independently wrapped in its own `try/except`, printing a warning and continuing — none of these can abort the pipeline once extraction itself has succeeded.
- A cache HIT skips Steps 2–5 and 7–9 entirely, re-running only Silver normalization under the new `statement_id` — this is the one path where Bronze and Silver disagree on which `statement_id` owns the data (Bronze keeps the original, Silver gets the new one).

**Known Fragility**
- **The three Fabric-cut-over tables' write functions (`update_cache`, `write_to_review_queue`, `write_intake_log`) each compute `MAX(id) + 1` in Python with no transaction/lock** — confirmed not concurrency-safe by each function's own docstring. Two workers processing different PDFs whose intake happens to land on the exact same instant could compute the same next `id` for the same table. See `TOPOLOGY.md` A01 row 8.
- `vendor_id` is derived twice with different logic at two points in `run_intake()` — once from the filename before extraction (line ~660), then overwritten from the AI-extracted or filename-derived `vendor_name` after Step 3 — the first derivation is pure dead weight for anything beyond a possible log line, easy to misread as meaningful.
- The "Auto-suggest exception targets" block at the end of `run_intake()` queries Silver and prints a ready-to-paste `scenario_config.json` snippet purely as developer convenience — wrapped in its own bare `except Exception: pass`, so any failure there is invisible, by design, since it's optional tooling not part of the pipeline's real contract.

**Change Impact** — This module's functions are individually imported and called by M-021 (orchestrator) and M-050 (integration test) — any signature change to `run_intake()` or the internal functions it calls breaks both callers, not just one.

**Callers** — M-021 (`run_intake`, via dynamic module load), M-050 (`run_intake`, via dynamic module load)
**Calls** — M-024 (`extract_pdf_text`, `DocumentUnderstandingEngine().understand()`), M-036 (`normalize_invoice_number`), M-042 (`get_shop_owner`), M-043 (`BlobStorageClient().upload_pdf()`), M-034 (`score_exception_confidence`), M-037 (`execute_sql`/`execute_query`/`execute_sql_fabric`/`execute_query_fabric`)
**Integration Points Used** — IP-008 (Azure SQL/SQLite), IP-009 (Azure Blob Storage, via M-043), IP-011 (Fabric Warehouse, via M-037's fabric functions) — all transitive, not called directly
