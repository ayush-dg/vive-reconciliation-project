"""
document_understanding_engine.py

The core AI stage. Takes a PDF path, calls the AI provider chain, and
returns a Universal Financial Document Schema dict.

Extraction strategy — universal, no PDF-format detection:
  Primary:  Gemini Vision — send PDF bytes directly. Handles text-based,
            scanned, thin-text-layer, and hybrid PDFs identically, since
            it reads the page as an image regardless of what's underneath.
  Fallback: only reached if Gemini Vision itself fails (quota, network,
            etc). pdfplumber's extracted text is used if substantial;
            otherwise pytesseract OCR runs first. Either way the text is
            then sent to the remaining providers (Groq, then pdfplumber
            last-resort table parsing).

There is deliberately no character-count heuristic deciding between a
"text PDF path" and a "scanned PDF path" up front — that kind of
threshold-based routing breaks on every new PDF format variant (e.g. a
thin text layer that's neither clearly text nor clearly scanned). Vision
sidesteps the question entirely by not caring what's inside the PDF.
"""

import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.ai import client_factory
from src.ai.pdfplumber_fallback import extract_with_pdfplumber
from src.ai.audit_logger import log_ai_call

# Used ONLY in the Gemini-Vision-failed fallback path, to decide between
# sending pdfplumber's text vs running OCR first. NOT used for primary
# routing — Vision is tried on every PDF regardless of its text content.
FALLBACK_TEXT_THRESHOLD = 500  # chars

EXTRACTION_PROMPT_VERSION = "v1"

