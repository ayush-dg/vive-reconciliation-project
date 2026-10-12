"""
tests/test_upload_preprocess.py

What ClaudeSonnetClient sends for one PDF (src/ai/upload_preprocess.py,
2026-10-12): as_is / compressed (legibility-gated) / split, merged in page
order, any part failing => the whole statement fails.

SYNTHETIC DATA ONLY: every PDF is generated here with PyMuPDF; the model is
never called -- ClaudeSonnetClient._real_file_call is replaced by a fake that
reads which pages it was sent from the PDF bytes themselves.
"""

import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fitz

from src.ai import upload_preprocess as up
from src.ai.claude_sonnet_client import ClaudeSonnetClient

OK_GATE = lambda original, reduced: {"ok": True, "recall": 1.0}
BAD_GATE = lambda original, reduced: {"ok": False, "recall": 0.5}


def text_pdf(pages, rows_per_page=3, total_on_last=True):
    """A statement whose page k prints "PAGE k" and rows INV-k-r of 10.00;
    the last page prints the TOTAL."""
    doc = fitz.open()
    for k in range(1, pages + 1):
        page = doc.new_page(width=612, height=792)
        page.insert_text((40, 40), f"PAGE {k}", fontsize=10)
        for r in range(rows_per_page):
            page.insert_text((40, 80 + 14 * r), f"08/{k:02d}/26 INV-{k}-{r} 10.00", fontsize=9)
        if total_on_last and k == pages:
            page.insert_text((40, 700), f"TOTAL DUE {pages * rows_per_page * 10:.2f}", fontsize=10)
    return _save(doc)


def noise_pdf(pages, side=700):
    """Pages that are one incompressible image each (a large scan)."""
    from PIL import Image
    doc = fitz.open()
    for _ in range(pages):
        buf = io.BytesIO()
        Image.frombytes("RGB", (side, side), os.urandom(side * side * 3)).save(buf, format="PNG")
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=buf.getvalue())
    return _save(doc)


def _save(doc):
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    doc.close()
    return f.name


def pages_in(data):
    with fitz.open(stream=data, filetype="pdf") as doc:
        return [int(page.get_text().split("PAGE ")[1].split()[0]) for page in doc]


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class _Case(unittest.TestCase):
    def make(self, path):
        self.addCleanup(os.remove, path)
        return path


