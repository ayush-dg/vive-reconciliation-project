"""
document_intelligence_client.py

Azure Document Intelligence implementation of AIClient. The ONLY file that
knows Document Intelligence's SDK/wire format.

Uses the "prebuilt-layout" model, not "prebuilt-invoice" — prebuilt-invoice
is built for one invoice per document with a header-level InvoiceId/
AmountDue and an Items array for that single invoice's own line items. Our
documents are vendor statements: one page holding a table of many separate
invoices as rows, each needing its own invoice_number/amount/outstanding_
amount, plus dealer-specific fields (ro_number, work_order_number) that
don't exist in prebuilt-invoice's schema at all. prebuilt-layout returns
generic table geometry (rows/cells, no semantic field labels); the same
column-header interpreter already used by the pdfplumber fallback
(_find_header_row / _map_columns / _extract_invoice_row) is reused here to
turn those raw cells into schema fields — see RULE-07 (universal,
per-vendor-config-free column mapping).

Key behavior this client works around (confirmed by direct testing against
the live endpoint on sample_data/ASTCollex0526.pdf):
  - The whole PDF is sent in ONE call — prebuilt-layout handles multi-page
    documents (and scanned pages, via its own internal OCR) natively.
    Unlike AzureOpenAIClient, there is no need to split into per-page calls.
  - prebuilt-layout returns one Table object per page for a table that
    visually continues across pages, but only the FIRST such table includes
    the header row — continuation tables on later pages start directly
    with data rows. The header (and the col_map built from it) is detected
    once and reused for every subsequent table with a matching column
    count; a later table whose column count doesn't match gets a warning
    and is skipped rather than silently misaligned.
"""

import json
import time
from typing import Callable, Optional

from .base_client import AIClient, AIResponse
from .pdfplumber_fallback import (
    _extract_header_info,
    _extract_invoice_row,
    _find_header_row,
    _map_columns,
)

# _find_header_row() is a broad keyword-substring scan across ALL rows of a
# table, not just the top — fine for pdfplumber's per-page tables (the real
# header is always found before any footer row further down the same page),
# but calling it on a headerless continuation table can walk all the way to
# a trailing summary row (e.g. "Total Outstanding Invoices: $13,860.79",
# which trips the same >=2 keyword threshold via "outstanding"+"invoice")
# and misread it as the header. A real header is always at/near row 0 of a
# table; a totals footer is always at the bottom — reject any match found
# later than this as a false positive rather than editing the shared
# keyword list (which pdfplumber's own per-page path still relies on as-is).
HEADER_MAX_DATA_START = 2

# Fixed confidence for rows extracted from a Document Intelligence table.
# Same spirit as pdfplumber_fallback's 0.65 (real geometry-based extraction,
# not OCR-text-guessing) — not a benchmarked/tuned value, just deliberately
# below "1.0 = certain" while above pdfplumber's own geometry confidence,
# since prebuilt-layout's table detection is purpose-built rather than a
# generic PDF-library heuristic. Revisit once real accuracy data exists.
ROW_CONFIDENCE = 0.75


