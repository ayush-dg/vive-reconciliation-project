## C11 — Azure Document Intelligence client
ID: M-024
Layer: pipeline
Source file: src/ai/document_intelligence_client.py

**Module** — Azure Document Intelligence client
**ID** — M-024
**Layer** — pipeline
**Primary Responsibility** — `AIClient` implementation for Azure Document Intelligence's `prebuilt-layout` model (pure table-geometry extraction, not an LLM). Registered, a **prior** active primary per RULES.md RULE-04 history — not currently in the active chain.

**Inputs** — `DocumentIntelligenceClient(config, transport=None)`; `generate_with_file(pdf_path, prompt)` — `prompt` is accepted for interface parity but unused (no LLM prompt applies to a layout-extraction call). `generate()` always returns a clean failure — this client only supports `generate_with_file()`.

**Outputs** — `AIResponse` with `parsed_json` built by reusing `pdfplumber_fallback.py`'s column-header interpreter (`_extract_header_info`, `_extract_invoice_row`, `_find_header_row`, `_map_columns` — imported directly, not duplicated) against the raw table geometry Document Intelligence returns.

**Public Interface**
- `generate(...) -> AIResponse` (always fails — not applicable to this service)
- `generate_with_file(pdf_path, prompt) -> AIResponse`
- Private: `_missing_config_error()`, `_real_analyze_call()`, `_table_to_grid()`, `_build_schema()`, `_clean_error()`

**Error Behaviour** — Retry policy from config (default `max_retries=1`). `_build_schema()` adds an explicit warning if `prebuilt-layout` returned no tables at all, rather than silently returning an empty-but-successful result.

**Known Fragility**
- **`ROW_CONFIDENCE = 0.75` is hardcoded here too** — but structurally different from M-023's case: `prebuilt-layout` has no content understanding at all, so there is no model self-assessment to elicit in the first place (the file's own comment acknowledges this is "not a benchmarked/tuned value"). Same downstream effect (every row clears the 0.60 threshold) but a more defensible root cause — a genuinely absent signal, not a discarded real one.
- **`HEADER_MAX_DATA_START = 2` guard, and the header-detection-per-table-first logic**, exist specifically because of two real bugs found during live testing (per the module's own extensive comments, confirmed against RULES.md RULE-04's account): (1) reusing one document's header for every subsequent table silently discarded most of two vendors' real data (KSI, Fred Beans) whose per-page tables genuinely differ; (2) a trailing "Total Outstanding Invoices..." footer row tripped the same header-detection keyword scan and got misread as a header, discarding 33 real rows on ASTCollex. Both fixes are confirmed present and correctly scoped (the fix for #2 lives here, not in the shared `pdfplumber_fallback.py` keyword list, since pdfplumber's own per-page path never had this failure mode).

**Change Impact** — Shares its column-mapping logic directly with M-028 (`pdfplumber_fallback.py`) via import, not duplication — a change to `_map_columns()`/`_extract_invoice_row()` in that file directly changes this client's behavior too.

**Callers** — M-031 (conditionally, `provider_name == "azure_doc_intel"` — no confirmed live caller does this)
**Calls** — M-028 (`_extract_header_info`, `_extract_invoice_row`, `_find_header_row`, `_map_columns`, all imported directly)
**Integration Points Used** — IP-004 (Azure Document Intelligence)
