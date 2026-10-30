"""
document_understanding_engine.py

The core AI stage. Takes a PDF path, calls the AI provider chain, and
returns a Universal Financial Document Schema dict.

Final chain (see RULES.md RULE-04 — Claude Sonnet 4.6 + pdfplumber/OCR is
the current chain; superseded three times, see RULE-04 for the full
history):
  Primary:  Whichever provider client_factory.get_ai_client() resolves from
            active_provider.json's provider_chain (currently Claude Sonnet
            4.6) — send the PDF file directly as a document content
            block. Handles text-based, scanned, thin-text-layer, and hybrid
            PDFs identically, since the model reads the PDF natively
            regardless of what's underneath.
  Fallback: only reached if the primary provider itself fails (quota,
            network, timeout, etc). Deterministic pdfplumber extraction —
            no AI, no cost. pdfplumber_fallback.extract_with_pdfplumber()
            now handles scanned pages internally via per-page OCR (see its
            module docstring), so this fallback needs no OCR-vs-text
            branching here — it's a single call either way.
[Corrected 2026-07-24, BCE Stage 3 documentation sweep follow-up — this
docstring previously named Azure OpenAI gpt-5-mini as primary, and was
missed by the original six-location sweep despite being one of the
locations INVARIANT_CATALOGUE.md's IC-4 itself named as stale.]

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
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.ai import client_factory
from src.ai.pdfplumber_fallback import extract_with_pdfplumber
from src.ai.audit_logger import log_ai_call
from src.ai.base_client import AIResponse
from src.ai.page_orientation import upright_copy
from src.pipeline_timing import timed_step


class CorruptedPDFError(Exception):
    """Raised by extract_pdf_text() when the file can't be opened as a PDF
    at all (invalid structure, not just a hard-to-parse layout) — a
    corrupted upload or a non-PDF file saved with a .pdf extension."""


VISION_PROMPT = """You are a financial document understanding system.

Analyze this vendor statement PDF and extract ALL invoice/line-item data.

CRITICAL INSTRUCTIONS — READ CAREFULLY:

1. COLUMN MAPPING — Every vendor uses different column names, including names you have never
   seen before. Map by SEMANTIC MEANING, not by matching against a fixed list — the examples
   below are illustrative, not exhaustive. Ask yourself what each column is FOR, not just what
   it's literally labeled:
   - Anything identifying a specific invoice/transaction ("Invoice #", "Invoice No", "Doc No",
     "Document", "Document No.", "Ref #", "Reference", "Inv #", "Ticket #", "Transaction #",
     or any other vendor-specific label serving the same purpose) → invoice_number
   - Anything dating the invoice/transaction ("Invoice Date", "Doc Date", "Date", "Transaction Date",
     "Posted Date") → invoice_date
   - Anything giving a payment deadline ("Due Date", "Payment Due", "Due By") → due_date
   - Anything giving the original charge ("Amount", "Invoice Amount", "Charges", "Total",
     "Gross Amount", "Original Amount") → amount
   - Anything giving what's still owed ("Balance", "Outstanding", "Amount Due", "Open Amount",
     "Remaining", "Balance Due", "Net Amount", "Unpaid", "Open Balance") → outstanding_amount
   - Anything referencing a repair/work order ("RO #", "RO No", "Repair Order", "Work Order",
     "WO #", "Job #") → ro_number
   - Anything referencing a purchase order ("PO #", "PO No", "Purchase Order") → po_number
   - Anything describing the line item ("Description", "Desc", "Details", "Notes") → description
   - Anything identifying the paying location ("Shop", "Location", "Branch", "Store", "Entity",
     "Bill To") → shop
   If this vendor's layout uses a column name you don't recognize, reason about its likely
   purpose from context (its position in the table, the kind of values in it, the header text's
   meaning) rather than giving up on mapping it.

2. MISSING FIELDS — If this vendor's layout has no column for a given field at all, set that
   field to null. Never invent a value and never infer one from other fields, context, or what
   a "typical" statement usually has — null is always correct when the data genuinely isn't
   present in this document. Do NOT skip the invoice — include it with null for missing fields.