class DocumentIntelligenceClient(AIClient):
    def __init__(self, config: dict, transport: Optional[Callable] = None):
        """
        config   : parsed config/ai/azure_doc_intel.json
        transport: optional injectable callable for testing.
                   Signature: (pdf_path, config) -> (success, tables, error)
                   where `tables` is a list of raw table grids — each grid a
                   list of rows, each row a list of cell strings (the same
                   shape pdfplumber's extract_table() returns) — one grid
                   per Document Intelligence Table object, in document order.
                   If None, uses the real Document Intelligence SDK call.
        """
        self.config = config
        self._transport = transport

        import os
        self.api_key = os.environ.get(config.get("api_key_env_var", "AZURE_DOC_INTEL_KEY"))
        self.endpoint = os.environ.get(config.get("endpoint_env_var", "AZURE_DOC_INTEL_ENDPOINT"))
        self.model_id = config.get("model_id", "prebuilt-layout")

    def _missing_config_error(self) -> Optional[str]:
        if not self.api_key:
            return f"Missing API key — env var '{self.config.get('api_key_env_var')}' not set"
        if not self.endpoint:
            return f"Missing endpoint — env var '{self.config.get('endpoint_env_var')}' not set"
        return None

    def generate(self, prompt: str, *, temperature=None, max_output_tokens=None) -> AIResponse:
        # Document Intelligence is a document-extraction service, not a
        # text-completion model — generate() exists only to satisfy the
        # AIClient interface. document_understanding_engine.py never calls
        # it; use generate_with_file() instead.
        return AIResponse(
            success=False,
            provider="azure_document_intelligence",
            model=self.model_id,
            error="DocumentIntelligenceClient only supports generate_with_file() "
                  "— text-only prompts aren't applicable to a document-extraction service",
        )

    def generate_with_file(self, pdf_path: str, prompt: str) -> AIResponse:
        """
        Analyze the full PDF in one call with prebuilt-layout, map the
        returned tables to the Universal Financial Document Schema.

        `prompt` is accepted for AIClient interface parity but unused —
        there is no LLM prompt in a layout-extraction call.
        """
        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="azure_document_intelligence",
                               model=self.model_id, error=missing)

        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 1)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        start = time.monotonic()
        last_error = None

        for attempt in range(1, max_retries + 2):
            if self._transport:
                success, tables, error = self._transport(pdf_path, self.config)
                page1_text = ""
            else:
                success, tables, page1_text, error = self._real_analyze_call(pdf_path)

            if success:
                latency_ms = (time.monotonic() - start) * 1000
                result, warnings = self._build_schema(pdf_path, tables, page1_text)
                if not result["invoices"] and not warnings:
                    warnings.append("prebuilt-layout returned no tables — document may not "
                                     "have a tabular layout, or the page images were unreadable")
                result["warnings"] = [
                    {"code": "OTHER", "message": w, "severity": "MEDIUM"} for w in warnings
                ]
                text_out = json.dumps(result)
                return AIResponse(
                    success=True, text=text_out, parsed_json=result,
                    model=self.model_id, provider="azure_document_intelligence",
                    latency_ms=latency_ms, attempt_count=attempt,
                )

            last_error = error
            if attempt <= max_retries:
                time.sleep(backoff * (multiplier ** (attempt - 1)))

        latency_ms = (time.monotonic() - start) * 1000
        return AIResponse(
            success=False, provider="azure_document_intelligence", model=self.model_id,
            latency_ms=latency_ms, attempt_count=max_retries + 1, error=last_error,
        )

    def _real_analyze_call(self, pdf_path: str):
        """
        Real Document Intelligence call. Returns
        (success, tables_as_grids, page1_text, error).
        """
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient as _SDKClient
            from azure.core.credentials import AzureKeyCredential

            client = _SDKClient(endpoint=self.endpoint, credential=AzureKeyCredential(self.api_key))

            with open(pdf_path, "rb") as f:
                poller = client.begin_analyze_document(
                    self.model_id, body=f, content_type="application/pdf",
                )
            result = poller.result()

            grids = [self._table_to_grid(t) for t in (result.tables or [])]

            page1_text = ""
            if result.pages:
                page1_text = "\n".join(line.content for line in (result.pages[0].lines or []))

            return True, grids, page1_text, None
        except Exception as e:
            return False, None, "", self._clean_error(str(e))

    @staticmethod
    def _table_to_grid(table) -> list:
        """Convert a Document Intelligence Table object into a pdfplumber-style
        grid: a list of rows, each row a list of cell strings."""
        grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
        for cell in table.cells:
            if 0 <= cell.row_index < table.row_count and 0 <= cell.column_index < table.column_count:
                grid[cell.row_index][cell.column_index] = cell.content
        return grid

    def _build_schema(self, pdf_path: str, tables: list, page1_text: str):
        """Turn a list of table grids into a Universal Financial Document
        Schema dict, reusing pdfplumber_fallback's header-detection and
        column-mapping helpers. Returns (schema_dict, warnings_list)."""
        import os

        warnings = []
        all_invoices = []
        col_map = None
        header_col_count = None

        vendor_name, shop_name = _extract_header_info(page1_text) if page1_text else (None, None)

        for page_num, grid in enumerate(tables or [], start=1):
            if not grid:
                continue

            # Try header detection on THIS table independently first — most
            # vendors put a genuinely different table on each page (different
            # column counts/layouts per shop or section), not a continuation
            # of one ledger. Only fall back to reusing the last col_map when
            # this table has no header of its own AND its shape matches the
            # last one that did — that's the ASTCollex case (one logical
            # table split across pages, header only on page 1).
            header_row, data_start = _find_header_row(grid)
            if header_row and data_start <= HEADER_MAX_DATA_START:
                col_map = _map_columns(header_row)
                header_col_count = len(header_row)
                rows_to_process = grid[data_start:]
            elif col_map is not None and len(grid[0]) == header_col_count:
                rows_to_process = grid
            else:
                warnings.append(
                    f"Table {page_num}: could not identify column headers"
                    if col_map is None else
                    f"Table {page_num}: column count ({len(grid[0])}) doesn't match "
                    f"the last detected header ({header_col_count}) — skipped rather than "
                    f"risk misaligned data"
                )
                continue

            for row_num, row in enumerate(rows_to_process, start=1):
                invoice = _extract_invoice_row(
                    row, col_map, page_num, row_num, shop_name,
                    confidence=ROW_CONFIDENCE,
                )
                if invoice:
                    all_invoices.append(invoice)

        statement_total = sum(
            inv.get("outstanding_amount", 0) or 0
            for inv in all_invoices
            if inv.get("outstanding_amount") is not None
        )

        confidence = ROW_CONFIDENCE if all_invoices else 0.20

        result = {
            "document_metadata": {
                "document_type": "VENDOR_STATEMENT",
                "source_file": os.path.basename(pdf_path),
                "page_count": len(tables or []),
                "document_type_confidence": 0.60,  # not classified — layout extraction has no doc-type signal
            },
            "vendor_metadata": {
                "vendor_name": vendor_name,
                "vendor_address": None,
                "shop_or_entity": [shop_name] if shop_name else [],
                "vendor_confidence": 0.50 if vendor_name else 0.10,
            },
            "statement_metadata": {
                "statement_date": None,
                "statement_period_start": None,
                "statement_period_end": None,
                "currency": "USD",
                "statement_total_as_printed": statement_total if all_invoices else None,
                "statement_confidence": 0.50,
            },
            "invoices": all_invoices,
            "extraction_confidence": {
                "overall": confidence,
                "table_detection_confidence": 0.90 if tables else 0.20,
                "column_mapping_confidence": 0.70 if col_map else 0.10,
            },
            "warnings": [],
        }
        return result, warnings

    def _clean_error(self, raw_error: str) -> str:
        """Convert a raw azure-core/Document Intelligence SDK error into a
        short, readable message. Kept local/self-contained rather than
        imported from azure_openai_client — each provider file owns its own
        wire-format error handling end to end (same precedent as ClaudeClient's
        and AzureOpenAIClient's own duplicated salvage/error logic)."""
        if not raw_error:
            return "unknown error"

        raw = str(raw_error)
        raw_lower = raw.lower()

        if "rate_limit" in raw_lower or "429" in raw:
            return "rate limited — try again shortly"

        if "authentication" in raw_lower or "401" in raw or "invalid api key" in raw_lower:
            return "invalid API key"

        if "permission" in raw_lower or "403" in raw:
            return "permission denied — check API key / resource access"

        if "404" in raw or "resourcenotfound" in raw_lower.replace(" ", ""):
            return "resource not found — check endpoint / model_id"

        if "timeout" in raw_lower or "timed out" in raw_lower:
            return "request timed out"

        if "connection" in raw_lower or "network" in raw_lower:
            return "network error"

        first_line = raw.split("\n")[0][:150]
        return first_line
