## C20 — Mock ERP Generator
ID: M-035
Layer: pipeline
Source file: `src/mock_erp/generator.py`

**Module** — Mock ERP Generator
**ID** — M-035
**Layer** — pipeline
**Primary Responsibility** — Generates a deterministic Mock ERP dataset seeded from Silver VENDOR_STATEMENT rows, applying explicitly configured (never random) exceptions from `scenario_config.json` — the placeholder for a future real NetSuite integration (RULE-06). CLI-only by design (RULE-05) — must never be wired into a dashboard.

**Inputs** — `statement_id`; `config/mock_erp/scenario_config.json` (`missing_invoices`, `amount_mismatches`, `duplicate_invoices`, `pending_posting`, `renumbered_invoices`, `posting_date_lag_days`, `default_erp_status`).

**Outputs** — Rows in `bronze_internal_erp_raw` (DELETE-then-rewrite per `statement_id`, new `erp_version` each run) and `silver_reconciliation_standard` (INTERNAL_ERP side, via `normalize_erp_to_silver()`).

**Public Interface** — `generate_mock_erp(statement_id, config_path=...) -> dict` (counts summary), `normalize_erp_to_silver(statement_id) -> int` (row count), `get_next_erp_version(statement_id) -> int`, `load_scenario_config(config_path)`.

**Error Behaviour** — `generate_mock_erp()` raises `ValueError` if zero Silver VENDOR_STATEMENT rows exist for the statement_id — same hard-stop pattern as M-034.

**Known Fragility**
- **`renumbered_invoices` is the only controlled-exception type able to make Level 1 matching fail while Level 2 (RO+amount) still succeeds** — added this session (`d77f305`) specifically because no prior controlled-exception type could vary `invoice_number` independently between the two sides, meaning Level 2 matching had never fired through a real intake→ERP→matching run before this addition (confirmed: 0 of 1,940 historical `gold_matched_invoices` rows were ever Level 2). A future engineer removing this exception type without realizing its unique role would silently regress test coverage back to "Level 2 provable only in isolated unit calls."
- `posting_date` calculation uses `random.randint(posting_lag_min, posting_lag_max)` — the only genuinely non-deterministic value this otherwise fully-deterministic generator produces; not controlled by `scenario_config.json`'s exception mechanism, just a lag-day range.
- Random posting-date lag means re-running `generate_mock_erp()` twice with an identical config produces byte-different `posting_date` values each time — a subtle deviation from the module's own docstring claim ("This is NOT random").

**Change Impact** — Called directly by M-021 and M-050 (not through M-018's CLI wrapper) — any signature change here breaks both.

**Callers** — M-018 (CLI wrapper), M-021, M-050
**Calls** — M-036 (`normalize_invoice_number`), M-037 (`execute_sql`/`execute_query`)
**Integration Points Used** — IP-008 (via M-037)
