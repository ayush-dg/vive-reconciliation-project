"""Printed total from bare BALANCE / NET DUE boxes (src/validation/printed_total.py find_box_total, used by
notebooks/01_document_intake.py _fill_printed_total only when the text has no total-labelled amount at
all, 2026-10-21).

Synthetic tests build text-layer PDFs with PyMuPDF (a header box label with its amount printed in the cell
below). TestGroove / TestOnlyGroove use the stored extraction and PDF in scratchpad/ (real data,
git-ignored; skipped where absent); Groove is a scan, read by Tesseract (the cached intake OCR text is
byte-identical to a fresh read)."""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_oct1_intake_worker_web import load_intake  # noqa: E402
from test_text_columns import Q10, _stored, schema, to_invoices  # noqa: E402

from src.validation import pdf_row_match as prm  # noqa: E402
from src.validation import printed_total as pt  # noqa: E402

GROOVE = "STMT-B9D084C8"
OCR_CACHE = os.path.join(os.path.dirname(Q10), "q7_ocr_text.json")
FILLER = [(40, 300 + 14 * k, f"08/{k + 1:02d}/26 Invoice 10{k:04d} for parts and labour") for k in range(4)]


def box_page(value="21976.51", label="BALANCE", value_dy=14, extra=()):
    """A page with a header box: label (small) and its value printed in the cell below."""
    items = [(40, 60, "STATEMENT OF ACCOUNT"), (400, 100, label), (500, 100, "AMOUNT PAID")]
    if value is not None:
        items.append((400, 100 + value_dy, value))
    return items + FILLER + list(extra)


def write(pages):
    doc = fitz.open()
    for items in pages:
        page = doc.new_page(width=612, height=792)
        for x, y, text in items:
            page.insert_text((x, y), text, fontsize=8)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    return f.name


class _Case(unittest.TestCase):
    def setUp(self):
        prm._PAGES_CACHE.clear()
        pt._BOX_CACHE.clear()

    def read(self, pages):
        path = write(pages)
        self.addCleanup(os.remove, path)
        return pt.find_box_total(path)


class TestSynthetic(_Case):

    def test_two_agreeing_places_are_found(self):
        out = self.read([box_page(), box_page()])
        self.assertEqual(out["amount"], 21976.51)
        self.assertEqual([(p["page"], p["label"], p["read"]) for p in out["places"]],
                         [(1, "BALANCE", "printed under"), (2, "BALANCE", "printed under")])

    def test_two_different_labels_on_one_page_count_as_two_places(self):
        out = self.read([box_page(extra=[(480, 400, "NET DUE"), (480, 414, "21976.51")])])
        self.assertEqual(out["amount"], 21976.51)

    def test_one_place_only_is_not_found(self):
        self.assertIsNone(self.read([box_page(), box_page(value=None)]))

    def test_two_different_amounts_are_not_found(self):
        self.assertIsNone(self.read([box_page(), box_page(), box_page(value="21976.15")]))

    def test_a_value_far_from_the_label_is_not_found(self):
        self.assertIsNone(self.read([box_page(value_dy=60), box_page(value_dy=60)]))

    def test_zero_values_are_ignored(self):
        out = self.read([box_page(), box_page(value="0.00"), box_page()])
        self.assertEqual(out["amount"], 21976.51)

    def test_a_label_inside_a_phrase_is_not_a_box(self):
        for label in ("Balance Due", "DATE OF BALANCE", "NET DUE 30 DAYS"):
            with self.subTest(label=label):
                self.assertIsNone(self.read([box_page(label=label), box_page(label=label)]))

    def test_a_column_of_amounts_under_a_header_is_not_a_box(self):
        column = [(400, 114 + 14 * k, f"{100 + k}.00") for k in range(1, 4)]
        self.assertIsNone(self.read([box_page(extra=column), box_page(extra=column)]))

    def test_a_value_on_the_labels_own_line_counts(self):
        same = [(40, 60, "STATEMENT OF ACCOUNT"), (400, 100, "BALANCE"), (440, 100, "21976.51")] + FILLER
        out = self.read([same, same])
        self.assertEqual([p["read"] for p in out["places"]], ["same line", "same line"])


