#!/usr/bin/env python3
"""Session 8, Task 8.3 — deterministic pdfplumber table extraction with a
per-page OCR fallback for scanned pages. Reused/adapted from the reference
implementation's src/ai/pdfplumber_fallback.py + src/ai/ocr_extractor.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable), with two real
adaptations rather than a verbatim port:

1. Output shape matches THIS project's ExtractedStatement contract
   (vendor_name_guess/statement_period/statement_total/lines[] with
   invoice_ref/ro_number/amount/date) instead of the reference's Universal
   Financial Document Schema — the extra fields that schema carries
   (outstanding_amount vs. amount, due_date, po_number, work_order_number,
   description, credit, shop, per-field confidence) have no column in this
   project's silver.statement_line and are dropped, not renamed.
2. Never calls any AI provider — this project's Claude call lives in
   aiProvider.ts (TypeScript), not Python (unlike the reference repo, which
   orchestrates its own AI call from this same Python layer). This script is
   invoked only as extractionPipeline.ts's Task 8.2 fallback, after a Claude
   attempt has already genuinely failed — never tried first.

Invoked exactly like scripts/pdfplumber_extract.py: `<script> <pdf_path>`,
one JSON object on stdout, non-zero exit + {"error": ...} on failure — same
I/O contract, so pdfplumberExtractor.ts's subprocess-spawning code didn't
need to change shape, only which script it points at for this path.

OCR is gracefully skipped (not a hard failure) when pytesseract/pdf2image
aren't installed or the Tesseract/Poppler binaries aren't reachable on
PATH — same behavior as the reference's is_ocr_available() check. Confirmed
2026-09-01: this local dev environment has the Python packages
(pytesseract, pdf2image) but not the Tesseract/Poppler binaries themselves —
OCR is inert here until those are installed; plain table extraction (no OCR)
still works today. Per EXECUTION_PLAN.md Task 8.3's own note, Tesseract's
availability on the actual Azure App Service deployment target still needs
confirming before this OCR path can be relied on in production — flagged as
a Scope Decision, not silently assumed.
"""
import json
import platform
import re
import shutil
import sys

OCR_TRIGGER_TEXT_THRESHOLD = 500


def _configure_tesseract_path(pytesseract) -> None:
    if platform.system() != "Windows":
        return
    tess_path = shutil.which("tesseract")
    if not tess_path:
        import os
        default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(default_path):
            tess_path = default_path
    if tess_path:
        pytesseract.pytesseract.tesseract_cmd = tess_path


def _is_ocr_available() -> bool:
    try:
        import pytesseract
        import pdf2image  # noqa: F401
        _configure_tesseract_path(pytesseract)
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_page(pdf_path: str, page_num: int, dpi: int = 200) -> str:
    import pytesseract
    from pdf2image import convert_from_path

    _configure_tesseract_path(pytesseract)
    images = convert_from_path(pdf_path, dpi=dpi, first_page=page_num, last_page=page_num)
    if not images:
        return ""
    return pytesseract.image_to_string(images[0], config="--psm 6")


def _extract_header_info(text: str):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    vendor_name = lines[0] if lines else None
    return vendor_name


def _find_header_row(table):
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


_REF_WORD_RE = re.compile(r"\bref\b")


def _map_columns(header_row):
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
        elif any(kw in cell_lower for kw in ["outstanding", "balance", "amount due", "remaining"]):
            col_map["outstanding_amount"] = i
        elif "amount" in cell_lower or "charges" in cell_lower:
            col_map.setdefault("amount", i)
        elif any(kw in cell_lower for kw in ["ro #", "ro no", "repair order"]):
            col_map["ro_number"] = i
    return col_map


def _parse_amount(value):
    if not value:
        return None
    try:
        cleaned = re.sub(r"[^\d.\-]", "", str(value).replace(",", ""))
        if cleaned:
            return float(cleaned)
    except (ValueError, TypeError):
        pass
    return None


def _extract_line(row, col_map):
    def get(key):
        idx = col_map.get(key)
        if idx is not None and idx < len(row):
            val = row[idx]
            return str(val).strip() if val else None
        return None

    invoice_ref = get("invoice_number")
    outstanding_raw = get("outstanding_amount")
    if not invoice_ref and not outstanding_raw:
        return None
    if invoice_ref and any(kw in invoice_ref.lower() for kw in ["total", "balance", "subtotal"]):
        return None

    outstanding = _parse_amount(outstanding_raw)
    amount = _parse_amount(get("amount"))
    if amount is None:
        amount = outstanding

    return {
        "invoice_ref": invoice_ref,
        "ro_number": get("ro_number"),
        "amount": amount,
        "date": get("invoice_date"),
    }


def _ocr_text_to_pseudo_table(ocr_text: str) -> list:
    rows = []
    for line in ocr_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        cells = re.split(r"\s{2,}", line)
        if len(cells) == 1 and len(cells[0].split()) > 1:
            cells = cells[0].split()
        rows.append(cells)
    return rows


def _try_ocr_page(pdf_path, page_num, ocr_available):
    if not ocr_available:
        return None, "Tesseract/Poppler not installed or not reachable — page skipped"
    try:
        ocr_text = _ocr_page(pdf_path, page_num)
    except Exception as exc:
        return None, f"OCR failed — {exc}"
    if len(ocr_text.strip()) < OCR_TRIGGER_TEXT_THRESHOLD:
        return None, "OCR ran but produced too little text to parse"
    pseudo_table = _ocr_text_to_pseudo_table(ocr_text)
    if len(pseudo_table) < 2:
        return None, "OCR text had no detectable column structure"
    return pseudo_table, None


def extract(pdf_path: str) -> dict:
    import pdfplumber

    ocr_available = _is_ocr_available()
    vendor_name_guess = None
    lines = []
    warnings = []
    ocr_pages_used = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            if page_num == 1:
                vendor_name_guess = _extract_header_info(page_text)

            table = page.extract_table()
            if not table or len(table) < 2:
                if len(page_text.strip()) < OCR_TRIGGER_TEXT_THRESHOLD:
                    ocr_table, warning = _try_ocr_page(pdf_path, page_num, ocr_available)
                    if ocr_table is not None:
                        table = ocr_table
                        ocr_pages_used.append(page_num)
                    else:
                        warnings.append(f"Page {page_num}: {warning}")
                        continue
                else:
                    warnings.append(f"Page {page_num}: no detectable table structure")
                    continue

            header_row, data_start = _find_header_row(table)
            if not header_row:
                warnings.append(f"Page {page_num}: could not identify column headers")
                continue

            col_map = _map_columns(header_row)
            for row in table[data_start:]:
                line = _extract_line(row, col_map)
                if line:
                    lines.append(line)

    statement_total = sum(l["amount"] for l in lines if l["amount"] is not None) or None

    return {
        "vendor_name_guess": vendor_name_guess,
        "statement_period": None,  # not recoverable without per-vendor layout knowledge
        "statement_total": statement_total,
        "lines": lines,
        "warnings": warnings,
        "ocr_pages_used": ocr_pages_used,
        "ocr_available": ocr_available,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: pdfplumber_ocr_fallback.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        print(json.dumps(extract(pdf_path)))
        return 0
    except Exception as exc:  # noqa: BLE001 — see pdfplumber_extract.py's own note
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