3. UNREADABLE PAGES — If an entire page is too blurry, low-resolution, or otherwise unclear to
   read reliably (not just a single ambiguous character, but the page as a whole), do not guess
   at its contents. Return an empty invoices list for that page, set extraction_confidence.overall
   below 0.3, and add a warning explaining that the page could not be read reliably.

4. AMOUNTS — Always extract as plain numbers. Remove $, commas, parentheses.
   If a field like "Balance" or "Open Amount" exists, map it to outstanding_amount.
   If only one amount column exists, use it for BOTH amount AND outstanding_amount.

5. EVERY LINE — Extract every invoice/transaction line you find. Do not skip any lines.

6. TOTAL ROWS — Capture grand total in statement_total_as_printed. Do NOT include as invoice.

7. EXACT TRANSCRIPTION OF NUMBERS — invoice_number, ro_number, po_number, and work_order_number
   must be transcribed EXACTLY character-by-character as printed. Never infer, correct, "clean up",
   normalize, or add/remove a prefix or suffix — even if a similar-looking number elsewhere in the
   document makes a different reading seem more plausible. Do NOT assume a prefix pattern applies
   uniformly (e.g. do not assume every row shares the same letter prefix as a nearby row). If a
   character is genuinely illegible, transcribe your best single reading and set line_confidence low
   (below 0.5) rather than silently substituting a "corrected" or guessed value.

8. MIXED PREFIX PATTERNS — When a column contains rows with different prefix patterns (e.g. some
   rows start with I, others with M), treat each row's prefix as independently uncertain — do NOT
   assume nearby rows share the same prefix. Lower line_confidence to 0.5 for any row where you are
   not fully certain of the first character.

9. CONFIDENCE CALIBRATION — A confidence score of 0.85 or above means you can read every character
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

        # Scanned pages rotated sideways or upside down are sent upright --
        # see src/ai/page_orientation.py. A no-op (same path back) for
        # upright scans, text PDFs, or if detection isn't available.
        with timed_step("orientation"):
            send_path, _rotations = upright_copy(pdf_path)
        try:
            return self._understand(pdf_path, send_path, source_file, statement_id)
        finally:
            if send_path != pdf_path:
                try:
                    os.remove(send_path)
                except OSError:
                    pass

    def _call(self, client, send_path: str, source_file: str, statement_id: str):
        """One AI call, audit-logged; raises what the client raises (after logging it)."""
        started = time.monotonic()
        try:
            with timed_step("ai_call"):
                response = client.generate_with_file(send_path, VISION_PROMPT)
        except Exception as e:
            _log_call_exception(client, e, time.monotonic() - started, source_file, statement_id)
            raise
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
        except Exception as e:
            print(f"  [Engine] ai_audit_log row not written ({type(e).__name__}: {e})")
        return response

    def _understand(self, pdf_path: str, send_path: str, source_file: str, statement_id: str = None) -> dict:
        # --- PRIMARY PATH: active provider from provider_chain (universal, handles all PDF formats) ---
        primary_client = client_factory.get_ai_client()
        provider_label = primary_client.__class__.__name__
        print(f"  [Engine] Attempting {provider_label} (primary path — handles any PDF format)...")
        answers = []
        try:
            response = self._call(primary_client, send_path, source_file, statement_id)
            shortfall = _shortfall(response, pdf_path)
            if shortfall:
                # No rows, or far fewer than the PDF's text layer prints (2026-10-26, the Faulkner case):
                # one automatic retry before any fallback.
                print(f"  [Engine] {provider_label}: {shortfall} -- retrying the AI call once")
                answers.append((response, shortfall))
                response = self._call(primary_client, send_path, source_file, statement_id)
                shortfall = _shortfall(response, pdf_path)
            if response.success and response.parsed_json and not shortfall:
                result = response.parsed_json
                result["_provider_used"] = response.provider
                result["_model_used"] = response.model
                print(f"  [Engine] {provider_label} success — "
                      f"{len(result.get('invoices', []))} invoices extracted")
                return result
            if shortfall:
                answers.append((response, shortfall))
            else:
                print(f"  [Engine] {provider_label} failed: {response.error}")
        except Exception as e:
            print(f"  [Engine] {provider_label} error: {e}")

        if answers:
            # Both AI answers fell short: the deterministic reader for this layout first, if there is one.
            best = max(answers, key=lambda a: len((a[0].parsed_json or {}).get("invoices") or []) if a[0].success else -1)
            best_rows = len((best[0].parsed_json or {}).get("invoices") or []) if best[0].success else 0
            reader = _deterministic_reader(pdf_path)
            if reader is not None and len(reader.get("invoices") or []) > best_rows:
                print(f"  [Engine] Using the deterministic reader for this layout "
                      f"({reader.get('_deterministic_reader')}): {len(reader['invoices'])} rows")
                reader.setdefault("warnings", []).append(
                    f"AI answers fell short twice ({best[1]}); read by {reader.get('_deterministic_reader')}")
                return reader
            if best_rows:
                result = best[0].parsed_json
                result["_provider_used"] = best[0].provider
                result["_model_used"] = best[0].model
                result.setdefault("warnings", []).append(
                    f"The AI returned {best_rows} rows twice; {best[1]}. Kept the AI rows; validation decides.")
                print(f"  [Engine] Keeping the better AI answer ({best_rows} rows)")
                return result
            print(f"  [Engine] {provider_label}: no rows on both attempts and no deterministic reader for this layout")

        # --- FALLBACK PATH: deterministic pdfplumber (no AI, no cost) ---
        # extract_with_pdfplumber() handles scanned pages internally via
        # per-page OCR — no OCR-vs-text branching needed here.
        print(f"  [Engine] Falling back to pdfplumber (deterministic)...")
        result = extract_with_pdfplumber(pdf_path)
        result["_provider_used"] = "pdfplumber"
        return result


