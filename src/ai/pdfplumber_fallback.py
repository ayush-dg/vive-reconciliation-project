"""
pdfplumber_fallback.py

Last-resort extraction when all AI providers fail.
No API needed. Works offline.

Handles both text-based PDFs (via pdfplumber's geometry-based table
extraction) and scanned/image-based pages (via Tesseract OCR, page-by-page,
only for pages where pdfplumber finds no usable text layer). OCR-derived
rows get a lower line_confidence (0.50 vs. 0.65) since column boundaries are
inferred from whitespace in flat OCR text rather than real geometry — by
design, this keeps OCR rows below the 0.60 validation threshold so they
always route to human review rather than silently auto-passing.

Limitations:
- Clean tabular PDFs (text or scanned) work well; highly irregular layouts
  with no consistent column structure at all still won't parse cleanly, OCR or not
- Cannot classify document type reliably (defaults to VENDOR_STATEMENT with low confidence)
- Cannot infer vendor name from complex layouts
- Does NOT return an AIResponse — returns the same Universal Schema dict shape

Use only when the primary AI provider has failed.
"""

import re
from datetime import datetime
from typing import Optional

# Mirrors the same threshold value previously used in
# document_understanding_engine.py's FALLBACK_TEXT_THRESHOLD to decide
# "is there a real text layer on this page" — reused here per-page (not
# per-document) to decide whether a page is scanned and worth OCR'ing.
OCR_TRIGGER_TEXT_THRESHOLD = 500


def extract_with_pdfplumber(pdf_path: str) -> dict:
    """
    Attempt to extract invoice data from a PDF using only pdfplumber.
    Returns a dict matching the Universal Financial Document Schema shape.
    """
    try:
        import pdfplumber
    except ImportError:
        return _failed_schema(pdf_path, "pdfplumber not installed")

    # Checked once per call, not per page — is_ocr_available() invokes the
    # Tesseract binary, so avoid repeating that for every scanned page.
    try:
        from src.ai.ocr_extractor import is_ocr_available, ocr_page as ocr_page_fn
        ocr_available = is_ocr_available()
    except Exception:
        ocr_available = False

    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            all_invoices = []
            warnings = []
            vendor_name = None
            shop_name = None
            ocr_pages_used = []

            for page_num, page in enumerate(pdf.pages, start=1):
                # Try to get header text (first 200 chars) to find vendor/shop
                page_text = page.extract_text() or ""
                if page_num == 1:
                    vendor_name, shop_name = _extract_header_info(page_text)

                # Try table extraction
                table = page.extract_table()
                if not table or len(table) < 2:
                    # A sparse text layer means this page is likely a scanned
                    # image — worth trying OCR. A page with substantial text
                    # but no clean table is a genuinely non-tabular layout;
                    # OCR wouldn't help there, so keep the old behavior.
                    if len(page_text.strip()) < OCR_TRIGGER_TEXT_THRESHOLD:
                        ocr_table, ocr_warning = _try_ocr_page(
                            pdf_path, page_num, ocr_available, ocr_page_fn
                        )
                        if ocr_table is not None:
                            table = ocr_table
                            ocr_pages_used.append(page_num)
                        else:
                            warnings.append(ocr_warning)
                            continue
                    else:
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
                        "message": f"Page {page_num}: could not identify column headers"
                                   + (" (OCR text)" if page_num in ocr_pages_used else ""),
                        "severity": "HIGH"
                    })
                    continue

                # Map column names to indices
                col_map = _map_columns(header_row)

                # OCR-derived rows get a lower confidence — column boundaries
                # are inferred from whitespace in flat text, not real geometry.
                # See RULES.md RULE-10 — 0.50 is deliberately below the 0.60
                # validation threshold, so OCR rows always route to human
                # review. Do not raise this without revisiting that rule.
                row_confidence = 0.50 if page_num in ocr_pages_used else 0.65

                # Extract invoice rows
                for row_num, row in enumerate(table[data_start:], start=1):
                    invoice = _extract_invoice_row(
                        row, col_map, page_num, row_num, shop_name,
                        confidence=row_confidence,
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
            "_ocr_pages_used": ocr_pages_used,
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


# A standalone "ref"/"reference" word (e.g. "Txn Ref", "Reference #") is as
# valid an invoice-identifier header as "Invoice #" -- claude_sonnet_client.py's
# own fallback column mapping already treats "reference" as a synonym
# (INVOICE_NUMBER_KEYWORDS); this deterministic fallback didn't, which left
# it unable to recognize a real, plausible header wording. Matched as a
# whole word (not a bare substring) so it doesn't fire on unrelated words
# like "preferred", and excluded whenever "date" is also present so a
# "Reference Date" column still falls through to the date branch below
# instead of being misread as the invoice identifier.
_REF_WORD_RE = re.compile(r"\bref\b")


def _map_columns(header_row):
    """Map column header strings to their indices.

    See RULES.md RULE-07 — this generic keyword-based mapping is what lets
    any vendor's PDF work without per-vendor configuration; don't replace
    it with a per-vendor lookup table.
    """
    col_map = {}
    for i, cell in enumerate(header_row):
        if not cell:
            continue
        cell_lower = str(cell).lower().strip()

        is_invoice_number_header = "date" not in cell_lower and (
            any(kw in cell_lower for kw in
                ["invoice #", "invoice no", "invoice number", "inv #", "inv no", "reference"])
            or _REF_WORD_RE.search(cell_lower)
        )
        if is_invoice_number_header:
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
        elif any(kw in cell_lower for kw in ["work order", "wo #", "wo no"]):
            col_map["work_order_number"] = i
        elif "description" in cell_lower or "desc" in cell_lower:
            col_map["description"] = i

    return col_map


def _extract_invoice_row(row, col_map, page_num, row_num, default_shop, confidence=0.65):
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
        "work_order_number": get("work_order_number"),
        "description": get("description"),
        "credit": None,
        "shop": default_shop,
        "page_number": page_num,
        "row_number": row_num,
        "line_confidence": confidence,
    }


