"""Several account statements in one PDF (pdf_account_blocks: src/validation/account_blocks.py, wired into
notebooks/01_document_intake.py after the no-total rule, 2026-10-20), and the single signed
"Purchase/Payments Amount" column in claude_sonnet_client._map_columns.

Synthetic tests build a text-layer PDF with PyMuPDF in Lithia's layout: "STATEMENT PAGE k of N", an aging
line ending in "Total Amount Due" with its amount printed under the label, the transaction table
(Date / Transaction Type / Reference/Invoice / Purchase/Payments Amount / Balance Due), the account's
section line, and a remittance stub restating the Amount Due. TestLithia / TestOnlyLithia use the stored
extraction and PDF in scratchpad/ (real data, git-ignored) and skip where those files are not present."""
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
from test_pdf_row_match import _PdfCase, row, write_pdf  # noqa: E402
from test_text_columns import Q10, _stored, schema, to_invoices  # noqa: E402

from src.ai.claude_sonnet_client import ClaudeSonnetClient, is_signed_amount_header  # noqa: E402
from src.validation import account_blocks as ab  # noqa: E402
from src.validation.arithmetic_gate import compute_statement_total_from_invoices  # noqa: E402

LITHIA = "STMT-142DA134"
X = {"date": 40, "type": 110, "ref": 200, "amount": 300, "bal": 480}
TX_HEADER = (("date", "Date"), ("type", "Transaction Type"), ("ref", "Reference/Invoice"),
             ("amount", "Purchase/Payments Amount"), ("bal", "Balance Due"))
# (date, type, reference, printed signed amount)
ALPHA = [("07/30/2026", "Parts Sale", "243925", "$543.88"), ("08/12/2026", "Parts Sale", "CM243925", "($296.40)"),
         ("08/14/2026", "Payment", "243925", "($543.88)"), ("08/11/2026", "Parts Sale", "244770", "$759.03")]  # 462.63
BETA = [("07/01/2026", "Parts Sale", "115014", "$107.59"), ("08/18/2026", "Payment", "115014", "($107.59)"),
        ("08/14/2026", "Parts Sale", "115810", "$1,538.14")]                                              # 1,538.14
TERMS = [(40, 100 + 14 * k, "Finance charges apply if the balance showing due is unpaid by the next statement")
         for k in range(3)]


def account_page(name, account, total, lines, marker="1 of 1", label=True, stub=True):
    """One account statement page in Lithia's layout; total is the printed Total Amount Due text."""
    items = [(40, 60, name), (450, 60, account), (300, 100, "Current")]
    if marker:
        items.append((450, 40, f"STATEMENT PAGE {marker}"))
    if label:
        items += [(480, 100, "Total Amount Due"), (300, 114, "$0.00"), (490, 114, total)]
    items += [(X[k], 150, text) for k, text in TX_HEADER]
    items += [(40, 164, name), (490, 164, total)]
    y = 180
    for date, kind, ref, amount in lines:
        items += [(X["date"], y, date), (X["type"], y, kind), (X["ref"], y, ref), (X["amount"], y, amount)]
        y += 14
    if stub:
        items += [(480, 600, "Amount Due"), (300, 612, "Company No."),
                  (300, 624, "768"), (340, 624, account), (400, 624, "09/03/2026"), (490, 624, total)]
    return items


def rows_for(lines):
    out = []
    for date, _, ref, amount in lines:
        value = float(amount.strip("$()").replace(",", ""))
        out.append(row(ref, date, credit=value) if amount.startswith("(") else row(ref, date, value))
    return out


class _Case(_PdfCase):

    def check(self, pages, rows):
        return ab.check_pdf_account_blocks(rows, self.pdf(pages), compute_statement_total_from_invoices(rows))

    def two_blocks(self, alpha_total="$462.63", alpha=ALPHA, beta=BETA, **beta_kw):
        return [account_page("Alpha Motors", "ACC100", alpha_total, alpha), TERMS,
                account_page("Beta Motors", "ACC200", "$1,538.14", beta, **beta_kw)]


