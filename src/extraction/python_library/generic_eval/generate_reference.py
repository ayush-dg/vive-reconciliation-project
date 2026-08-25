"""
Generates ground-truth line-item JSON for each of the 10 target vendor PDFs
by running that vendor's existing, verified extract_<vendor>.py module
directly (bypassing extract_all.py's vendor-sniffing, since we already know
the mapping) -- this is the same code path already trusted as 100% accurate
per vendor. Output is used by compare_generic.py as the reference to check
the new generic extractor against.
"""
import json
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.dirname(THIS_DIR)
SAMPLE_DIR = os.path.join(LIB_DIR, "sample_pdfs")
OUT_DIR = os.path.join(THIS_DIR, "output")

sys.path.insert(0, LIB_DIR)

import extract_astech
import extract_empire
import extract_wilberts
import extract_quirk
import extract_nimey
import extract_lia
import extract_keystone
import extract_precision
import extract_adas
import extract_statement

VENDORS = [
    ("Fred Beans Lee's", extract_statement, "Fred Beans Lee's.pdf"),
    ("Astech Owego", extract_astech, "Astech Owego.pdf"),
    ("Empire Hewitt's", extract_empire, "Empire Hewitt's.PDF"),
    ("Wilbert's Owego", extract_wilberts, "Wilbert's Owego.PDF"),
    ("Quirk Colemans", extract_quirk, "Quirk Colemans.PDF"),
    ("Matt Nimey Sprague's", extract_nimey, "Matt Nimey Sprague's.pdf"),
    ("Lia Vestal", extract_lia, "Lia Vestal.pdf"),
    ("Keystone Neet's", extract_keystone, "Keystone Neet's.pdf"),
    ("Precision Diagnostics Klapec", extract_precision, "Precision Diagnostics Klapec.pdf"),
    ("Adas Calibration Don Joe", extract_adas, "Adas Calibration Don Joe.pdf"),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for label, module, filename in VENDORS:
        pdf_path = os.path.join(SAMPLE_DIR, filename)
        result = module.extract(pdf_path)
        out_path = os.path.join(OUT_DIR, f"{label} - reference.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "vendor": label,
                "module": module.__name__,
                "fieldnames": result["fieldnames"],
                "line_items": result["line_items"],
                "summary": result.get("summary", {}),
            }, f, indent=2, default=str)
        print(f"{label}: {len(result['line_items'])} reference line items -> {out_path}")


if __name__ == "__main__":
    main()
