"""
document_understanding_engine.py

The core AI stage. Takes a PDF path, calls the AI provider chain, and
returns a Universal Financial Document Schema dict.

Final chain (see docs/VIVE_Implementation_Context.md Section 3 — Claude
(Haiku 4.5) + pdfplumber/OCR is the settled decision, no other AI
providers):
  Primary:  Claude Vision — send the PDF file directly as a document
            content block. Handles text-based, scanned, thin-text-layer,
            and hybrid PDFs identically, since Claude reads the PDF
            natively regardless of what's underneath.
  Fallback: only reached if Claude Vision itself fails (quota, network,
            etc). Deterministic pdfplumber extraction — no AI, no cost.
            pdfplumber_fallback.extract_with_pdfplumber() now handles
            scanned pages internally via per-page OCR (see its module
            docstring), so this fallback needs no OCR-vs-text branching
            here — it's a single call either way.

There is deliberately no character-count heuristic deciding between a
"text PDF path" and a "scanned PDF path" up front for the primary path —
that kind of threshold-based routing breaks on every new PDF format
variant (e.g. a thin text layer that's neither clearly text nor clearly
scanned). Vision sidesteps the question entirely by not caring what's
inside the PDF.
"""

import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.ai import client_factory
from src.ai.pdfplumber_fallback import extract_with_pdfplumber
from src.ai.audit_logger import log_ai_call

VISION_PROMPT = """You are a financial document understanding system.

Analyze this vendor statement PDF and extract ALL invoice/line-item data.

CRITICAL INSTRUCTIONS — READ CAREFULLY:

1. COLUMN MAPPING — Every vendor uses different column names. You must map whatever columns
   appear in this document to our standard fields:
   - "Invoice #", "Invoice No", "Doc No", "Document", "Ref #", "Reference" → invoice_number
   - "Invoice Date", "Doc Date", "Date", "Transaction Date", "Posted Date" → invoice_date
   - "Due Date", "Payment Due", "Due By" → due_date
   - "Amount", "Invoice Amount", "Charges", "Total", "Gross Amount", "Original Amount" → amount
   - "Balance", "Outstanding", "Amount Due", "Open Amount", "Remaining", "Balance Due",
     "Net Amount", "Unpaid", "Open Balance" → outstanding_amount
   - "RO #", "RO No", "Repair Order", "Work Order", "WO #", "Job #" → ro_number
   - "PO #", "PO No", "Purchase Order" → po_number
   - "Description", "Desc", "Details", "Notes" → description
   - "Shop", "Location", "Branch", "Store", "Entity", "Bill To" → shop

2. MISSING FIELDS — If a column does not exist in this document, set that field to null.
   Do NOT invent data. Do NOT skip the invoice — include it with null for missing fields.

3. AMOUNTS — Always extract as plain numbers. Remove $, commas, parentheses.
   If a field like "Balance" or "Open Amount" exists, map it to outstanding_amount.
   If only one amount column exists, use it for BOTH amount AND outstanding_amount.

4. EVERY LINE — Extract every invoice/transaction line you find. Do not skip any lines.

5. TOTAL ROWS — Capture grand total in statement_total_as_printed. Do NOT include as invoice.

Return ONLY a valid JSON object with this exact structure:
{
  "document_metadata": {
    "document_type": "VENDOR_STATEMENT",
    "source_file": "document.pdf",
    "page_count": <integer>,
    "document_type_confidence": <float 0.0-1.0>
  },
  "vendor_metadata": {
    "vendor_name": "<vendor name or null>",
    "vendor_address": "<address or null>",
    "shop_or_entity": ["<shop name>"],
    "vendor_confidence": <float 0.0-1.0>
  },
  "statement_metadata": {
    "statement_date": "<YYYY-MM-DD or null>",
    "statement_period_start": "<YYYY-MM-DD or null>",
    "statement_period_end": "<YYYY-MM-DD or null>",
    "currency": "<USD or null>",
    "statement_total_as_printed": <float or null>,
    "statement_confidence": <float 0.0-1.0>
  },
  "invoices": [
    {
      "invoice_number": "<string or null>",
      "invoice_date": "<YYYY-MM-DD or null>",
      "due_date": "<YYYY-MM-DD or null>",
      "amount": <float or null>,
      "outstanding_amount": <float or null>,
      "ro_number": "<string or null>",
      "po_number": "<string or null>",
      "work_order_number": "<string or null>",
      "description": "<string or null>",
      "credit": <float or null>,
      "shop": "<string or null>",
      "page_number": <integer>,
      "row_number": <integer>,
      "line_confidence": <float 0.0-1.0>
    }
  ],
  "extraction_confidence": {
    "overall": <float 0.0-1.0>,
    "table_detection_confidence": <float 0.0-1.0>,
    "column_mapping_confidence": <float 0.0-1.0>
  },
  "warnings": []
}

Extract EVERY invoice line. Convert all dates to YYYY-MM-DD. Amounts as plain numbers.
Return only the JSON object."""