class TestSynthetic(_Case):

    def test_both_blocks_correct_pass_and_are_recorded(self):
        out = self.check(self.two_blocks(), rows_for(ALPHA + BETA))
        self.assertTrue(out["passed"], out.get("reason"))
        self.assertEqual([(b["name"], b["pages"], b["printed_total_amount_due"], b["rows"], b["rows_signed_sum"])
                          for b in out["blocks"]],
                         [("Alpha Motors", "1", 462.63, 4, 462.63), ("Beta Motors", "3", 1538.14, 3, 1538.14)])
        self.assertEqual((out["printed_total"], out["computed"]), (2000.77, 2000.77))
        self.assertEqual(out["printed_total_is"], "the sum of the account blocks' printed Total Amount Due")
        self.assertEqual([(r["page"], r["amount"]) for r in out["restated_totals"]], [(1, 462.63), (3, 1538.14)])

    def test_a_block_continued_on_page_2_of_2_passes(self):
        pages = [account_page("Alpha Motors", "ACC100", "$462.63", ALPHA),
                 account_page("Beta Motors", "ACC200", "$1,538.14", BETA[:2], marker="1 of 2"),
                 account_page("Beta Motors", "ACC200", "$1,538.14", BETA[2:], marker="2 of 2", stub=False)]
        out = self.check(pages, rows_for(ALPHA + BETA))
        self.assertTrue(out["passed"], out.get("reason"))
        self.assertEqual([(b["pages"], b["rows"]) for b in out["blocks"]], [("1", 4), ("2-3", 3)])

    def test_one_blocks_rows_one_cent_off_its_total_fail(self):
        out = self.check(self.two_blocks(alpha_total="$462.64"), rows_for(ALPHA + BETA))
        self.assertFalse(out["passed"])
        self.assertIn("rows sum to 462.63, printed Total Amount Due 462.64", out["reason"])

    def test_a_row_printed_in_no_block_fails(self):
        stray = [(X["date"], 200, "08/20/2026"), (X["type"], 200, "Parts Sale"), (X["ref"], 200, "115896"),
                 (X["amount"], 200, "$194.35")] + TERMS
        out = self.check(self.two_blocks() + [stray], rows_for(ALPHA + BETA) + [row("115896", "08/20/2026", 194.35)])
        self.assertFalse(out["passed"])
        self.assertIn("115896 is printed on page 4, in no account block", out["reason"])

    def test_a_block_with_no_printed_total_fails(self):
        out = self.check(self.two_blocks(label=False), rows_for(ALPHA + BETA))
        self.assertTrue(out["applicable"])
        self.assertFalse(out["passed"])
        self.assertIn("the account block starting on page 3 prints no Total Amount Due", out["reason"])

    def test_two_printed_lines_with_the_same_identity_fail(self):
        twice = ALPHA + [ALPHA[3]]
        for rows in (rows_for(twice), rows_for(ALPHA)):
            with self.subTest(rows=len(rows)):
                out = self.check(self.two_blocks(alpha_total="$1,221.66", alpha=twice), rows + rows_for(BETA))
                self.assertFalse(out["passed"])
                self.assertIn("ambiguous", out["reason"])

    def test_a_printed_line_with_no_row_fails(self):
        out = self.check(self.two_blocks(), rows_for(ALPHA[:3] + BETA))
        self.assertFalse(out["passed"])
        self.assertIn("printed line not extracted (p1)", out["reason"])

    def test_a_row_with_no_printed_line_fails(self):
        out = self.check(self.two_blocks(), rows_for(ALPHA + BETA) + [row("999999", "08/20/2026", 10.0)])
        self.assertFalse(out["passed"])
        self.assertIn("no printed transaction line with its reference", out["reason"])

    def test_a_scan_is_not_applicable(self):
        doc = fitz.open()
        for _ in range(2):
            page = doc.new_page(width=612, height=792)
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), 0)
            pix.clear_with(200)
            page.insert_image(fitz.Rect(30, 30, 300, 300), pixmap=pix)
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        self.addCleanup(os.remove, f.name)
        rows = rows_for(ALPHA + BETA)
        out = ab.check_pdf_account_blocks(rows, f.name, compute_statement_total_from_invoices(rows))
        self.assertFalse(out["applicable"])
        self.assertIn("not a text-layer PDF", out["reason"])

    def test_a_single_account_pdf_is_not_applicable(self):
        out = self.check([account_page("Alpha Motors", "ACC100", "$462.63", ALPHA), TERMS], rows_for(ALPHA))
        self.assertFalse(out["applicable"])

    def test_charges_minus_credits_must_equal_the_blocks_sum(self):
        rows = rows_for(ALPHA + BETA)
        out = ab.check_pdf_account_blocks(rows, self.pdf(self.two_blocks()), 2000.78)
        self.assertFalse(out["passed"])
        self.assertIn("is not the blocks' printed total 2,000.77", out["reason"])


