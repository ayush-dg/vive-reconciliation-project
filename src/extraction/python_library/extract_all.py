"""
Single entry point for extracting any of the known vendor statement PDFs.

Usage:
    python extract_all.py "file1.pdf" "file2.pdf" ...

For each PDF, this:
  1. Detects whether it's a scanned image or has real embedded text
     (pdfplumber probe: near-zero extractable text + a full-page image
     means scanned).
  2. Identifies the vendor by matching known signature text on the first
     readable page (OCR'd first if scanned) against each extractor
     module's VENDOR_SIGNATURE.
  3. Dispatches to that vendor's extract(pdf_path) function - each module
     encodes the column layout / parsing quirks worked out for that
     vendor's statement format (see each module's docstring for how and
     why). There is no generic column-position auto-detector: layouts
     differ too much (ruled tables vs none, wrapped headers, OCR'd scans)
     for one heuristic to safely cover all of them - see extract_all.py's
     git history / conversation for why a generic pdfplumber "text"
     table-strategy pass was tried and rejected.
  4. Writes "<pdf stem> - line items.csv" and "<pdf stem> - summary.csv"
     next to the input PDF (plus "<pdf stem> - full text.txt" for vendors
     that produce one, i.e. the OCR'd ones).

An unrecognized vendor is reported clearly rather than guessed at - see
UnknownVendorError below.
"""

import csv
import os
import sys

import pdfplumber

import extract_statement   # Fred Beans Parts
import extract_ksi         # KSI Trading Corp (scanned, OCR pipeline)
import extract_astech      # asTech / Repairify
import extract_empire      # Empire Auto Parts
import extract_wilberts    # Wilbert's Inc.
import extract_quirk       # Quirk Auto Group
import extract_nimey       # Matt Nimey GMC
import extract_lia         # Lia Auto Group
import extract_keystone    # Keystone Automotive Industries
import extract_precision   # Precision Diagnostics
import extract_adas        # Adas Calibration Experts

EXTRACTORS = [
    extract_statement,
    extract_ksi,
    extract_astech,
    extract_empire,
    extract_wilberts,
    extract_quirk,
    extract_nimey,
    extract_lia,
    extract_keystone,
    extract_precision,
    extract_adas,
]


class UnknownVendorError(Exception):
    pass


def probe_first_page_text(pdf_path):
    """Best-effort text for vendor detection. OCRs page 1 if the PDF has no
    embedded text at all (scanned), since vendor signatures live in the
    printed letterhead, not in any table this early detection pass parses."""
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ""
        if len(text.strip()) >= 20:
            return text

    # Scanned: OCR just page 1 far cheaper than running the full pipeline
    # blind, and we only need enough text to match a vendor signature.
    from ocr_embed import _page_to_pil_image, OCR_UPSCALE, OCR_PSM, TESSERACT_CMD
    import fitz
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    doc = fitz.open(pdf_path)
    page_img = _page_to_pil_image(doc[0], zoom=2.0).convert("L")
    w, h = page_img.size
    page_img = page_img.resize((int(w * OCR_UPSCALE), int(h * OCR_UPSCALE)), Image.LANCZOS)
    text = pytesseract.image_to_string(page_img, config=f"--psm {OCR_PSM}")
    doc.close()
    return text


def probe_all_pages_text(pdf_path):
    """Fallback for when the vendor name doesn't appear on page 1 at all
    (e.g. it's only in a remittance-slip footer on a later page, or the
    letterhead is an image rather than text)."""
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def detect_vendor(pdf_path):
    text = probe_first_page_text(pdf_path)
    for module in EXTRACTORS:
        if any(sig in text for sig in module.VENDOR_SIGNATURE):
            return module

    # Page 1 didn't have it - some statements only print the vendor name in
    # a footer/remittance slip on a later page. Widen the search before
    # giving up.
    full_text = probe_all_pages_text(pdf_path)
    for module in EXTRACTORS:
        if any(sig in full_text for sig in module.VENDOR_SIGNATURE):
            return module

    raise UnknownVendorError(
        f"Could not match {pdf_path!r} to a known vendor signature. "
        f"Known vendors: {[m.VENDOR_SIGNATURE[0] for m in EXTRACTORS]}. "
        "This statement format hasn't been taught to the pipeline yet - "
        "it needs its own extract_<vendor>.py module (see extract_astech.py "
        "for the simplest template)."
    )


def process(pdf_path, output_dir="."):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    out_base = os.path.join(output_dir, stem)
    print(f"\n=== {pdf_path} ===")

    module = detect_vendor(pdf_path)
    print(f"Detected vendor: {module.__name__} (signature: {module.VENDOR_SIGNATURE[0]!r})")

    kwargs = {"output_dir": output_dir} if module is extract_ksi else {}
    result = module.extract(pdf_path, **kwargs)
    line_items, fieldnames, summary, full_text = (
        result["line_items"], result["fieldnames"], result["summary"], result["full_text"]
    )

    lineitems_path = f"{out_base} - line items.csv"
    with open(lineitems_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(line_items)

    summary_path = f"{out_base} - summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Field", "Value"])
        for k, v in summary.items():
            writer.writerow([k, v])

    written = [lineitems_path, summary_path]
    if full_text:
        text_path = f"{out_base} - full text.txt"
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        written.append(text_path)

    print(f"Line items: {len(line_items)}")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("Wrote: " + ", ".join(written))


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_all.py file1.pdf [file2.pdf ...] [--out-dir DIR]")
        sys.exit(1)

    args = sys.argv[1:]
    output_dir = "."
    if "--out-dir" in args:
        i = args.index("--out-dir")
        output_dir = args[i + 1]
        del args[i:i + 2]
    os.makedirs(output_dir, exist_ok=True)

    for pdf_path in args:
        try:
            process(pdf_path, output_dir)
        except UnknownVendorError as e:
            print(f"\n=== {pdf_path} ===")
            print(f"SKIPPED: {e}")


if __name__ == "__main__":
    main()