# The provider name each client puts on its own AIResponse.
_PROVIDER_NAMES = {"ClaudeSonnetClient": "claude_sonnet", "ClaudeClient": "claude"}


def _log_call_exception(client, error: Exception, seconds: float, source_file: str, statement_id: str) -> None:
    """ai_audit_log row for an AI call that raised instead of returning a
    response (2026-10-25): until now only a returned response was logged, so
    on dev Receipts 47 2 fell back to pdfplumber with no audit row at all and
    no trace of why. Logged as a failed call -- success 0, the exception as
    error_message ("<type>: <message>"), validation_result "ERROR" (a returned
    failure stays "FAILED"). Never raises."""
    try:
        name = type(client).__name__
        log_ai_call(
            AIResponse(success=False, provider=_PROVIDER_NAMES.get(name, name), model=getattr(client, "model", "") or "",
                       latency_ms=seconds * 1000, error=f"{type(error).__name__}: {error}"[:4000]),
            interaction_type="DOCUMENT_UNDERSTANDING",
            prompt_version="vision_v1",
            source_file=source_file,
            statement_id=statement_id,
            validation_result="ERROR",
        )
    except Exception as e:
        print(f"  [Engine] ai_audit_log row not written ({type(e).__name__}: {e})")


# An AI answer that falls short (2026-10-26): no rows, or far fewer than the PDF's own text layer prints.
NO_ROWS_ERROR = "appears truncated"           # ClaudeSonnetClient: column names but an empty rows list
TEXT_ROW_SHORTFALL = 0.5                      # fewer than half the printed dated lines with an amount ...
MIN_TEXT_ROWS = 5                             # ... on a text layer printing at least this many
_DATE_RE = None
_AMOUNT_RE = None


def _text_layer_rows(pdf_path: str):
    """How many text-layer lines print a date and an amount (a rough count of transaction lines), or
    None for a scan / an unreadable file. Uses the text extract_pdf_text() already read when it can."""
    import re
    global _DATE_RE, _AMOUNT_RE
    if _DATE_RE is None:
        _DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[A-Z]{3}\d{2,4})\b")
        _AMOUNT_RE = re.compile(r"(?<![\d.])-?\$?\d{1,3}(?:,\d{3})*\.\d{2}\b")
    texts = page_texts(pdf_path)
    if texts is None:
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                texts = [page.extract_text() or "" for page in pdf.pages]
        except Exception:
            return None
    lines = [line for text in texts for line in (text or "").splitlines()]
    if sum(len(line) for line in lines) < 200:
        return None
    return sum(1 for line in lines if _DATE_RE.search(line) and _AMOUNT_RE.search(line))


