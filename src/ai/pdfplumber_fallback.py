"""
pdfplumber_fallback.py

Last-resort extraction when all AI providers fail.
No API needed. Works offline.

Limitations:
- Only works for clean tabular PDFs with detectable column headers
- Cannot classify document type reliably (defaults to VENDOR_STATEMENT with low confidence)
- Cannot infer vendor name from complex layouts
- Does NOT return an AIResponse — returns the same Universal Schema dict shape

Use only when Gemini AND Groq have both failed.
"""

import re
from datetime import datetime
from typing import Optional


def extract_with_pdfplumber(pdf_path: str) -> dict:
    """
    Attempt to extract invoice data from a PDF using only pdfplumber.
    Returns a dict matching the Universal Financial Document Schema shape.
    """
    try:
        import pdfplumber
    except ImportError:
        return _failed_schema(pdf_path, "pdfplumber not installed")

    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            all_invoices = []
            warnings = []
            vendor_name = None
            shop_name = None

            for page_num, page in enumerate(pdf.pages, start=1):
                # Try to get header text (first 200 chars) to find vendor/shop
                page_text = page.extract_text() or ""
                if page_num == 1:
                    vendor_name, shop_name = _extract_header_info(page_text)

                # Try table extraction
                table = page.extract_table()
                if not table or len(table) < 2:
                    # No table found — try word-based extraction
                    warnings.append({
                        "code": "UNSUPPORTED_LAYOUT",
                        "message": f"Page {page_num}: no detectable table structure",
                        "severity": "MEDIUM"
                    })
                    continue

                # Find the header row
                header_row, data_start = _find_header_row(table)
                if not header_row:
                    warnings.append({
                        "code": "AMBIGUOUS_COLUMN",
                        "message": f"Page {page_num}: could not identify column headers",
                        "severity": "HIGH"
                    })
                    continue

                # Map column names to indices
                col_map = _map_columns(header_row)

                # Extract invoice rows
                for row_num, row in enumerate(table[data_start:], start=1):
                    invoice = _extract_invoice_row(
                        row, col_map, page_num, row_num, shop_name
                    )
                    if invoice:
                        all_invoices.append(invoice)

        # Build the Universal Schema response
        statement_total = sum(
            inv.get("outstanding_amount", 0) or 0
            for inv in all_invoices
            if inv.get("outstanding_amount") is not None
        )

        confidence = 0.65 if all_invoices else 0.20  # honest about uncertainty

        return {
            "document_metadata": {
                "document_type": "VENDOR_STATEMENT",
                "source_file": pdf_path,
                "page_count": page_count,
                "document_type_confidence": 0.60,  # low — we're guessing
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
                "currency": "USD",  # assume USD
                "statement_total_as_printed": statement_total if all_invoices else None,
                "statement_confidence": 0.50,
            },
            "invoices": all_invoices,
            "extraction_confidence": {
                "overall": confidence,
                "table_detection_confidence": 0.75 if all_invoices else 0.20,
                "column_mapping_confidence": 0.60 if all_invoices else 0.10,
            },
            "warnings": warnings,
            "_extraction_method": "pdfplumber_fallback",
        }

    except Exception as e:
        return _failed_schema(pdf_path, str(e))


def _extract_header_info(text: str):
    """Try to find vendor name and shop name from page header text."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    vendor_name = lines[0] if lines else None

    shop_name = None
    for line in lines:
        if any(kw in line.lower() for kw in ["vive", "collision", "auto body", "shop"]):
            shop_name = line
            break

    return vendor_name, shop_name


def _find_header_row(table):
    """Find the row that contains column headers."""
    header_keywords = [
        "invoice", "amount", "date", "balance", "due", "outstanding",
        "ro", "po", "ref", "description", "charges"
    ]
    for i, row in enumerate(table):
        if not row:
            continue
        row_text = " ".join(str(cell or "").lower() for cell in row)
        matches = sum(1 for kw in header_keywords if kw in row_text)
        if matches >= 2:
            return row, i + 1
    return None, 1


def _map_columns(header_row):
    """Map column header strings to their indices."""
    col_map = {}
    for i, cell in enumerate(header_row):
        if not cell:
            continue
        cell_lower = str(cell).lower().strip()

        if any(kw in cell_lower for kw in ["invoice #", "invoice no", "invoice number", "inv #", "inv no"]):
            col_map["invoice_number"] = i
        elif "invoice" in cell_lower and "date" in cell_lower:
            col_map["invoice_date"] = i
        elif "due" in cell_lower and "date" in cell_lower:
            col_map["due_date"] = i
        elif any(kw in cell_lower for kw in ["outstanding", "balance", "amount due", "remaining"]):
            col_map["outstanding_amount"] = i
        elif "amount" in cell_lower or "charges" in cell_lower:
            col_map.setdefault("amount", i)
        elif any(kw in cell_lower for kw in ["ro #", "ro no", "repair order"]):
            col_map["ro_number"] = i
        elif any(kw in cell_lower for kw in ["po #", "po no", "purchase order"]):
            col_map["po_number"] = i
        elif "description" in cell_lower or "desc" in cell_lower:
            col_map["description"] = i

    return col_map


def _extract_invoice_row(row, col_map, page_num, row_num, default_shop):
    """Extract a single invoice line from a table row."""
    def get(key):
        idx = col_map.get(key)
        if idx is not None and idx < len(row):
            val = row[idx]
            return str(val).strip() if val else None
        return None

    invoice_number = get("invoice_number")
    outstanding_raw = get("outstanding_amount")

    # Skip rows with no invoice number and no amount
    if not invoice_number and not outstanding_raw:
        return None

    # Skip obvious total/header rows
    if invoice_number and any(
        kw in invoice_number.lower() for kw in ["total", "balance", "subtotal"]
    ):
        return None

    outstanding = _parse_amount(outstanding_raw)
    amount = _parse_amount(get("amount")) or outstanding

    return {
        "invoice_number": invoice_number,
        "invoice_date": get("invoice_date"),
        "due_date": get("due_date"),
        "amount": amount,
        "outstanding_amount": outstanding,
        "ro_number": get("ro_number"),
        "po_number": get("po_number"),
        "work_order_number": None,
        "description": get("description"),
        "credit": None,
        "shop": default_shop,
        "page_number": page_num,
        "row_number": row_num,
        "line_confidence": 0.65,
    }


def _parse_amount(value):
    """Parse a string like '$1,234.56' or '(123.45)' into a float."""
    if not value:
        return None
    try:
        cleaned = re.sub(r'[^\d.\-]', '', str(value).replace(',', ''))
        if cleaned:
            return float(cleaned)
    except (ValueError, TypeError):
        pass
    return None


def _failed_schema(pdf_path: str, error: str) -> dict:
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
        "warnings": [{"code": "OTHER", "message": f"pdfplumber extraction failed: {error}", "severity": "HIGH"}],
        "_extraction_method": "pdfplumber_fallback",
        "_error": error,
    }