class TestPlanUpload(_Case):

    def test_small_pdf_is_sent_as_is_byte_for_byte(self):
        path = self.make(text_pdf(3))
        plan = up.plan_upload(path)
        self.assertEqual(plan.path, "as_is")
        with open(path, "rb") as f:
            self.assertEqual(plan.parts[0].data, f.read())

    def test_long_pdf_is_split_into_balanced_consecutive_ranges(self):
        path = self.make(text_pdf(30))
        plan = up.plan_upload(path, max_pages=12, gate=OK_GATE)
        self.assertEqual(plan.path, "split")
        self.assertEqual([(p.first_page, p.last_page) for p in plan.parts], [(1, 10), (11, 20), (21, 30)])
        for part in plan.parts:
            self.assertEqual(pages_in(part.data), list(range(part.first_page, part.last_page + 1)))
            self.assertFalse(part.reduced)

    def test_oversized_single_page_is_compressed_when_the_gate_passes(self):
        path = self.make(noise_pdf(1))
        size = os.path.getsize(path)
        plan = up.plan_upload(path, max_bytes=size - 1, gate=OK_GATE)
        self.assertEqual(plan.path, "compressed")
        self.assertLess(len(plan.parts[0].data), size)
        self.assertTrue(plan.parts[0].reduced)

    def test_oversized_document_is_split_losslessly_before_any_reduction(self):
        path = self.make(noise_pdf(4))
        size = os.path.getsize(path)
        gate = mock.Mock(side_effect=AssertionError("no reduction may be tried"))
        plan = up.plan_upload(path, max_bytes=size // 3, gate=gate)
        self.assertEqual(plan.path, "split")
        self.assertTrue(all(len(p.data) <= size // 3 and not p.reduced for p in plan.parts))
        self.assertEqual(plan.parts[0].first_page, 1)
        self.assertEqual(plan.parts[-1].last_page, 4)
        gate.assert_not_called()

    def test_only_the_page_that_is_too_big_alone_is_reduced(self):
        path = self.make(noise_pdf(3))
        one_page = len(up.page_range_bytes(open(path, "rb").read(), 1, 1))
        plan = up.plan_upload(path, max_bytes=one_page - 1, gate=OK_GATE)
        self.assertEqual([(p.first_page, p.reduced) for p in plan.parts], [(1, True), (2, True), (3, True)])
        with self.assertRaises(up.UploadTooLarge):
            up.plan_upload(path, max_bytes=one_page - 1, gate=BAD_GATE)

    def test_a_page_that_cannot_fit_without_losing_digits_fails_visibly(self):
        path = self.make(noise_pdf(1))
        with self.assertRaises(up.UploadTooLarge):
            up.plan_upload(path, max_bytes=1000, gate=BAD_GATE)

    def test_the_original_file_is_never_modified(self):
        path = self.make(noise_pdf(3))
        before = sha(path)
        up.plan_upload(path, max_bytes=os.path.getsize(path) // 2, gate=OK_GATE)
        up.plan_upload(path, max_bytes=os.path.getsize(path) // 2, gate=BAD_GATE, max_pages=1)
        self.assertEqual(sha(path), before)

    def test_unreadable_small_file_is_sent_as_is(self):
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.write(b"%PDF-1.4 not really")
        f.close()
        path = self.make(f.name)
        plan = up.plan_upload(path)
        self.assertEqual((plan.path, plan.parts[0].data), ("as_is", b"%PDF-1.4 not really"))


class TestLegibilityGate(_Case):

    def _digits_page(self, scale):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        for r in range(12):
            page.insert_text((40, 60 + 22 * r), f"08/{r + 1:02d}/26  INV{9000 + r}  {123.45 * (r + 1):,.2f}", fontsize=11 * scale)
        return doc.tobytes()

    def test_a_readable_reduction_keeps_the_digits(self):
        original = self._digits_page(1)
        verdict = up.legibility_check(original, up.reduce_pdf(original, 200, 80))
        self.assertTrue(verdict["ok"], verdict)

    def test_an_illegible_reduction_is_refused(self):
        original = self._digits_page(1)
        verdict = up.legibility_check(original, up.reduce_pdf(original, 25, 10))
        self.assertFalse(verdict["ok"], verdict)


class TestMerge(unittest.TestCase):

    def test_rows_in_page_order_and_statement_fields_from_the_right_part(self):
        parts = [up.UploadPart(b"", 1, 2), up.UploadPart(b"", 3, 4)]
        first = {"rows": [{"INV": "A"}], "columns_found": ["INV", "AMOUNT"], "vendor_name": "Fred Beans",
                 "previous_balance": 100.0, "statement_total_as_printed": None}
        second = {"rows": [{"INV": "B"}, {"INV": "C"}], "columns_found": ["INV", "AMOUNT", "BALANCE"],
                  "vendor_name": "FRED BEANS PARTS", "statement_total_as_printed": 14261.66}
        merged = up.merge_chunk_results(parts, [first, second])
        self.assertEqual([r["INV"] for r in merged["rows"]], ["A", "B", "C"])
        self.assertEqual([r["_page"] for r in merged["rows"]], [1, 3, 3])
        self.assertEqual(merged["columns_found"], ["INV", "AMOUNT", "BALANCE"])
        self.assertEqual(merged["statement_total_as_printed"], 14261.66)
        self.assertEqual(merged["previous_balance"], 100.0)
        self.assertEqual(merged["vendor_name"], "Fred Beans")
        self.assertTrue(any(note.startswith("vendor_name") for note in merged["_merge_notes"]))


# --------------------------------------------------------------------------
# The client with a fake model
# --------------------------------------------------------------------------

def fake_model(fail_pages=(), cut_off_pages=()):
    """A _real_file_call stand-in: returns one row per printed INV line of
    the pages it was sent, and the printed total if its last page has one."""
    calls = []

    def call(self, pdf_b64, temperature, max_tokens):
        data = base64.standard_b64decode(pdf_b64)
        pages = pages_in(data)
        calls.append(pages)
        self._last_stop_reason = "end_turn"
        if set(pages) & set(fail_pages):
            return False, "", "Claude API overloaded"
        if len(pages) > 1 and set(pages) & set(cut_off_pages):
            self._last_stop_reason = "max_tokens"
        rows, total = [], None
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                for line in page.get_text().splitlines():
                    if line.startswith("08/"):
                        date, inv, amount = line.split()
                        rows.append({"DATE": date, "INVOICE": inv, "AMOUNT": float(amount), "confidence": 0.95})
                    if line.startswith("TOTAL DUE"):
                        total = float(line.split()[-1])
        body = {"vendor_name": "Synthetic Supply", "statement_date": "08/31/26", "statement_total_as_printed": total,
                "columns_found": ["DATE", "INVOICE", "AMOUNT"], "rows": rows}
        return True, json.dumps(body), None
    return call, calls


def client():
    with mock.patch.dict(os.environ, {"AZURE_CLAUDE_API_KEY": "test", "AZURE_CLAUDE_SONNET_DEPLOYMENT": "test-model"}):
        c = ClaudeSonnetClient({"api_key_env_var": "AZURE_CLAUDE_API_KEY",
                                "deployment_env_var": "AZURE_CLAUDE_SONNET_DEPLOYMENT",
                                "retry_policy": {"max_retries": 0, "backoff_seconds": 0}})
    return c


class TestClientWithParts(_Case):

    def run_client(self, path, model, max_pages=up.MAX_PAGES_PER_REQUEST):
        c = client()
        planner = lambda p: up.plan_upload(p, max_bytes=c.MAX_UPLOAD_PDF_BYTES, max_pages=max_pages, gate=OK_GATE)
        with mock.patch.object(ClaudeSonnetClient, "_real_file_call", model), \
             mock.patch.object(c, "_upload_plan", planner), \
             mock.patch("builtins.print"):
            return c.generate_with_file(path, "")

    def test_small_file_takes_the_unchanged_single_request(self):
        path = self.make(text_pdf(2))
        model, calls = fake_model()
        response = self.run_client(path, model)
        self.assertTrue(response.success, response.error)
        self.assertEqual(calls, [[1, 2]])
        self.assertFalse(any(w["code"] == "UPLOAD_PREPROCESSED" for w in response.parsed_json["warnings"]))

    def test_split_rows_are_merged_in_page_order_with_continuous_row_numbers(self):
        path = self.make(text_pdf(7))
        model, calls = fake_model()
        response = self.run_client(path, model, max_pages=3)
        self.assertTrue(response.success, response.error)
        self.assertEqual(calls, [[1, 2, 3], [4, 5, 6], [7]])
        invoices = response.parsed_json["invoices"]
        self.assertEqual([i["invoice_number"] for i in invoices][:4], ["INV-1-0", "INV-1-1", "INV-1-2", "INV-2-0"])
        self.assertEqual([i["row_number"] for i in invoices], list(range(1, 22)))
        self.assertEqual(invoices[-1]["page_number"], 7)
        self.assertEqual(response.parsed_json["statement_metadata"]["statement_total_as_printed"], 210.0)

    def test_printed_total_comes_from_the_part_that_prints_it(self):
        path = self.make(text_pdf(5))
        model, _ = fake_model()
        meta = self.run_client(path, model, max_pages=2).parsed_json["statement_metadata"]
        self.assertEqual(meta["statement_total_as_printed"], 150.0)

    def test_one_part_failing_fails_the_whole_statement(self):
        path = self.make(text_pdf(6))
        model, calls = fake_model(fail_pages=(5,))
        response = self.run_client(path, model, max_pages=2)
        self.assertFalse(response.success)
        self.assertIn("whole statement failed", response.error)
        self.assertIn("pages 5-6", response.error)
        self.assertIsNone(response.parsed_json)

    def test_a_cut_off_part_is_split_and_re_sent(self):
        path = self.make(text_pdf(4))
        model, calls = fake_model(cut_off_pages=(1, 2))
        response = self.run_client(path, model, max_pages=4)
        self.assertTrue(response.success, response.error)
        self.assertEqual(calls, [[1, 2, 3, 4], [1, 2], [1], [2], [3, 4]])
        self.assertEqual(len(response.parsed_json["invoices"]), 12)

    def test_the_arithmetic_gate_runs_on_the_merged_rows(self):
        from src.validation.arithmetic_gate import validate_with_fallbacks
        path = self.make(text_pdf(5))
        model, _ = fake_model()
        result = self.run_client(path, model, max_pages=2).parsed_json
        meta = result["statement_metadata"]
        verdict = validate_with_fallbacks(meta["statement_total_as_printed"], meta["statement_total_computed"],
                                          result["invoices"])
        self.assertEqual((verdict["status"], verdict["method"]), ("matches", "primary"))
        self.assertEqual(meta["statement_total_computed"], 150.0)

    def test_too_large_to_send_fails_visibly_without_a_request(self):
        path = self.make(noise_pdf(1))
        model, calls = fake_model()
        c = client()
        planner = lambda p: up.plan_upload(p, max_bytes=1000, gate=BAD_GATE)
        with mock.patch.object(ClaudeSonnetClient, "_real_file_call", model), \
             mock.patch.object(c, "_upload_plan", planner), mock.patch("builtins.print"):
            response = c.generate_with_file(path, "")
        self.assertFalse(response.success)
        self.assertIn("PDF too large to send", response.error)
        self.assertEqual(calls, [])

    def test_original_file_unchanged_after_a_split_extraction(self):
        path = self.make(text_pdf(5))
        before = sha(path)
        model, _ = fake_model()
        self.run_client(path, model, max_pages=2)
        self.assertEqual(sha(path), before)


if __name__ == "__main__":
    unittest.main()