def _shortfall(response, pdf_path: str):
    """Why an AI answer falls short, or None: column names but no rows (the client's "truncated"), a
    statement answered with no rows, or far fewer rows than its text layer prints. A document the
    model judged not a statement never falls short."""
    if not response.success:
        return "the AI returned column names but no rows" if NO_ROWS_ERROR in (response.error or "") else None
    parsed = response.parsed_json or {}
    if (parsed.get("document_metadata") or {}).get("document_type") == "NOT_A_STATEMENT":
        return None
    rows = len(parsed.get("invoices") or [])
    if not rows:
        return "the AI returned no rows"
    printed = _text_layer_rows(pdf_path)
    if printed is not None and printed >= MIN_TEXT_ROWS and rows < TEXT_ROW_SHORTFALL * printed:
        return f"the AI returned {rows} rows; the text layer prints {printed} dated lines with an amount"
    return None


def _deterministic_reader(pdf_path: str):
    """The python_library extractor for this PDF's layout (src/extraction/python_library, matched by its
    vendor signature -- extract_ef320, extract_fenix, ...) as an engine result, or None when no
    extractor matches, it has no field mapping, or it reads no rows. Never raises."""
    try:
        from src.extraction.python_library import adapter
        module = adapter.extract_all.detect_vendor(pdf_path)
        if module.__name__ not in adapter._FIELD_MAP:
            return None
        result = adapter.PythonLibraryExtractionEngine().understand("", pdf_path)
    except Exception as e:
        print(f"  [Engine] No deterministic reader for this layout ({type(e).__name__})")
        return None
    if not (result or {}).get("invoices"):
        return None
    result["_provider_used"] = "python_library"
    result["_deterministic_reader"] = module.__name__
    return result


def extract_pdf_text(pdf_path: str):
    """
    Extract raw text from all pages of a PDF using pdfplumber.
    Returns (text, page_count).

    Still used by notebooks/01_document_intake.py for its own char/page-count
    logging, ahead of calling DocumentUnderstandingEngine.understand().

    Raises CorruptedPDFError (not the raw pdfminer/pdfplumber exception) if
    the file can't be opened as a PDF at all — see that class's docstring.

    Each page's text is kept for page_texts() (the last file read only).
    """
    import pdfplumber
    from pdfplumber.utils.exceptions import PdfminerException
    from pdfminer.pdfparser import PDFSyntaxError

    pages_text = []
    raw_texts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                raw_texts.append(text)
                pages_text.append(f"--- PAGE {i} ---\n{text}")
    except (PdfminerException, PDFSyntaxError):
        raise CorruptedPDFError(
            "File is not a valid PDF or is corrupted — could not be opened"
        ) from None

    _PAGE_TEXTS.clear()
    try:
        _PAGE_TEXTS[_file_key(pdf_path)] = raw_texts
    except OSError:
        pass
    return "\n\n".join(pages_text), page_count


# Each page's text from the last extract_pdf_text() call (2026-10-25): the
# intake's routing step (_classify_pdf) reads exactly the same text right
# after Step 2, and parsing the PDF a second time was 44 of the 106 seconds
# Fred Beans Lamon spent before its AI call (on dev, an estimated 7-23 min).
_PAGE_TEXTS = {}


def _file_key(pdf_path: str) -> tuple:
    st = os.stat(pdf_path)
    return os.path.abspath(pdf_path), st.st_mtime, st.st_size


def page_texts(pdf_path: str):
    """Each page's text (page.extract_text() or "") as extract_pdf_text()
    read this same file (same path, modification time and size), or None."""
    try:
        return _PAGE_TEXTS.get(_file_key(pdf_path))
    except OSError:
        return None
