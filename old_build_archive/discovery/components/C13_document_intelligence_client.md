## C13 — Azure Document Intelligence Client
ID: M-028
Layer: pipeline
Source file: `src/ai/document_intelligence_client.py`

**Module** — Azure Document Intelligence Client
**ID** — M-028
**Layer** — pipeline
**Primary Responsibility** — Dormant (not in the active chain). Uses the `prebuilt-layout` model (not `prebuilt-invoice`) to extract generic table geometry, then reuses M-031's column-header interpreter to map cells to schema fields.

**Inputs** — `config` (`config/ai/azure_doc_intel.json`); env vars for API key/endpoint.

**Outputs** — `AIResponse` wrapping a Universal Financial Document Schema dict.

**Public Interface** — `DocumentIntelligenceClient(config, transport=None)`, `.generate()` (returns a clean failure — this is a document-extraction-only service, no text-completion mode), `.generate_with_file()`.

**Error Behaviour** — Never raises. Retries (default 1) on the whole-document call. A continuation table whose column count doesn't match the last detected header is skipped with a warning rather than risking misaligned data — a deliberate correctness-over-completeness choice.

**Known Fragility** — `_build_schema()`'s continuation-table logic (reuse the last `col_map` only when column counts match) is tuned to one confirmed real case (`ASTCollex0526.pdf`, one logical table split across pages, header only on page 1) — a vendor whose statement genuinely has multiple different tables with the same column count on different pages would have those wrongly treated as one continued table, or vice versa, with no way to distinguish the two cases from column count alone.

**Change Impact** — None currently — dormant, prior primary superseded twice (see RULES.md RULE-04 history).

**Callers** — M-023 (`get_ai_client("azure_doc_intel")`, instantiation — no current caller reaches this without an explicit provider name)
**Calls** — M-031 (`_extract_header_info`, `_extract_invoice_row`, `_find_header_row`, `_map_columns` — shared helpers)
**Integration Points Used** — IP-004 (Azure Document Intelligence)
