## C18 — mock ERP generator
ID: M-037
Layer: pipeline
Source file: src/mock_erp/generator.py

**Module** — mock ERP generator
**ID** — M-037
**Layer** — pipeline
**Primary Responsibility** — Generates a realistic Mock ERP dataset seeded from Silver VENDOR_STATEMENT rows, applying controlled (never random) exceptions from `scenario_config.json`. RULE-05/RULE-06: CLI-only, never wired to the dashboard; a deliberate placeholder for a future real NetSuite integration.

**Inputs** — `load_scenario_config(config_path) -> dict`; `get_next_erp_version(statement_id) -> int`; `generate_mock_erp(statement_id, config_path=...) -> dict`; `normalize_erp_to_silver(statement_id) -> int`.

**Outputs** — Writes `bronze_internal_erp_raw` (replacing prior rows for the `statement_id`) and `silver_reconciliation_standard` (`record_source='INTERNAL_ERP'`, also replacing prior rows).

**Public Interface**
- `load_scenario_config(config_path="config/mock_erp/scenario_config.json") -> dict`
- `get_next_erp_version(statement_id) -> int`
- `generate_mock_erp(statement_id, config_path=...) -> dict` — the counts summary dict.
- `normalize_erp_to_silver(statement_id) -> int` — row count written.

**Error Behaviour** — `generate_mock_erp()` raises `ValueError` (uncaught) if zero Silver VENDOR_STATEMENT rows exist for the `statement_id` — "Run 01_document_intake.py first." No other explicit error handling.

**Known Fragility**
- **Deterministic by design, confirmed by source** — every exception category (`missing_invoices`, `amount_mismatches`, `duplicate_invoices`, `pending_posting`) is read directly from `scenario_config.json`'s explicit lists/dicts; the only non-deterministic element is `random.randint()` for the posting-date lag (`posting_date_lag_days`), which affects `posting_date` display only, never matching-relevant fields (`amount`/`outstanding_amount`/`invoice_number`).
- **`normalize_erp_to_silver()` hardcodes `vendor_name = None`** (comment: "not stored in ERP Bronze") and `currency = None`, `due_date = None`, `description = None` — these are the exact fields confirmed structurally null on the INTERNAL_ERP side in DOMAIN_MODEL.json's null_semantic annotations, traced directly to this function.
- **ERP versioning (`erp_version`) increments on every re-generation** for the same `statement_id`, but old Bronze/Silver ERP rows are deleted before the new version is written (not retained as history) — `erp_version` on the surviving row always reflects the latest generation, not a true version history.

**Change Impact** — `normalize_erp_to_silver()`'s field-mapping decisions (what's hardcoded null vs. copied from Bronze) directly define the ERP-side semantics recorded in DOMAIN_MODEL.json — any change here should be reflected there too.

**Callers** — M-015 (`notebooks/02_generate_mock_erp.py`), M-018 (`scripts/run_full_pipeline.py`, direct import)
**Calls** — M-033 (`execute_sql`, `execute_query`), M-038 (`normalize_invoice_number`, inside `normalize_erp_to_silver()`)
**Integration Points Used** — IP-008 (Lakehouse database)