def _try_ocr_page(pdf_path, page_num, ocr_available, ocr_page_fn):
    """
    Attempt to OCR a single scanned page and convert its text into a
    pseudo-table (a list of rows, each split into cell strings) that
    _find_header_row / _map_columns / _extract_invoice_row can parse exactly
    like a real pdfplumber table.

    Returns (pseudo_table, None) on success, or (None, warning_dict) if OCR
    isn't available, fails, or produces nothing parsable — the caller treats
    this exactly like any other "page skipped" case.
    """
    if not ocr_available:
        return None, {
            "code": "OTHER",
            "message": f"Page {page_num}: looks scanned but OCR is unavailable "
                       f"(Tesseract/Poppler not installed or not reachable) — page skipped",
            "severity": "MEDIUM",
        }

    try:
        ocr_text = ocr_page_fn(pdf_path, page_num)
    except Exception as e:
        return None, {
            "code": "OTHER",
            "message": f"Page {page_num}: OCR failed — {e}",
            "severity": "MEDIUM",
        }

    if len(ocr_text.strip()) < OCR_TRIGGER_TEXT_THRESHOLD:
        return None, {
            "code": "UNSUPPORTED_LAYOUT",
            "message": f"Page {page_num}: OCR ran but produced too little text to parse",
            "severity": "MEDIUM",
        }

    pseudo_table = _ocr_text_to_pseudo_table(ocr_text)
    if len(pseudo_table) < 2:
        return None, {
            "code": "AMBIGUOUS_COLUMN",
            "message": f"Page {page_num}: OCR text had no detectable column structure",
            "severity": "HIGH",
        }

    return pseudo_table, None


def _ocr_text_to_pseudo_table(ocr_text: str) -> list:
    """
    Turn flat OCR text into a table-like list of rows (each row a list of
    cell strings) so it can be fed through the same header-detection /
    column-mapping / row-extraction logic used for pdfplumber's real
    (geometry-based) tables.

    Splits each non-blank line on runs of 2+ whitespace characters — a
    standard heuristic for column-aligned text from Tesseract's --psm 6
    mode, when the source table had wide enough visual gaps between columns
    for that spacing to survive OCR. Some documents' OCR output collapses
    those gaps down to a single space instead (columns still line up
    visually in the scanned image, but Tesseract's text output doesn't
    preserve the extra whitespace) — when that leaves an entire line
    un-split (one cell), fall back to splitting on any whitespace run for
    that line specifically. Scoped to exactly that degenerate case so a
    real multi-word value a 2+-space split correctly kept together (e.g. a
    free-text description) isn't shredded into one cell per word on a
    document where 2+-space splitting is already working.

    Best-effort: less reliable than geometry-based extraction, which is why
    OCR-derived rows get a lower line_confidence (see extract_with_pdfplumber).
    """
    rows = []
    for line in ocr_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        cells = re.split(r'\s{2,}', line)
        if len(cells) == 1 and len(cells[0].split()) > 1:
            cells = cells[0].split()
        rows.append(cells)
    return rows


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
