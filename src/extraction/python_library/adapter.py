"""
adapter.py

Bridges the copied Python-library PDF extractors (extract_all.py's vendor
dispatch, in this same folder) into the Universal Financial Document
Schema shape notebooks/01_document_intake.py expects from
src.ai.document_understanding_engine.DocumentUnderstandingEngine.understand().

Used ONLY for Fred Beans Parts statements -- see
notebooks/01_document_intake.py's _is_fred_beans_statement() gate, which
routes every other vendor to DocumentUnderstandingEngine (Claude Sonnet)
exactly as before. src/ai/document_understanding_engine.py and
src/ai/claude_sonnet_client.py are untouched -- this class is a drop-in
substitute with the same understand(pdf_text, pdf_path, statement_id=None)
signature, called only for the one vendor this toolkit has a real,
verified extractor for (extract_statement.py). Every other extract_*.py
module in this folder is retained from the original toolkit for reference
and potential future per-vendor rollout, but is not wired into the
production pipeline yet -- extract_all.py's detect_vendor() dispatch
would raise UnknownVendorError for a document none of them recognize.
"""

import os
import re
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import extract_all  # noqa: E402 (needs _THIS_DIR on sys.path first)

_MONTH = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}
_DATE_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})$")


def _normalize_date(raw):
    """'23DEC25' -> '2025-12-23'. Returns the raw string unchanged if it
    doesn't match the expected DDMonYY shape -- never guesses."""
    if not raw:
        return None
    m = _DATE_RE.match(raw)
    if not m:
        return raw
    day, mon, yy = m.groups()
    month = _MONTH.get(mon)
    if not month:
        return raw
    return f"20{yy}-{month}-{day}"


def _parse_money(raw):
    """'14,681.56' -> 14681.56, '100.00-' -> -100.00, '' -> None."""
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip()
    negative = s.endswith("-")
    if negative:
        s = s[:-1]
    s = s.replace(",", "")
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


class PythonLibraryExtractionEngine:
    """Drop-in substitute for DocumentUnderstandingEngine -- same
    understand(pdf_text, pdf_path, statement_id=None) signature. Ignores
    pdf_text (kept for call-site compatibility, matching the AI engine's
    own convention) and runs the copied pdfplumber-based vendor extractors
    directly against pdf_path instead of calling any AI provider."""

    def understand(self, pdf_text: str, pdf_path: str, statement_id: str = None) -> dict:
        module = extract_all.detect_vendor(pdf_path)
        kwargs = {"output_dir": "."} if module is extract_all.extract_ksi else {}
        result = module.extract(pdf_path, **kwargs)

        line_items = result["line_items"]
        invoices = []

        for row_num, item in enumerate(line_items, start=1):
            charges = _parse_money(item.get("charges"))
            credits = _parse_money(item.get("credits"))
            amount_due = _parse_money(item.get("amount_due"))

            # Ground-truth rule (confirmed by the engineer): Charges is the
            # only field that can ever populate the amount/outstanding_amount
            # matching role. A row with only Credits/Amount Due populated
            # (e.g. a credit memo, or a running-balance line) correctly
            # leaves this blank -- notebooks/01_document_intake.py's existing
            # INV-04 gate then routes it to gold_exceptions
            # (EXTRACTION_INCOMPLETE) instead of Silver, same as any other
            # vendor's missing-amount row. Never fall back to credits/
            # amount_due here -- that would silently misrepresent a credit or
            # a running balance as a chargeable amount.
            outstanding = charges

            invoice_number = item.get("invoice_number") or item.get("remit_invoice_no")

            invoices.append({
                "invoice_number": invoice_number,
                "invoice_date": _normalize_date(item.get("date")),
                "due_date": None,
                "amount": outstanding,
                "outstanding_amount": outstanding,
                "ro_number": None,
                "po_number": None,
                "work_order_number": None,
                "description": None,
                "credit": credits,
                "shop": None,
                "page_number": item.get("page"),
                "row_number": row_num,
                "line_confidence": 1.0,
                # New pass-through columns (migrations/010_add_python_extraction_columns.sql)
                # -- carried by write_to_bronze()/normalize_to_silver()/the
                # matching engine in addition to the fields above, never
                # instead of them.
                "charges": charges,
                "credits": credits,
                "amount_due": amount_due,
                "transaction_code": item.get("transaction_code"),
            })

        summary = result.get("summary", {})

        # This vendor's true printed name, matching this extractor's own
        # VENDOR_SIGNATURE and config/vendor_aliases.json's "FRED_BEANS_PARTS"
        # entry -- 01_document_intake.py's resolve_vendor_id() maps it to
        # vendor_id "FRED_BEANS_PARTS", the same id
        # scripts/load_voucher_data.py loads this vendor's real voucher
        # ERP data under (statement_id "VOUCHER-FRED_BEANS_PARTS"), so
        # matching has real data to run against.
        vendor_name = "Fred Beans Parts"

        statement_date = _normalize_date(summary.get("statement_date"))

        return {
            "document_metadata": {
                "document_type": "VENDOR_STATEMENT",
                "source_file": os.path.basename(pdf_path),
                "page_count": max((li.get("page") or 1) for li in line_items) if line_items else 1,
                "document_type_confidence": 1.0,
            },
            "vendor_metadata": {
                "vendor_name": vendor_name,
                "vendor_address": None,
                "shop_or_entity": [summary["customer_name"]] if summary.get("customer_name") else [],
                "vendor_confidence": 1.0,
            },
            "statement_metadata": {
                "statement_date": statement_date,
                "statement_period_start": None,
                "statement_period_end": statement_date,
                "currency": "USD",
                "statement_total_as_printed": _parse_money(summary.get("balance_due")),
                "statement_confidence": 1.0,
            },
            "invoices": invoices,
            "extraction_confidence": {
                "overall": 1.0,
                "table_detection_confidence": 1.0,
                "column_mapping_confidence": 1.0,
            },
            "warnings": [],
            "_provider_used": "python_library_pdfplumber",
            "_model_used": module.__name__,
        }
