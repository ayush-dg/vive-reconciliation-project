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


def column_model(rename_pages=(), stubborn=False, cut_off_pages=()):
    """A fake that also answers columns_found: parts holding a page in
    rename_pages answer different column names -- unless the part was sent
    with the list enforced (stubborn: even then). Records, per call, the
    pages sent and the carried list the client set."""
    calls = []

    def call(self, pdf_b64, temperature, max_tokens):
        data = base64.standard_b64decode(pdf_b64)
        pages = pages_in(data)
        carried = getattr(self, "_continuation_columns", None)
        enforced = getattr(self, "_continuation_enforced", False)
        calls.append({"pages": pages, "carried": carried, "enforced": enforced})
        self._last_stop_reason = "end_turn"
        if len(pages) > 1 and set(pages) & set(cut_off_pages):
            self._last_stop_reason = "max_tokens"
        renamed = bool(set(pages) & set(rename_pages)) and (stubborn or not enforced)
        names = ["Date", "Inv #", "Amt"] if renamed else ["DATE", "INVOICE", "AMOUNT"]
        rows = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                for line in page.get_text().splitlines():
                    if line.startswith("08/"):
                        date, inv, amount = line.split()
                        rows.append(dict(zip(names, (date, inv, float(amount))), confidence=0.95))
        body = {"vendor_name": "Synthetic Supply", "statement_date": "08/31/26", "statement_total_as_printed": None,
                "columns_found": names, "rows": rows}
        return True, json.dumps(body), None
    return call, calls