class TestIntakeRule(_Case):
    """_fill_printed_total: the old labels decide whenever they print any amount."""

    def fill(self, text, pdf_path="x.pdf"):
        meta = {"statement_total_as_printed": None}
        with mock.patch.object(load_intake(), "find_box_total", return_value={"amount": 1.0, "places": [{"page": 1, "label": "BALANCE"}, {"page": 2, "label": "BALANCE"}]}) as box, \
                mock.patch("builtins.print"):
            out = load_intake()._fill_printed_total(meta, text, "ocr", pdf_path)
        return meta["statement_total_as_printed"], out, box.called

    def test_an_old_label_text_gives_the_same_result_as_before(self):
        for text in ("Total due 3425.00\nBalance due 3425.00", "PLEASE PAY THIS AMOUNT 4,484.09"):
            with self.subTest(text=text):
                printed, (source, places), called = self.fill(text)
                self.assertEqual((printed, source, places, called), (pt.find_printed_total(text), "ocr", None, False))

    def test_old_labels_that_disagree_give_no_total_and_never_reach_the_box_reader(self):
        printed, out, called = self.fill("Total due 100.00\nBalance due 200.00")
        self.assertEqual((printed, out, called), (None, (None, None), False))

    def test_no_old_label_amount_tries_the_boxes(self):
        printed, (source, places), called = self.fill("BALANCE AMOUNT PAID\nnothing else")
        self.assertEqual((printed, source, called), (1.0, "pdf_box_labels", True))

    def test_an_extracted_total_is_never_replaced(self):
        meta = {"statement_total_as_printed": 5.0}
        self.assertEqual(load_intake()._fill_printed_total(meta, "BALANCE", "ocr", "x.pdf"), (None, None))
        self.assertEqual(meta["statement_total_as_printed"], 5.0)


@unittest.skipUnless(os.path.exists(Q10) and os.path.exists(OCR_CACHE), "saved replay data not present")
class TestGroove(_Case):

    @classmethod
    def setUpClass(cls):
        cls.st = _stored()[GROOVE]
        if not (cls.st.get("pdf") and os.path.exists(cls.st["pdf"])):
            raise unittest.SkipTest("Groove PDF not on disk")
        with open(OCR_CACHE, encoding="utf-8") as f:
            cls.ocr = json.load(f)[GROOVE]

    def gate(self, change=None):
        rows = copy.deepcopy(self.st["rows"])
        if change:
            change(rows)
        with mock.patch("builtins.print"):
            invoices = to_invoices(rows, [k for k in self.st["keys"] if k != "confidence"])
        intake = load_intake()
        s = schema(invoices, None, vendor=self.st["vendor"])
        with mock.patch.object(intake, "ocr_pdf_text", return_value=self.ocr), mock.patch("builtins.print"):
            return s, intake.apply_arithmetic_validation(s, intake.extract_pdf_text(self.st["pdf"])[0], self.st["pdf"])

    def test_groove_passes_with_its_printed_total(self):
        s, v = self.gate()
        self.assertEqual((v["status"], v["method"], v["printed"], v["computed"], v["difference"]),
                         ("matches", "primary", 21976.51, 21976.51, 0.0))
        self.assertEqual(s["statement_metadata"]["statement_total_as_printed"], 21976.51)
        self.assertEqual(v["detail"]["printed_total_source"], "pdf_box_labels")
        self.assertEqual([(p["page"], p["label"]) for p in v["detail"]["printed_total_read_from"]],
                         [(2, "BALANCE"), (3, "BALANCE"), (3, "NET DUE")])

    def test_row_mutations_fail(self):
        def digit(rows):
            rows[9]["AMOUNT"] = 3071.37

        def drop(rows):
            rows.pop(20)

        def duplicate(rows):
            rows.insert(5, dict(rows[5]))
        for name, fn in (("changed digit", digit), ("dropped row", drop), ("duplicated row", duplicate)):
            with self.subTest(mutation=name):
                self.assertEqual(self.gate(fn)[1]["status"], "mismatch")

    def test_one_printed_total_read_differently_gives_no_total(self):
        real_lines, real_ocr = prm.read_pdf_lines, prm._Rereader._ocr

        def net_due_misread(*a, **k):
            pages = copy.deepcopy(real_lines(*a, **k))
            for line in pages[2]["lines"]:
                for w in line["words"]:
                    if w["text"] == "21976.51" and w["x0"] > 500:
                        w["text"] = "21976.15"
            return pages

        def box_misread(self_, page, *a, **k):
            got = real_ocr(self_, page, *a, **k)
            return [{**w, "text": "21976.15"} for w in got] if page == 2 and got else got
        for name, patch in (("NET DUE read 21976.15", mock.patch.object(prm, "read_pdf_lines", net_due_misread)),
                            ("page 2 BALANCE re-read 21976.15", mock.patch.object(prm._Rereader, "_ocr", box_misread))):
            with self.subTest(mutation=name), patch:
                pt._BOX_CACHE.clear()
                s, v = self.gate()
                self.assertEqual(v["status"], "total_not_found")
                self.assertIsNone(s["statement_metadata"]["statement_total_as_printed"])