class TestIntake(_Case):

    def gate(self, pages, rows, printed=None):
        intake = load_intake()
        path = self.pdf(pages)
        s = schema(rows, printed, vendor="Synthetic Group")
        with mock.patch("builtins.print"):
            text = intake.extract_pdf_text(path)[0]
            return s, intake.apply_arithmetic_validation(s, text, path)

    def test_a_correct_two_block_statement_passes_after_the_no_total_rule(self):
        s, v = self.gate(self.two_blocks(), rows_for(ALPHA + BETA))
        self.assertEqual((v["status"], v["method"], v["printed"], v["computed"], v["difference"]),
                         ("matches", "pdf_account_blocks", 2000.77, 2000.77, 0.0))
        self.assertIn("rows_only", v["detail"])
        self.assertIsNone(s["statement_metadata"]["statement_total_as_printed"])
        self.assertEqual(len(v["detail"]["account_blocks"]["blocks"]), 2)

    def test_a_failing_block_stays_total_not_found_with_the_reason(self):
        s, v = self.gate(self.two_blocks(alpha_total="$462.64"), rows_for(ALPHA + BETA))
        self.assertEqual((v["status"], v["method"]), ("total_not_found", None))
        self.assertIn("printed Total Amount Due 462.64", v["detail"]["account_blocks"]["reason"])

    def test_a_statement_with_a_printed_total_never_takes_the_check(self):
        intake = load_intake()
        validation = {"status": "mismatch", "printed": 100.0, "computed": 2000.77, "difference": -1900.77,
                      "method": None, "detail": None}
        self.assertIs(intake._account_blocks_status(validation, rows_for(ALPHA + BETA), self.pdf(self.two_blocks())),
                      validation)


