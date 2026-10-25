"""
tests/test_timeouts_oct25.py

The four dev jobs the 30-minute worker cap killed on 2026-10-25 (Berlin City
13 pages, NYE 9-4-26 16 pages -- both after a successful AI call -- and two
Fred Beans statements):

- the validation OCR text is skipped above the 12-page cap of the PDF checks
  and read at most once per apply_arithmetic_validation() call;
- page orientation runs within a time budget for PDFs over 12 pages;
- VIVE_TESSERACT_THREADS caps Tesseract's threads (default unchanged);
- routing reuses the page text Step 2 just read;
- the worker prints each "Step timing" line while the pipeline runs, and a
  timed-out job keeps the end of the pipeline's output in error_message
  (tested with a stand-in pipeline subprocess);
- the engine prints its orientation and AI-call timings.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf

from src.ai import document_understanding_engine as due
from src.ai import ocr_extractor, page_orientation
from src.rerun.in_place import load_intake

INTAKE = load_intake()


def blank_pdf(testcase, pages, text=None):
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=612, height=792)
        if text:
            page.insert_text((72, 72), text, fontsize=10)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    doc.close()
    testcase.addCleanup(os.remove, f.name)
    return f.name


def statement(printed=100.0, computed=90.0):
    return {"document_metadata": {"document_type": "VENDOR_STATEMENT"},
            "vendor_metadata": {"vendor_name": "Test Vendor"},
            "statement_metadata": {"statement_total_as_printed": printed, "statement_total_computed": computed},
            "invoices": [{"invoice_number": "1", "amount": 90.0, "outstanding_amount": 90.0, "credit": None}]}


class TestValidationOcrText(unittest.TestCase):

    def test_scan_over_the_page_cap_is_not_ocrd(self):
        pdf = blank_pdf(self, 13)
        with mock.patch.object(INTAKE, "ocr_pdf_text", return_value="Total due 100.00") as ocr, \
                mock.patch("builtins.print"):
            text, source = INTAKE._validation_text("", pdf, {"statement_total_as_printed": None}, True)
        self.assertEqual((text, source), ("", None))
        ocr.assert_not_called()

    def test_scan_at_the_cap_is_still_ocrd(self):
        pdf = blank_pdf(self, 12)
        ocr_text = "STATEMENT\n" + "INV 1001 PARTS ORDER 12.00\n" * 12 + "Total due 100.00"
        with mock.patch.object(INTAKE, "ocr_pdf_text", return_value=ocr_text) as ocr:
            text, source = INTAKE._validation_text("", pdf, {"statement_total_as_printed": None}, True)
        self.assertEqual((text, source), (ocr_text, "ocr"))
        ocr.assert_called_once()

    def test_ocr_text_is_read_once_per_validation(self):
        pdf = blank_pdf(self, 2)

        def two_gate_passes(schema, text, path):
            INTAKE._validate_extraction(schema, text, path)
            return INTAKE._validate_extraction(schema, text, path)

        mismatch = {"status": "mismatch", "printed": 100.0, "computed": 90.0, "difference": 10.0, "method": None,
                    "detail": None}
        with mock.patch.object(INTAKE, "_apply_arithmetic_validation", side_effect=two_gate_passes), \
                mock.patch.object(INTAKE, "validate_with_fallbacks", return_value=mismatch), \
                mock.patch.object(INTAKE, "try_pdf_full_match", side_effect=lambda v, *a: v), \
                mock.patch.object(INTAKE, "ocr_pdf_text", return_value="") as ocr, mock.patch("builtins.print"):
            INTAKE.apply_arithmetic_validation(statement(), "", pdf)
            self.assertEqual(ocr.call_count, 1)
            INTAKE.apply_arithmetic_validation(statement(), "", pdf)   # a new validation reads it again
            self.assertEqual(ocr.call_count, 2)
        self.assertIsNone(INTAKE._OCR_TEXT_MEMO)


class TestOrientationBudget(unittest.TestCase):

    def _run(self, pages, budget=None):
        pdf = blank_pdf(self, pages)
        calls = []

        def fake_osd(page, **kwargs):
            calls.append(kwargs)
            return 0

        patches = [mock.patch.object(page_orientation, "_osd_rotation", side_effect=fake_osd),
                   mock.patch("builtins.print")]
        if budget is not None:
            patches.append(mock.patch.object(page_orientation, "LONG_PDF_BUDGET_SECONDS", budget))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual(page_orientation.upright_copy(pdf), (pdf, {}))
        return calls

    def test_up_to_the_cap_every_page_is_checked_without_a_budget(self):
        self.assertEqual(self._run(12), [{}] * 12)

    def test_over_the_cap_each_check_gets_the_remaining_budget(self):
        calls = self._run(13)
        self.assertEqual(len(calls), 13)
        self.assertTrue(all(0 < c["timeout"] <= page_orientation.LONG_PDF_BUDGET_SECONDS for c in calls))

    def test_over_the_cap_a_spent_budget_leaves_the_rest_unchecked(self):
        self.assertEqual(self._run(16, budget=0.0), [])


class TestTesseractThreads(unittest.TestCase):

    def setUp(self):
        saved = {k: os.environ.get(k) for k in ("VIVE_TESSERACT_THREADS", "OMP_THREAD_LIMIT")}

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)
        os.environ.pop("VIVE_TESSERACT_THREADS", None)
        os.environ.pop("OMP_THREAD_LIMIT", None)

    def test_setting_caps_tesseract_threads(self):
        os.environ["VIVE_TESSERACT_THREADS"] = "2"
        ocr_extractor._configure_tesseract_path(mock.Mock())
        self.assertEqual(os.environ.get("OMP_THREAD_LIMIT"), "2")

    def test_default_is_unchanged(self):
        for value in (None, "", "abc", "0", "-1"):
            if value is None:
                os.environ.pop("VIVE_TESSERACT_THREADS", None)
            else:
                os.environ["VIVE_TESSERACT_THREADS"] = value
            ocr_extractor.apply_tesseract_thread_limit()
            self.assertNotIn("OMP_THREAD_LIMIT", os.environ, value)
        os.environ["OMP_THREAD_LIMIT"] = "7"
        os.environ.pop("VIVE_TESSERACT_THREADS")
        ocr_extractor.apply_tesseract_thread_limit()
        self.assertEqual(os.environ["OMP_THREAD_LIMIT"], "7")

    def test_orientation_check_runs_tesseract_with_the_limit(self):
        os.environ["VIVE_TESSERACT_THREADS"] = "1"
        seen = {}

        def fake_osd(image, config, timeout):
            seen.update(limit=os.environ.get("OMP_THREAD_LIMIT"), timeout=timeout)
            return "Rotate: 0\nOrientation confidence: 9.0"

        with pymupdf.open(blank_pdf(self, 1)) as doc, mock.patch("pytesseract.image_to_osd", side_effect=fake_osd):
            self.assertEqual(page_orientation._osd_rotation(doc[0]), 0)
        self.assertEqual(seen, {"limit": "1", "timeout": 0})


class TestRoutingReusesPageText(unittest.TestCase):

    def test_route_does_not_parse_the_pdf_again(self):
        import pdfplumber
        pdf = blank_pdf(self, 2, text="Some printed statement text that is long enough to be a text layer")
        real_open = pdfplumber.open
        with mock.patch("pdfplumber.open", side_effect=real_open) as opened, mock.patch("builtins.print"):
            INTAKE.extract_pdf_text(pdf)
            route = INTAKE._determine_extraction_route(pdf)
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(route["pdf_type"], "text_embedded")


CHILD = r'''
import time
print("    Step timing: pdf_text=1.0s", flush=True)
print("    Step timing: orientation=2.0s", flush=True)
print("  [Engine] ClaudeSonnetClient success -- 84 invoices extracted", flush=True)
time.sleep(30)
'''
CHILD_OK = r'''
import time
print("Statement ID: STMT-T0001", flush=True)
print("    Step timing: pdf_text=1.0s", flush=True)
time.sleep(1.5)
print("PIPELINE DONE", flush=True)
'''


class TestWorkerLiveOutputAndTimeout(unittest.TestCase):
    JOB = {"job_id": "J1", "pdf_path": __file__, "pdf_filename": "x.pdf", "source_blob_path": None}

    def _run(self, child, timeout, **query_patches):
        from web import worker
        printed = []
        t0 = time.monotonic()
        patches = [mock.patch.object(worker, "_pipeline_command", return_value=[sys.executable, "-c", child]),
                   mock.patch.object(worker, "PIPELINE_TIMEOUT_SECONDS", timeout),
                   mock.patch("web.worker.print", create=True,
                              side_effect=lambda *a, **k: printed.append((time.monotonic() - t0, " ".join(map(str, a))))),
                   mock.patch.object(worker, "_write_blob_outcome"),
                   mock.patch("web.queries.update_job_status")]
        patches += [mock.patch(f"web.queries.{name}", return_value=value) for name, value in query_patches.items()]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        worker._run_job(dict(self.JOB))
        return printed, mocks[4].call_args.kwargs, time.monotonic() - t0

    def test_step_lines_are_printed_live_and_a_timeout_keeps_the_output(self):
        printed, kwargs, elapsed = self._run(CHILD, 4)
        steps = [(t, line) for t, line in printed if line.startswith("[worker] Job J1: Step timing:")]
        self.assertEqual([line for _, line in steps], ["[worker] Job J1: Step timing: pdf_text=1.0s",
                                                       "[worker] Job J1: Step timing: orientation=2.0s"])
        self.assertTrue(all(t < 3.5 for t, _ in steps), steps)    # printed before the cap killed it
        self.assertEqual(kwargs["status"], "FAILED")
        message = kwargs["error_message"]
        self.assertIn("Step timing: orientation=2.0s", message)
        self.assertIn("84 invoices extracted", message)
        self.assertRegex(message.strip().splitlines()[-1], r"^Worker error: .*timed out after 4 seconds")
        self.assertLess(elapsed, 20)

    def test_timeout_keeps_only_the_last_4000_characters(self):
        from web import worker
        out = b"x" * 6000 + b"\n    Step timing: ai_call=300.0s\n  Validation: running"
        error = subprocess.TimeoutExpired(cmd=["pipeline"], timeout=1800, output=out, stderr=b"stderr tail")
        with mock.patch("web.worker.subprocess.run", side_effect=error), \
                mock.patch.object(worker, "_write_blob_outcome") as outcome, \
                mock.patch("web.queries.update_job_status") as update, mock.patch("builtins.print"):
            worker._run_job(dict(self.JOB))
        message = update.call_args.kwargs["error_message"]
        kept, _, last = message.rpartition("\n\n")
        self.assertEqual(last, "Worker error: Command '['pipeline']' timed out after 1800 seconds")
        self.assertEqual(len(kept), worker.TIMEOUT_OUTPUT_CHARS)
        self.assertTrue(kept.endswith("Validation: running\nstderr tail"))
        self.assertIn("Step timing: ai_call=300.0s", kept)
        self.assertEqual(outcome.call_args.args[1:], ("failed", message))

    def test_completed_job_prints_each_step_line_once_while_running(self):
        printed, kwargs, _ = self._run(CHILD_OK, 30, get_silver_row_count=3, get_vendor_name_for_statement="V")
        steps = [(t, line) for t, line in printed if line.startswith("[worker] Job J1: Step timing:")]
        self.assertEqual([line for _, line in steps], ["[worker] Job J1: Step timing: pdf_text=1.0s"])
        done = next(t for t, line in printed if "COMPLETED" in line)
        self.assertLess(steps[0][0], done - 1.0)   # printed while the pipeline was still running
        self.assertEqual(kwargs["status"], "COMPLETED")


class TestEngineStepTimings(unittest.TestCase):

    def test_orientation_and_ai_call_timings_are_printed(self):
        from src.ai.base_client import AIResponse
        client = mock.Mock()
        client.generate_with_file.return_value = AIResponse(success=True, parsed_json={"invoices": []},
                                                            provider="test", model="m")
        lines = []
        with mock.patch.object(due.client_factory, "get_ai_client", return_value=client), \
                mock.patch.object(due, "upright_copy", side_effect=lambda p: (p, {})), \
                mock.patch.object(due, "log_ai_call"), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: lines.append(" ".join(map(str, a)))):
            due.DocumentUnderstandingEngine().understand("", __file__)
        self.assertTrue(any(l.startswith("    Step timing: orientation=") for l in lines), lines)
        self.assertTrue(any(l.startswith("    Step timing: ai_call=") for l in lines), lines)


if __name__ == "__main__":
    unittest.main()
