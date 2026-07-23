## C02 — document intake pipeline
ID: M-014
Layer: pipeline
Source file: notebooks/01_document_intake.py

**Module** — document intake pipeline
**ID** — M-014
**Layer** — pipeline
**Primary Responsibility** — Main intake pipeline: cache check → AI extraction → validation → Bronze → Silver → intake log → Blob archival → cache update, for one vendor statement PDF.

**Inputs** — `run_intake(pdf_path: str, statement_id: str = None, statement_period: str = None) -> dict` — CLI via `--pdf`/`--statement-id`/`--period`, or called directly (e.g. by `scripts/run_full_pipeline.py`).

**Outputs** — Writes to `bronze_vendor_statement_raw`, `silver_reconciliation_standard`, `document_intake_log`, `extraction_cache`, `validation_document_review_queue`, `gold_exceptions` (for `EXTRACTION_INCOMPLETE` skip rows), `ai_audit_log` (via M-032, for row-skip logging). Uploads the PDF to Blob Storage. Returns a summary dict.

**Public Interface**
- `run_intake(pdf_path, statement_id=None, statement_period=None) -> dict`
- `compute_file_hash(pdf_path) -> str`, `check_cache(document_hash)`, `validate_invoice(invoice, rules) -> (bool, str)`, `write_to_bronze(...) -> int`, `get_skip_reason(invoice) -> str`, `log_row_skip(...)`, `write_skip_exception(...)`, `write_to_review_queue(...)`, `normalize_to_silver(bronze_statement_id, silver_statement_id, vendor_id) -> int`, `write_intake_log(...)`, `update_intake_log_blob_path(...)`, `derive_vendor_slug_from_filename(pdf_path) -> Optional[str]`, `derive_vendor_name_from_filename(pdf_path) -> str`, `upload_pdf_to_blob_storage(...) -> Optional[str]`, `update_cache(...)`

**Error Behaviour**
- **`run_intake()` raises `FileNotFoundError`** if `pdf_path` doesn't exist — the one hard, unguarded failure in this module (deliberately fail-fast for a genuinely-missing input file).
- **Row-skip logging (`log_row_skip`) and exception-writing (`write_skip_exception`) both wrap their DB writes in `try/except Exception`, printing a warning and continuing** — a logging failure never blocks intake from proceeding to the next row.
- **`upload_pdf_to_blob_storage()` wraps its call in a further `try/except`** on top of `BlobStorageClient.upload_pdf()`'s own never-raise guarantee (G12) — "belt and suspenders," confirmed redundant but harmless by source.
- **Cache-hit path returns early** (before Step 2 onward) if `check_cache()` finds a prior successful run — re-normalizes Silver from the cached Bronze rows but does not re-run AI extraction, re-write Bronze, or re-log intake (see A-004's disambiguation_note in DOMAIN_MODEL.json for the resulting `statement_id` semantics quirk this creates).

**Known Fragility**
- **`get_skip_reason()` + `validate_invoice()`'s `required_fields` gate are the two-layer mechanism guaranteeing `invoice_number`/`outstanding_amount` are never null in Silver** (cited directly in DOMAIN_MODEL.json's A-009/A-017 annotations) — any future change to either function's logic directly changes what "guaranteed non-null" means for the domain model.
- **`derive_vendor_name_from_filename()`'s fallback is the sole guarantee that `vendor_name` is never null on the VENDOR_STATEMENT side** — confirmed by this session's investigation that the only 424 null-`vendor_name` Silver rows are orphaned test-seed data that bypassed this function entirely (never went through `run_intake()`), not evidence of a bug in the fallback itself.
- **Auto-suggested exception targets printed after intake** (`SUGGESTED EXCEPTION TARGETS` block) reads real extracted invoice numbers/amounts and prints a ready-to-paste JSON snippet for `scenario_config.json` — this is plain deterministic Python (sorting by amount), not an AI call, confirmed by direct source read despite the "SUGGESTED" phrasing potentially reading as AI-driven.

**Change Impact** — The auto-suggestion block, the Blob upload step, and the cache-check step are each independently wrapped for failure isolation — changing any one should preserve that isolation given how central this module is to the whole pipeline (called by every full pipeline run).

**Callers** — M-018 (`scripts/run_full_pipeline.py`, via dynamic module load + `run_intake()` call)
**Calls** — M-020 (`DocumentUnderstandingEngine`, `extract_pdf_text`), M-033 (`execute_sql`, `execute_query`), M-038 (`normalize_invoice_number`), M-039 (`BlobStorageClient`)
**Integration Points Used** — IP-001 through IP-006 (indirectly, via M-020's provider resolution), IP-008 (Lakehouse database), IP-009 (Azure Blob Storage)
