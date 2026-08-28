#!/usr/bin/env python3
"""Deterministic PDF text extraction (Task 3.1's known-vendor path).

Invoked as a subprocess from src/lib/pdfplumberExtractor.ts. Takes a PDF file
path as argv[1], prints a single JSON object to stdout:
  {"text": "<all page text, joined by \\n>", "page_count": <int>}
Never invokes any LLM — this is the deterministic, non-AI extraction path
Claude.md's Fixed Stack names explicitly ("deterministic pdfplumber-based
extractors"). Errors are reported as {"error": "<message>"} on stdout with a
non-zero exit code, never a raw Python traceback (the Node caller parses
stdout as JSON either way).
"""
import json
import sys

import pdfplumber


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: pdfplumber_extract.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
            text = "\n".join(pages_text)
            print(json.dumps({"text": text, "page_count": len(pdf.pages)}))
            return 0
    except Exception as exc:  # noqa: BLE001 — deliberately broad: any failure
        # here must surface as a structured extraction-attempt failure
        # (Task 3.2's validation gate), never crash the Node caller.
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