class TestSignedColumn(unittest.TestCase):
    COLUMNS = ["Date", "Reference/Invoice", "Purchase/Payments Amount", "Payment Applied", "Balance Due"]
    RAW = [{"Date": "07/30/2026", "Reference/Invoice": "1001", "Purchase/Payments Amount": 543.88},
           {"Date": "08/12/2026", "Reference/Invoice": "CM1001", "Purchase/Payments Amount": -296.40},
           {"Date": "08/14/2026", "Reference/Invoice": "1001", "Purchase/Payments Amount": -543.88,
            "Payment Applied": "MC081426", "Balance Due": -296.40},
           {"Date": "08/11/2026", "Reference/Invoice": "1002", "Purchase/Payments Amount": 759.03, "Balance Due": 759.03}]

    def test_the_header_rule(self):
        for header in ("purchase/payments amount", "charges/payments", "charges and credits", "invoice / credit"):
            self.assertTrue(is_signed_amount_header(header), header)
        for header in ("payments", "payment", "charge", "purchases", "payment applied", "credit applied",
                       "invoice credit #", "payment date", "charges"):
            self.assertFalse(is_signed_amount_header(header), header)

    def test_a_single_signed_column_computes_charges_minus_credits_as_the_signed_sum(self):
        client = ClaudeSonnetClient.__new__(ClaudeSonnetClient)
        self.assertEqual(client._map_columns(self.COLUMNS, self.RAW)["signed_amount"], "Purchase/Payments Amount")
        with mock.patch("builtins.print"):
            invoices = to_invoices(self.RAW, self.COLUMNS)
        self.assertEqual([(i["charges"], i["credit"]) for i in invoices],
                         [(543.88, None), (None, 296.40), (None, 543.88), (759.03, None)])
        self.assertEqual([i["amount_due"] for i in invoices], [None, None, -296.40, 759.03])
        signed_sum = round(sum(r["Purchase/Payments Amount"] for r in self.RAW), 2)
        self.assertEqual(compute_statement_total_from_invoices(invoices), signed_sum)
        self.assertEqual(signed_sum, 462.63)


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class TestLithia(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.st = _stored()[LITHIA]
        if not (cls.st.get("pdf") and os.path.exists(cls.st["pdf"])):
            raise unittest.SkipTest("Lithia PDF not on disk")

    def setUp(self):
        from src.validation import pdf_row_match
        pdf_row_match._PAGES_CACHE.clear()

    def gate(self, change=None, pdf=None):
        rows = copy.deepcopy(self.st["rows"])
        if change:
            change(rows)
        with mock.patch("builtins.print"):
            invoices = to_invoices(rows, [k for k in self.st["keys"] if k != "confidence"])
        intake = load_intake()
        path = pdf or self.st["pdf"]
        s = schema(invoices, self.st["printed"], vendor=self.st["vendor"])
        with mock.patch("builtins.print"):
            return s, intake.apply_arithmetic_validation(s, intake.extract_pdf_text(path)[0], path)

    def test_the_stored_rows_compute_their_signed_sum(self):
        with mock.patch("builtins.print"):
            invoices = to_invoices(self.st["rows"], [k for k in self.st["keys"] if k != "confidence"])
        self.assertEqual(compute_statement_total_from_invoices(invoices), 3779.91)
        self.assertEqual(round(sum(r["Purchase/Payments Amount"] for r in self.st["rows"]), 2), 3779.91)

    def test_lithia_passes_by_its_two_account_blocks(self):
        s, v = self.gate()
        self.assertEqual((v["status"], v["method"], v["printed"], v["computed"], v["difference"]),
                         ("matches", "pdf_account_blocks", 3779.91, 3779.91, 0.0))
        self.assertIsNone(s["statement_metadata"]["statement_total_as_printed"])
        self.assertEqual(v["detail"]["rows_only"]["status"], "has_printed_total")
        out = v["detail"]["account_blocks"]
        self.assertEqual([(b["name"], b["pages"], b["printed_total_amount_due"], b["rows"], b["rows_signed_sum"])
                          for b in out["blocks"]],
                         [("Prestige Ramsey Lexus", "1", 816.12, 7, 816.12), ("DCH Freehold BMW", "3-4", 2963.79, 13, 2963.79)])
        self.assertEqual((out["rows_verified"], out["pdf_transaction_lines"]), (20, 20))
        self.assertEqual([(r["page"], r["amount"]) for r in out["restated_totals"]], [(1, 816.12), (3, 2963.79)])

    def assert_fails(self, v):
        self.assertEqual((v["status"], v["method"]), ("total_not_found", None))
        self.assertFalse(v["detail"]["account_blocks"]["passed"])

    def test_mutations_fail(self):
        def digit(rows):
            rows[3]["Purchase/Payments Amount"] = 759.13

        def drop(rows):
            rows.pop(5)

        def duplicate(rows):
            rows.insert(4, dict(rows[4]))

        def flip_payment(rows):   # 243925's 543.88 payment read as a 543.88 sale
            rows[2]["Purchase/Payments Amount"] = 543.88
        for name, fn in (("changed digit", digit), ("dropped row", drop), ("duplicated row", duplicate),
                         ("payment sign flipped", flip_payment)):
            with self.subTest(mutation=name):
                self.assert_fails(self.gate(fn)[1])

    def test_a_printed_line_moved_into_the_other_accounts_block_fails(self):
        # 245150 (08/17/2026, 13.94) removed from page 1 and printed under DCH Freehold BMW's last line on page 3.
        doc = fitz.open(self.st["pdf"])
        words = doc[0].get_text("words")
        anchor = next(w for w in words if w[4] == "245150")
        line = [w for w in words if abs((w[1] + w[3]) / 2 - (anchor[1] + anchor[3]) / 2) < 3]
        doc[0].add_redact_annot(fitz.Rect(min(w[0] for w in line) - 1, anchor[1] - 1,
                                          max(w[2] for w in line) + 1, anchor[3] + 1))
        doc[0].apply_redactions()
        for w in line:
            doc[2].insert_text((w[0], 519), w[4], fontsize=7)
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        doc.save(f.name)
        self.addCleanup(os.remove, f.name)
        s, v = self.gate(pdf=f.name)
        self.assert_fails(v)
        self.assertIn("Prestige Ramsey Lexus (pages 1): rows sum to 802.18, printed Total Amount Due 816.12",
                      v["detail"]["account_blocks"]["reason"])


@unittest.skipUnless(os.path.exists(Q10), "saved replay data not present")
class TestOnlyLithia(unittest.TestCase):

    def test_the_check_passes_no_other_stored_statement(self):
        from src.validation import pdf_row_match
        passed, applicable = set(), {}
        for sid, st in _stored().items():
            if not (st.get("pdf") and os.path.exists(st["pdf"])) or not st["rows"]:
                continue
            if st["engine"] == "claude_sonnet":
                with mock.patch("builtins.print"):
                    invoices = to_invoices(st["rows"], [k for k in st["keys"] if k != "confidence"])
            else:   # python-library rows: block structure and row matching are decided on the PDF
                invoices = [{"_raw_row": dict(r)} for r in st["rows"]]
            pdf_row_match._PAGES_CACHE.clear()
            rows = [i for i in invoices if not i.get("informational")]
            out = ab.check_pdf_account_blocks(rows, st["pdf"], compute_statement_total_from_invoices(invoices))
            if out["applicable"]:
                applicable[sid] = out["reason"]
            if out["passed"]:
                passed.add(sid)
        self.assertEqual(passed, {LITHIA})
        self.assertEqual(set(applicable), {LITHIA}, applicable)


class TestDetailPage(unittest.TestCase):
    BLOCKS = {"applicable": True, "passed": True, "reason": "", "printed_total": 3779.91,
              "printed_total_is": "the sum of the account blocks' printed Total Amount Due",
              "blocks": [{"name": "Prestige Ramsey Lexus", "pages": "1", "printed_total_amount_due": 816.12,
                          "rows": 7, "rows_signed_sum": 816.12},
                         {"name": "DCH Freehold BMW", "pages": "3-4", "printed_total_amount_due": 2963.79,
                          "rows": 13, "rows_signed_sum": 2963.79}]}

    def test_the_blocks_are_shown(self):
        import test_pdf_row_match as prm
        page = prm.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "L", "source_file": "lithia.pdf", "vendor_name": "Lithia", "statement_period": "2026-09",
                  "statement_total_as_printed": None, "validation_status": "matches", "validation_difference": 0.0,
                  "validation_method": "pdf_account_blocks", "previous_balance": None, "previous_balance_source": None,
                  "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": True, "primary_computed": None,
                  "validation_attempts": [], "account_blocks": self.BLOCKS}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": 3779.91, "lines": []})
        try:
            html = page._client().get("/validation/L").text
        finally:
            page.doCleanups()
        self.assertIn('id="account-blocks"', html)
        self.assertIn("PDF account blocks (each account&#39;s own printed total)", html)
        self.assertIn("This PDF holds 2 account statements", html)
        self.assertIn("Sum of 2 account blocks' printed totals", html)
        for text in ("Prestige Ramsey Lexus", "DCH Freehold BMW", "3-4", "$816.12", "$2,963.79", "$3,779.91"):
            self.assertIn(text, html)

    def test_the_query_reads_the_blocks_and_their_sum(self):
        from web import queries
        row_ = {"statement_id": "L", "source_file": "lithia.pdf", "vendor_name": "Lithia", "statement_period": "2026-09",
                "statement_total_as_printed": None, "validation_status": "matches", "validation_difference": 0.0,
                "validation_method": "pdf_account_blocks", "validation_detail": json.dumps({"account_blocks": self.BLOCKS}),
                "previous_balance": None, "previous_balance_source": None, "ingestion_timestamp": "2026-10-01"}
        with mock.patch.object(queries, "execute_query", lambda sql, params=None: [dict(row_)]), \
             mock.patch.object(queries, "recon_query", lambda sql, params=None: []):
            data = queries.get_extraction_validation_detail("L")
        self.assertEqual(data["intake"]["account_blocks"]["blocks"][1]["pages"], "3-4")
        self.assertIsNone(data["intake"]["statement_total_as_printed"])
        self.assertEqual(data["computed_total"], 3779.91)


if __name__ == "__main__":
    unittest.main()
