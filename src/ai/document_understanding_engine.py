"""
document_understanding_engine.py

The core AI stage. Takes a PDF path, calls the AI provider chain, and
returns a Universal Financial Document Schema dict.

Final chain (see RULES.md RULE-04 — Azure OpenAI gpt-5-mini + pdfplumber/OCR
is the settled decision, no other AI providers active):
  Primary:  Whichever provider client_factory.get_ai_client() resolves from
            active_provider.json's provider_chain (currently Azure OpenAI
            gpt-5-mini) — send the PDF file directly as a document content
            block. Handles text-based, scanned, thin-text-layer, and hybrid
            PDFs identically, since the model reads the PDF natively
            regardless of what's underneath.
  Fallback: only reached if the primary provider itself fails (quota,
            network, timeout, etc). Deterministic pdfplumber extraction —
            no AI, no cost. pdfplumber_fallback.extract_with_pdfplumber()
            now handles scanned pages internally via per-page OCR (see its
            module docstring), so this fallback needs no OCR-vs-text
            branching here — it's a single call either way.

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

6. EXACT TRANSCRIPTION OF NUMBERS — invoice_number, ro_number, po_number, and work_order_number
   must be transcribed EXACTLY character-by-character as printed. Never infer, correct, "clean up",
   normalize, or add/remove a prefix or suffix — even if a similar-looking number elsewhere in the
   document makes a different reading seem more plausible. Do NOT assume a prefix pattern applies
   uniformly (e.g. do not assume every row shares the same letter prefix as a nearby row). If a
   character is genuinely illegible, transcribe your best single reading and set line_confidence low
   (below 0.5) rather than silently substituting a "corrected" or guessed value.

7. MIXED PREFIX PATTERNS — When a column contains rows with different prefix patterns (e.g. some
   rows start with I, others with M), treat each row's prefix as independently uncertain — do NOT
   assume nearby rows share the same prefix. Lower line_confidence to 0.5 for any row where you are
   not fully certain of the first character.

8. CONFIDENCE CALIBRATION — A confidence score of 0.85 or above means you can read every character
   clearly and are certain it is correct. Do not assign 0.85+ if there is any ambiguity about any
   character in any field.

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

    Primary path: whichever provider is active in provider_chain (handles
    any PDF — text, scanned, hybrid). Fallback path (only if the primary
    provider fails): deterministic pdfplumber, which handles scanned pages
    internally via per-page OCR.

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
        primary (active AI provider) and fallback (pdfplumber) paths read
        the PDF file directly.
        """
        source_file = os.path.basename(pdf_path)

        # --- PRIMARY PATH: active provider from provider_chain (universal, handles all PDF formats) ---
        primary_client = client_factory.get_ai_client()
        provider_label = primary_client.__class__.__name__
        print(f"  [Engine] Attempting {provider_label} (primary path — handles any PDF format)...")
        try:
            response = primary_client.generate_with_file(pdf_path, VISION_PROMPT)

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
                result["_provider_used"] = response.provider
                result["_model_used"] = response.model
                print(f"  [Engine] {provider_label} success — "
                      f"{len(result.get('invoices', []))} invoices extracted")
                return result
            else:
                print(f"  [Engine] {provider_label} failed: {response.error}")
        except Exception as e:
            print(f"  [Engine] {provider_label} error: {e}")

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
