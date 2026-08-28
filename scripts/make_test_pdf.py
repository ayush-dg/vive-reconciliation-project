#!/usr/bin/env python3
"""Test-fixture helper only — generates a single-page PDF containing exactly
the given text. Not part of the application; used by ui_tests/scripts to
build PDF fixtures pdfplumber can parse (better-sqlite3/JS PDF fixtures used
elsewhere in this project are plain byte strings, which satisfy the app's own
"looks like a PDF" checks but aren't real parseable PDFs — Session 3's tests
need actual pdfplumber-readable content).

Usage: python make_test_pdf.py <output_path> <text_file_path>
(text passed via a file, not argv, to avoid shell-escaping issues with
newlines/pipes/special characters in the marker-format test content)
"""
import sys

import fitz


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: make_test_pdf.py <output_path> <text_file_path>", file=sys.stderr)
        return 1

    output_path, text_file_path = sys.argv[1], sys.argv[2]
    with open(text_file_path, "r", encoding="utf-8") as f:
        text = f.read()

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=10)
    doc.save(output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