class DocumentUnderstandingEngine:
    """
    Universal PDF extraction engine.

    Primary path: Claude Vision (handles any PDF — text, scanned, hybrid).
    Fallback path (only if Claude fails): deterministic pdfplumber, which
    handles scanned pages internally via per-page OCR.

    No PDF-format detection needed. Vision is format-agnostic.

    Usage:
        engine = DocumentUnderstandingEngine()
        result = engine.understand(pdf_text, pdf_path)
        # result is a dict matching the Universal Financial Document Schema
    """

    def understand(self, pdf_text: str, pdf_path: str, statement_id: str = None) -> dict:
        """
        Main entry point.

        pdf_text is accepted for call-site compatibility with
        notebooks/01_document_intake.py (which still calls extract_pdf_text()
        for its own char/page-count logging) but is not used here — both the
        primary (Claude Vision) and fallback (pdfplumber) paths read the PDF
        file directly.
        """
        source_file = os.path.basename(pdf_path)

        # --- PRIMARY PATH: Claude Vision (universal, handles all PDF formats) ---
        print(f"  [Engine] Attempting Claude Vision (primary path — handles any PDF format)...")
        try:
            claude_client = client_factory.get_ai_client("claude")
            response = claude_client.generate_with_file(pdf_path, VISION_PROMPT)

            try:
                log_ai_call(
                    response,
                    interaction_type="DOCUMENT_UNDERSTANDING",
                    prompt_version="vision_v1",
                    source_file=source_file,
                    statement_id=statement_id,
                    extraction_confidence=(
                        response.parsed_json.get("extraction_confidence", {}).get("overall")
                        if response.parsed_json else None
                    ),
                    validation_result="SUCCESS" if response.success else "FAILED",
                )
            except Exception:
                pass

            if response.success and response.parsed_json:
                result = response.parsed_json
                result["_provider_used"] = "claude_vision"
                result["_model_used"] = response.model
                print(f"  [Engine] Claude Vision success — "
                      f"{len(result.get('invoices', []))} invoices extracted")
                return result
            else:
                print(f"  [Engine] Claude Vision failed: {response.error}")
        except Exception as e:
            print(f"  [Engine] Claude Vision error: {e}")

        # --- FALLBACK PATH: deterministic pdfplumber (no AI, no cost) ---
        # extract_with_pdfplumber() handles scanned pages internally via
        # per-page OCR — no OCR-vs-text branching needed here.
        print(f"  [Engine] Falling back to pdfplumber (deterministic)...")
        result = extract_with_pdfplumber(pdf_path)
        result["_provider_used"] = "pdfplumber"
        return result


def extract_pdf_text(pdf_path: str):
    """
    Extract raw text from all pages of a PDF using pdfplumber.
    Returns (text, page_count).

    Still used by notebooks/01_document_intake.py for its own char/page-count
    logging, ahead of calling DocumentUnderstandingEngine.understand().
    """
    import pdfplumber
    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages_text.append(f"--- PAGE {i} ---\n{text}")

    return "\n\n".join(pages_text), page_count