EXTRACTION_PROMPT_TEMPLATE = """You are a financial document understanding system specializing in vendor statement reconciliation.

Analyze the following text extracted from a vendor statement PDF and extract ALL invoice/line-item data.

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
   - "Description", "Desc", "Details", "Notes", "Reference Description" → description
   - "Shop", "Location", "Branch", "Store", "Entity", "Bill To" → shop

2. MISSING FIELDS — If a column does not exist in this document, set that field to null.
   Do NOT invent data. Do NOT skip the invoice — include it with null for missing fields.

3. AMOUNTS — Always extract as plain numbers. Remove $, commas, parentheses.
   If a field like "Balance" or "Open Amount" exists, map it to outstanding_amount.
   If only one amount column exists, use it for BOTH amount AND outstanding_amount.

4. EVERY LINE — Extract every invoice/transaction line you find. Do not skip lines.
   Include credit memos, adjustments, and payments if present (set credit field for credits).

5. TOTAL ROWS — If you see a "Total" or "Grand Total" row at the bottom, capture the
   amount in statement_total_as_printed but do NOT include it as an invoice line.

6. VENDOR INFO — Extract vendor name, address, and the shop/customer name from the header.

Return ONLY a valid JSON object matching this exact schema. No explanation, no markdown.

{{
  "document_metadata": {{
    "document_type": "VENDOR_STATEMENT",
    "source_file": "{source_file}",
    "page_count": <integer>,
    "document_type_confidence": <float 0.0-1.0>
  }},
  "vendor_metadata": {{
    "vendor_name": "<vendor company name or null>",
    "vendor_address": "<vendor address or null>",
    "shop_or_entity": ["<shop/customer name>"],
    "vendor_confidence": <float 0.0-1.0>
  }},
  "statement_metadata": {{
    "statement_date": "<YYYY-MM-DD or null>",
    "statement_period_start": "<YYYY-MM-DD or null>",
    "statement_period_end": "<YYYY-MM-DD or null>",
    "currency": "<USD or null>",
    "statement_total_as_printed": <float or null>,
    "statement_confidence": <float 0.0-1.0>
  }},
  "invoices": [
    {{
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
    }}
  ],
  "extraction_confidence": {{
    "overall": <float 0.0-1.0>,
    "table_detection_confidence": <float 0.0-1.0>,
    "column_mapping_confidence": <float 0.0-1.0>
  }},
  "warnings": [
    {{
      "code": "<AMBIGUOUS_COLUMN|LOW_CONFIDENCE_FIELD|OTHER>",
      "message": "<what was ambiguous>",
      "severity": "<LOW|MEDIUM|HIGH>"
    }}
  ]
}}

PDF TEXT TO ANALYZE:
---
{pdf_text}
---

Return only the JSON object. Begin with {{ and end with }}.
"""

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

    Primary path: Gemini Vision (handles any PDF — text, scanned, hybrid).
    Fallback path (only if Gemini fails): pdfplumber text OR OCR, sent to Groq.

    No PDF-format detection needed. Vision is format-agnostic.

    Usage:
        engine = DocumentUnderstandingEngine()
        result = engine.understand(pdf_text, pdf_path)
        # result is a dict matching the Universal Financial Document Schema
    """

    def __init__(self):
        self.provider_chain = client_factory.get_provider_chain()

    def understand(self, pdf_text: str, pdf_path: str, statement_id: str = None) -> dict:
        """
        Main entry point.
        pdf_text is provided but only used by the fallback path.
        The primary path re-reads the PDF bytes directly for Gemini Vision.
        """
        source_file = os.path.basename(pdf_path)

        # --- PRIMARY PATH: Gemini Vision (universal, handles all PDF formats) ---
        print(f"  [Engine] Attempting Gemini Vision (primary path — handles any PDF format)...")
        try:
            gemini_client = client_factory.get_ai_client("gemini")
            response = gemini_client.generate_with_file(pdf_path, VISION_PROMPT)

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
                result["_provider_used"] = "gemini_vision"
                result["_model_used"] = response.model
                print(f"  [Engine] Gemini Vision success — "
                      f"{len(result.get('invoices', []))} invoices extracted")
                return result
            else:
                print(f"  [Engine] Gemini Vision failed: {response.error}")
        except Exception as e:
            print(f"  [Engine] Gemini Vision error: {e}")

        # --- FALLBACK PATH: pdfplumber text OR OCR, then Groq ---
        print(f"  [Engine] Falling back to text-based extraction...")

        # Decide between using pdfplumber's text or running OCR
        if len(pdf_text.strip()) > FALLBACK_TEXT_THRESHOLD:
            # Trim to keep total tokens under Groq's 12K TPM limit.
            #
            # NOTE: an 18000-char trim was tried first (per the ~4 chars/token
            # rule of thumb: 18000 chars ~= 4500 tokens + ~2000 prompt +
            # ~4096 output ~= 10600, "safely" under 12K). Verified empirically
            # against a real 24-page statement (Tekion) and it still failed —
            # Groq reported ~13.6K tokens requested. Two things broke the
            # estimate: dense numeric/tabular statement text tokenizes far
            # less efficiently than prose (closer to ~1.6 chars/token here,
            # not ~4), and the column-mapping instructions added to this
            # prompt made the template itself ~3800 chars, not ~2000.
            # 14000 chars passed in that same test; 12000 is used here for
            # headroom across vendors with even denser text.
            text_to_send = pdf_text[:12000]
            print(f"  [Engine] Using pdfplumber text "
                  f"({len(pdf_text.strip())} chars, trimmed to {len(text_to_send)} for Groq token limit)")
        else:
            print(f"  [Engine] pdfplumber text insufficient ({len(pdf_text.strip())} chars) — running OCR")
            try:
                from src.ai.ocr_extractor import extract_text_with_ocr, is_ocr_available
                if is_ocr_available():
                    ocr_text, _ = extract_text_with_ocr(pdf_path)
                    if len(ocr_text.strip()) > FALLBACK_TEXT_THRESHOLD:
                        text_to_send = ocr_text[:12000]
                        print(f"  [Engine] OCR extracted {len(ocr_text)} chars "
                              f"(trimmed to {len(text_to_send)} for Groq token limit)")
                    else:
                        print(f"  [Engine] OCR text insufficient — giving up")
                        return _empty_schema(pdf_path)
                else:
                    print(f"  [Engine] pytesseract not available — falling through to pdfplumber_fallback")
                    result = extract_with_pdfplumber(pdf_path)
                    result["_provider_used"] = "pdfplumber"
                    return result
            except Exception as e:
                print(f"  [Engine] OCR failed: {e}")
                return _empty_schema(pdf_path)

        # Send the text (either pdfplumber's or OCR'd) to the remaining providers
        for provider_name in self.provider_chain:
            if provider_name == "gemini":
                # Already tried Gemini via Vision above; skip in text fallback
                continue
            if provider_name == "pdfplumber":
                print(f"  [Engine] Falling back to pdfplumber last resort")
                result = extract_with_pdfplumber(pdf_path)
                result["_provider_used"] = "pdfplumber"
                return result

            print(f"  [Engine] Trying provider: {provider_name}")
            try:
                client = client_factory.get_ai_client(provider_name)
            except Exception as e:
                print(f"  [Engine] Could not load {provider_name} client: {e}")
                continue

            prompt = EXTRACTION_PROMPT_TEMPLATE.format(
                source_file=source_file,
                pdf_text=text_to_send[:50000],
            )
            response = client.generate(prompt)

            try:
                log_ai_call(
                    response,
                    interaction_type="DOCUMENT_UNDERSTANDING",
                    prompt_version=EXTRACTION_PROMPT_VERSION,
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
                result["_provider_used"] = provider_name
                result["_model_used"] = response.model
                print(f"  [Engine] Success with {provider_name} — "
                      f"{len(result.get('invoices', []))} invoices extracted")
                return result
            else:
                print(f"  [Engine] {provider_name} failed: {response.error}")
                continue

        return _empty_schema(pdf_path)


def extract_pdf_text(pdf_path: str):
    """
    Extract raw text from all pages of a PDF using pdfplumber.
    Returns (text, page_count).

    This is called FIRST, before any AI provider — all paths
    (Gemini, Groq, and pdfplumber fallback) start with this.
    """
    import pdfplumber
    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages_text.append(f"--- PAGE {i} ---\n{text}")

    return "\n\n".join(pages_text), page_count


def _empty_schema(pdf_path: str) -> dict:
    return {
        "document_metadata": {
            "document_type": "UNKNOWN",
            "source_file": pdf_path,
            "page_count": 0,
            "document_type_confidence": 0.0,
        },
        "vendor_metadata": {"vendor_name": None, "vendor_address": None, "shop_or_entity": [], "vendor_confidence": None},
        "statement_metadata": {"statement_date": None, "statement_period_start": None, "statement_period_end": None, "currency": None, "statement_total_as_printed": None, "statement_confidence": None},
        "invoices": [],
        "extraction_confidence": {"overall": 0.0, "table_detection_confidence": 0.0, "column_mapping_confidence": 0.0},
        "warnings": [{"code": "OTHER", "message": "All providers failed — no extraction possible", "severity": "HIGH"}],
        "_provider_used": "none",
    }
