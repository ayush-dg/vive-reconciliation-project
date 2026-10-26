"""
tests/test_ai_no_rows_retry.py

An AI answer with no rows (2026-10-26; the Faulkner case: the model returned the column names and an
empty rows list, the client called it a truncation and the engine fell straight back to the generic
pdfplumber reader, which found 0 rows). Now DocumentUnderstandingEngine:

- an answer with column names and no rows ("Response appears truncated"), a successful answer with no
  rows on a document that is a statement, or one with far fewer rows than the PDF's text layer prints
  (fewer than half its dated lines with an amount, at least 5 such lines) gets ONE automatic retry;
- if the retry is no better, the deterministic reader for that layout (src/extraction/python_library:
  extract_ef320 and the other vendor extractors, matched by their signature) is used before giving up;
- only then the generic pdfplumber fallback, as before; an AI answer that has some rows is kept (with a
  warning) rather than replaced by a generic read;
- every other answer -- a normal one, a "not a statement" document, any other failure -- is unchanged:
  one call, no retry.

A scripted stand-in AI client and synthetic PDFs only: no AI, network or database.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fitz

from src.ai import document_understanding_engine as due
from src.ai.base_client import AIResponse

NO_ROWS = "Response appears truncated — falling back"


def answer(rows, document_type="VENDOR_STATEMENT"):
    return AIResponse(success=True, provider="claude_sonnet", model="claude-test",
                      parsed_json={"document_metadata": {"document_type": document_type},
                                   "invoices": [{"invoice_number": f"INV{i}"} for i in range(rows)], "warnings": []})


def failed(error=NO_ROWS):
    return AIResponse(success=False, provider="claude_sonnet", model="claude-test", error=error)


class ScriptedClient:
    model = "claude-test"

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def generate_with_file(self, path, prompt):
        self.calls += 1
        return self.responses.pop(0)


ScriptedClient.__name__ = "ClaudeSonnetClient"


def text_pdf(lines):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((40, 60), "SYNTHETIC PARTS SUPPLY  STATEMENT OF ACCOUNT", fontsize=9)
    for k in range(lines):
        page.insert_text((40, 100 + 14 * k), f"08/{k + 1:02d}/2026   INV{1000 + k}   Parts order   {100 + k}.25", fontsize=9)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    return f.name


class _Case(unittest.TestCase):

    def understand(self, client, pdf="no-such-file.pdf", reader=None):
        self.fallback = mock.Mock(return_value={"invoices": [{"invoice_number": "fragment"}], "warnings": []})
        self.reader = mock.Mock(return_value=reader)
        for p in (mock.patch.object(due.client_factory, "get_ai_client", return_value=client),
                  mock.patch.object(due, "upright_copy", side_effect=lambda p: (p, {})),
                  mock.patch.object(due, "extract_with_pdfplumber", self.fallback),
                  mock.patch.object(due, "_deterministic_reader", self.reader),
                  mock.patch.object(due, "log_ai_call"), mock.patch("builtins.print")):
            p.start()
            self.addCleanup(p.stop)
        return due.DocumentUnderstandingEngine().understand("", pdf, statement_id="STMT-T")

    def pdf(self, lines):
        path = text_pdf(lines)
        self.addCleanup(os.remove, path)
        return path


class TestNoRows(_Case):

    def test_columns_and_no_rows_then_rows_on_the_retry(self):
        client = ScriptedClient(failed(), answer(6))
        result = self.understand(client)
        self.assertEqual((client.calls, len(result["invoices"]), result["_provider_used"]), (2, 6, "claude_sonnet"))
        self.fallback.assert_not_called()
        self.reader.assert_not_called()

    def test_no_rows_twice_uses_the_deterministic_reader_before_giving_up(self):
        client = ScriptedClient(failed(), failed())
        reader = {"invoices": [{"invoice_number": "518306"}], "_provider_used": "python_library",
                  "_deterministic_reader": "extract_ef320", "warnings": []}
        result = self.understand(client, reader=reader)
        self.assertEqual((client.calls, result["_provider_used"], result["_deterministic_reader"]),
                         (2, "python_library", "extract_ef320"))
        self.fallback.assert_not_called()

    def test_no_rows_twice_and_no_reader_falls_back_as_before(self):
        client = ScriptedClient(failed(), failed())
        result = self.understand(client)
        self.assertEqual((client.calls, result["_provider_used"]), (2, "pdfplumber"))
        self.reader.assert_called_once()

    def test_a_successful_answer_with_no_rows_is_retried(self):
        client = ScriptedClient(answer(0), answer(3))
        result = self.understand(client)
        self.assertEqual((client.calls, len(result["invoices"])), (2, 3))

    def test_not_a_statement_is_never_retried(self):
        client = ScriptedClient(answer(0, document_type="NOT_A_STATEMENT"))
        result = self.understand(client)
        self.assertEqual((client.calls, result["document_metadata"]["document_type"]), (1, "NOT_A_STATEMENT"))
        self.reader.assert_not_called()

    def test_any_other_failure_is_not_retried(self):
        client = ScriptedClient(failed("HTTP 529 overloaded"))
        result = self.understand(client)
        self.assertEqual((client.calls, result["_provider_used"]), (1, "pdfplumber"))
        self.reader.assert_not_called()


class TestFarFewerRowsThanTheTextLayer(_Case):

    def test_far_fewer_rows_are_retried(self):
        client = ScriptedClient(answer(2), answer(12))
        result = self.understand(client, self.pdf(12))
        self.assertEqual((client.calls, len(result["invoices"])), (2, 12))

    def test_far_fewer_rows_twice_prefer_a_deterministic_reader_with_more_rows(self):
        reader = {"invoices": [{"invoice_number": str(i)} for i in range(12)], "_provider_used": "python_library",
                  "_deterministic_reader": "extract_x", "warnings": []}
        client = ScriptedClient(answer(2), answer(3))
        result = self.understand(client, self.pdf(12), reader=reader)
        self.assertEqual((client.calls, len(result["invoices"]), result["_provider_used"]), (2, 12, "python_library"))

    def test_far_fewer_rows_twice_without_a_reader_keep_the_better_ai_answer_with_a_warning(self):
        client = ScriptedClient(answer(2), answer(3))
        result = self.understand(client, self.pdf(12))
        self.assertEqual((client.calls, len(result["invoices"]), result["_provider_used"]), (2, 3, "claude_sonnet"))
        self.assertTrue(any("text layer" in w for w in result["warnings"]), result["warnings"])
        self.fallback.assert_not_called()

    def test_a_complete_answer_is_called_once(self):
        client = ScriptedClient(answer(12))
        result = self.understand(client, self.pdf(12))
        self.assertEqual((client.calls, len(result["invoices"])), (1, 12))

    def test_a_short_statement_is_not_judged(self):
        client = ScriptedClient(answer(1))
        self.understand(client, self.pdf(4))   # under 5 printed lines: never a shortfall
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