class TestCarriedColumns(_Case):
    """2026-10-16: parts 2+ of a split statement get part 1's columns_found."""

    run_client = TestClientWithParts.run_client

    def test_later_parts_get_part_ones_list_and_are_sent_in_order(self):
        path = self.make(text_pdf(6))
        model, calls = column_model()
        response = self.run_client(path, model, max_pages=2)
        self.assertTrue(response.success, response.error)
        self.assertEqual([c["pages"] for c in calls], [[1, 2], [3, 4], [5, 6]])
        self.assertEqual([c["carried"] for c in calls], [None, ["DATE", "INVOICE", "AMOUNT"], ["DATE", "INVOICE", "AMOUNT"]])
        self.assertFalse(any(c["enforced"] for c in calls))
        message = next(w["message"] for w in response.parsed_json["warnings"] if w["code"] == "UPLOAD_PREPROCESSED")
        self.assertIn("pages 3-4: sent with part 1's column list (3 columns); matched", message)
        self.assertIn("pages 5-6: sent with part 1's column list (3 columns); matched", message)

    def test_different_names_are_detected_retried_enforced_and_then_pass(self):
        path = self.make(text_pdf(6))
        model, calls = column_model(rename_pages=(4,))
        response = self.run_client(path, model, max_pages=2)
        self.assertTrue(response.success, response.error)
        self.assertEqual([(c["pages"], c["enforced"]) for c in calls],
                         [([1, 2], False), ([3, 4], False), ([3, 4], True), ([5, 6], False)])
        self.assertEqual(len(response.parsed_json["invoices"]), 18)
        message = next(w["message"] for w in response.parsed_json["warnings"] if w["code"] == "UPLOAD_PREPROCESSED")
        self.assertIn("pages 3-4: sent with part 1's column list; first answer ['Date', 'Inv #', 'Amt']; matched after the "
                      "enforced retry", message)

    def test_still_different_after_the_retry_fails_the_whole_statement(self):
        path = self.make(text_pdf(6))
        model, calls = column_model(rename_pages=(5,), stubborn=True)
        response = self.run_client(path, model, max_pages=2)
        self.assertFalse(response.success)
        self.assertIn("part pages 5-6 did not use part 1's columns ['DATE', 'INVOICE', 'AMOUNT']", response.error)
        self.assertIn("whole statement failed", response.error)
        self.assertIsNone(response.parsed_json)
        self.assertEqual(sum(1 for c in calls if c["pages"] == [5, 6]), 2)  # sent, then retried once

    def test_a_single_request_file_never_carries_a_list(self):
        path = self.make(text_pdf(3))
        model, calls = column_model()
        response = self.run_client(path, model)
        self.assertTrue(response.success, response.error)
        self.assertEqual(calls, [{"pages": [1, 2, 3], "carried": None, "enforced": False}])

    def test_a_cut_off_later_part_is_re_split_and_both_halves_get_the_list(self):
        path = self.make(text_pdf(8))
        model, calls = column_model(cut_off_pages=(6,))
        response = self.run_client(path, model, max_pages=4)
        self.assertTrue(response.success, response.error)
        self.assertEqual([c["pages"] for c in calls], [[1, 2, 3, 4], [5, 6, 7, 8], [5, 6], [5], [6], [7, 8]])
        self.assertEqual([c["carried"] for c in calls[1:]], [["DATE", "INVOICE", "AMOUNT"]] * 5)
        self.assertEqual([i["invoice_number"] for i in response.parsed_json["invoices"]],
                         [f"INV-{k}-{r}" for k in range(1, 9) for r in range(3)])

    def _payload_texts(self, path, max_pages, config=None):
        """The prompt text the REAL _real_file_call puts in each request (requests.post mocked).
        The whole request bodies are kept in self.payloads."""
        from src.ai import claude_sonnet_client as csc
        texts = []
        self.payloads = []

        def post(url, headers=None, json=None, timeout=None):
            self.payloads.append(json)
            data = base64.standard_b64decode(json["messages"][0]["content"][0]["source"]["data"])
            texts.append((pages_in(data), json["messages"][0]["content"][1]["text"]))
            rows = [{"DATE": "08/01/26", "INVOICE": f"INV-{p}-0", "AMOUNT": 10.0} for p in pages_in(data)]
            body = {"vendor_name": "Synthetic Supply", "columns_found": ["DATE", "INVOICE", "AMOUNT"], "rows": rows}
            resp = mock.Mock(status_code=200, text="")
            resp.json.return_value = {"stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
                                      "content": [{"type": "text", "text": globals()["json"].dumps(body)}]}
            resp.raise_for_status.return_value = None
            return resp
        c = client()
        c.endpoint = "https://example.invalid"
        c.config.update(config or {})
        planner = lambda p: up.plan_upload(p, max_bytes=c.MAX_UPLOAD_PDF_BYTES, max_pages=max_pages, gate=OK_GATE)
        with mock.patch.object(csc.requests, "post", post), mock.patch.object(c, "_upload_plan", planner), \
                mock.patch.object(c, "_detect_truncation", lambda *a, **k: None), mock.patch("builtins.print"):
            response = c.generate_with_file(path, "")
        self.assertTrue(response.success, response.error)
        return texts

    def test_single_request_payload_is_exactly_todays_prompt(self):
        from src.ai.claude_sonnet_client import EXTRACTION_PROMPT
        texts = self._payload_texts(self.make(text_pdf(3)), max_pages=16)
        self.assertEqual(texts, [([1, 2, 3], EXTRACTION_PROMPT)])

    def test_split_payload_adds_the_continuation_note_to_later_parts_only(self):
        from src.ai.claude_sonnet_client import EXTRACTION_PROMPT, continuation_note
        texts = self._payload_texts(self.make(text_pdf(4)), max_pages=2)
        self.assertEqual(texts[0], ([1, 2], EXTRACTION_PROMPT))
        self.assertEqual(texts[1], ([3, 4], EXTRACTION_PROMPT + continuation_note(["DATE", "INVOICE", "AMOUNT"])))


class TestRequestTemperature(_Case):
    """2026-10-19: the PDF request carries the configured temperature (before,
    _real_file_call left it out and the API default 1.0 applied)."""

    _payload_texts = TestCarriedColumns._payload_texts

    def test_single_request_carries_the_config_temperature(self):
        self._payload_texts(self.make(text_pdf(3)), max_pages=16, config={"temperature": 0.1})
        self.assertEqual([p.get("temperature") for p in self.payloads], [0.1])

    def test_every_part_of_a_split_statement_carries_it_including_continuations(self):
        texts = self._payload_texts(self.make(text_pdf(6)), max_pages=2, config={"temperature": 0.1})
        self.assertEqual([t[0] for t in texts], [[1, 2], [3, 4], [5, 6]])
        self.assertIn("CONTINUATION PAGES", texts[1][1])  # a continuation part...
        self.assertEqual([p.get("temperature") for p in self.payloads], [0.1, 0.1, 0.1])  # ...carries it too

    def test_zero_is_sent_not_dropped(self):
        self._payload_texts(self.make(text_pdf(4)), max_pages=2, config={"temperature": 0})
        self.assertEqual([p.get("temperature") for p in self.payloads], [0, 0])

    def test_no_config_value_sends_the_client_default(self):
        self._payload_texts(self.make(text_pdf(3)), max_pages=16)
        self.assertEqual([p.get("temperature") for p in self.payloads], [0.1])


if __name__ == "__main__":
    unittest.main()