@unittest.skipUnless(os.path.exists(Q10) and os.path.exists(OCR_CACHE), "saved replay data not present")
class TestOnlyGroove(_Case):

    def test_the_box_reader_fills_no_other_stored_statement(self):
        import pdfplumber
        from src.validation.previous_balance import has_text_layer
        with open(OCR_CACHE, encoding="utf-8") as f:
            ocr = json.load(f)
        found, reached = {}, []
        for sid, st in _stored().items():
            if st["printed"] is not None or not (st.get("pdf") and os.path.exists(st["pdf"])):
                continue
            with pdfplumber.open(st["pdf"]) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            if not has_text_layer(text):
                text = ocr.get(sid) or ""
            if not text or pt.labelled_amounts(text):
                continue   # no text to read, or the old labels decide (unchanged)
            reached.append(sid)
            prm._PAGES_CACHE.clear()
            box = pt.find_box_total(st["pdf"])
            if box is not None:
                found[sid] = box["amount"]
        self.assertIn("STMT-1880E21C", reached)   # Healey passes by pdf_rows_no_total and must stay so
        self.assertEqual(found, {GROOVE: 21976.51})


class TestDetailPage(unittest.TestCase):

    def test_the_reading_places_are_shown_next_to_the_printed_total(self):
        import test_pdf_row_match as prm_tests
        page = prm_tests.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "G", "source_file": "g.pdf", "vendor_name": "Berlin City", "statement_period": "2026-09",
                  "statement_total_as_printed": 21976.51, "validation_status": "matches", "validation_difference": 0.0,
                  "validation_method": "primary", "previous_balance": None, "previous_balance_source": None,
                  "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": True, "primary_computed": None,
                  "validation_attempts": [],
                  "printed_total_read_from": [{"page": 2, "label": "BALANCE", "amount": 21976.51, "read": "re-read under the label"},
                                              {"page": 3, "label": "BALANCE", "amount": 21976.51, "read": "re-read under the label"},
                                              {"page": 3, "label": "NET DUE", "amount": 21976.51, "read": "printed under"}]}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": 21976.51, "lines": []})
        try:
            html = page._client().get("/validation/G").text
        finally:
            page.doCleanups()
        self.assertIn('id="printed-total-read-from"', html)
        self.assertIn("Read from the PDF: BALANCE p2, BALANCE p3, NET DUE p3", html)

    def test_the_query_reads_the_places(self):
        from web import queries
        detail = {"printed_total_source": "pdf_box_labels",
                  "printed_total_read_from": [{"page": 2, "label": "BALANCE", "amount": 21976.51, "read": "x"}]}
        row = {"statement_id": "G", "source_file": "g.pdf", "vendor_name": "Berlin City", "statement_period": "2026-09",
               "statement_total_as_printed": 21976.51, "validation_status": "matches", "validation_difference": 0.0,
               "validation_method": "primary", "validation_detail": json.dumps(detail), "previous_balance": None,
               "previous_balance_source": None, "ingestion_timestamp": "2026-10-01"}
        with mock.patch.object(queries, "execute_query", lambda sql, params=None: [dict(row)]), \
             mock.patch.object(queries, "recon_query", lambda sql, params=None: []):
            data = queries.get_extraction_validation_detail("G")
        self.assertEqual(data["intake"]["printed_total_read_from"][0]["label"], "BALANCE")
        self.assertEqual(data["computed_total"], 21976.51)


if __name__ == "__main__":
    unittest.main()
