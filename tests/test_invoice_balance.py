"""Invoice-balance check (src/validation/arithmetic_gate.py check_invoice_balance /
apply_invoice_balance_check, 2026-10-19) and its failure text (src/validation/gate.py).

The unit tests use synthetic rows. TestRocklandRuns replays the three saved AI
extractions of Fred Beans Rockland (STMT-6A9842BA) from scratchpad/rerun_ai/ -- real
vendor data, git-ignored, so those tests skip where the files are not present."""
import copy
import glob
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # test_pdf_row_match's page helpers

from src.validation import arithmetic_gate as g
from src.validation.gate import describe_failure

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROCKLAND = sorted(glob.glob(os.path.join(REPO, "scratchpad", "rerun_ai", "ai_extraction_STMT-6A9842BA_*.json")))


def charge(inv, amount, due=None, row=None):
    return {"invoice_number": inv, "outstanding_amount": amount, "amount": amount, "amount_due": due, "row_number": row}


def credit(inv, amount, due=None, row=None):
    return {"invoice_number": inv, "credit": amount, "amount_due": due, "row_number": row}


def flags_of(invoices):
    report = g.check_invoice_balance(invoices)
    return None if report is None else sorted((f["rule"], f["invoice_number"]) for f in report["flags"])


class TestRefinements(unittest.TestCase):

    def test_credit_memo_with_a_trailing_letter_groups_with_its_invoice(self):
        # Rockland 9460269: 2,149.15 - 125 (CM9460269) - 75 (CM9460269A) - 200 - 1,949.15 = -200 = due
        rows = [charge("9460269", 2149.15), credit("CM9460269", 125.0), credit("CM9460269A", 75.0),
                credit("9460269", 200.0), credit("9460269", 1949.15, due=-200.0)]
        self.assertEqual(flags_of(rows), [])
        self.assertEqual(g._balance_group_key("CM9460269A"), "9460269")
        self.assertEqual(g._balance_group_key("CM9485340"), "9485340")
        self.assertEqual(g._balance_group_key("9417731X3"), "9417731X3")   # not a credit memo: kept
        self.assertEqual(g._balance_group_key("INV100A"), "INV100A")       # plain invoice letter: kept
        self.assertIsNone(g._balance_group_key("ROA"))

    def test_without_the_letter_rule_that_invoice_would_not_net(self):
        rows = [charge("9460269", 2149.15), credit("CM9460269", 125.0), credit("CM9460269B9", 75.0),
                credit("9460269", 200.0), credit("9460269", 1949.15, due=-200.0)]
        self.assertEqual(flags_of(rows), [(g.INVOICE_BALANCE_RULE_INVOICE, "9460269")])

    def test_due_covering_a_balanced_invoice_is_exempt_from_the_row_rule(self):
        # Rockland 942002: 22.67 + 34.34 = 57.01, printed once on the last line
        rows = [charge("942002", 22.67), charge("942002", 34.34, due=57.01)]
        self.assertEqual(flags_of(rows), [])

    def test_no_exemption_when_the_invoice_does_not_balance(self):
        rows = [charge("942002", 22.67), charge("942002", 34.34, due=60.00)]
        self.assertEqual(flags_of(rows), [(g.INVOICE_BALANCE_RULE_ROW_EXCEEDS, "942002"),
                                          (g.INVOICE_BALANCE_RULE_INVOICE, "942002")])

    def test_no_exemption_when_the_due_has_the_other_sign_than_the_invoice(self):
        # the invoice nets (+50 - 40 = +10 = 60 - 50), so the charge row's 60 is exempt (same sign as the
        # invoice), but the credit row's -50 has the other sign and is more than its own 40: flagged
        rows = [charge("777", 50.0, due=60.0, row=1), credit("777", 40.0, due=-50.0, row=2)]
        report = g.check_invoice_balance(rows)
        self.assertEqual([(f["rule"], f["row_number"]) for f in report["flags"]],
                         [(g.INVOICE_BALANCE_RULE_ROW_EXCEEDS, 2)])

    def test_due_on_a_row_with_no_amount_is_always_flagged(self):
        # Rockland 9391887 (carry run): the 113.20 credit read into AMOUNT DUE -- the invoice still
        # "nets" because the credit left the rows and entered the due by the same amount
        rows = [charge("9391887", 452.64), credit("9391887", 339.44), {"invoice_number": "9391887", "amount_due": 113.2},
                charge("9391887", 71.13), charge("9391887", 72.24), charge("9391887", 196.07, due=339.44)]
        self.assertEqual(flags_of(rows), [(g.INVOICE_BALANCE_RULE_DUE_ONLY, "9391887")])

    def test_a_balance_only_line_of_its_own_is_not_flagged(self):
        # Healey 1401474: no Amount, only Balance -100.54, on a line of its own (a real layout)
        rows = [charge("CM6237539", -4.67, due=-4.67), charge("6237682", 5.47, due=5.47),
                {"invoice_number": "1401474", "amount_due": -100.54}, charge("6238592", 403.91, due=403.91)]
        self.assertEqual(flags_of(rows), [])

    def test_a_charge_with_a_negative_due_is_flagged_by_sign(self):
        # Rockland 9417731X3: the 760.41 credit read as a charge, due -100.00
        rows = [charge("9417731X3", 860.41), credit("9417731X3", 100.0), charge("9417731X3", 760.41, due=-100.0)]
        self.assertEqual(flags_of(rows), [(g.INVOICE_BALANCE_RULE_ROW_SIGN, "9417731X3"),
                                          (g.INVOICE_BALANCE_RULE_INVOICE, "9417731X3")])


class TestWhenItApplies(unittest.TestCase):

    def test_no_amount_due_values_means_not_applicable(self):
        self.assertIsNone(g.check_invoice_balance([charge("1", 10.0), credit("1", 10.0)]))

    def test_a_running_balance_column_is_not_an_open_balance(self):
        rows = [charge("1", 10.0, due=10.0), charge("2", 5.0, due=15.0), credit("3", 3.0, due=12.0)]
        self.assertIsNone(g.check_invoice_balance(rows))

    def test_single_row_invoices_only_get_the_row_rule(self):
        self.assertEqual(flags_of([charge("1", 10.0), charge("2", 5.0, due=5.0)]), [])

    def test_informational_rows_are_ignored(self):
        rows = [charge("1", 10.0, due=10.0), {"invoice_number": "1", "amount_due": 99.0, "informational": True}]
        self.assertEqual(flags_of(rows), [])


LISTED = "FRED_BEANS_PARTS"  # config/validation_invoice_balance.json "fail_vendors"


class TestApply(unittest.TestCase):
    BAD = [charge("9417731X3", 860.41), credit("9417731X3", 100.0), charge("9417731X3", 760.41, due=-100.0)]

    def test_a_pass_with_flags_of_a_listed_vendor_becomes_a_mismatch_and_keeps_the_pass_in_detail(self):
        passed = {"status": "matches", "printed": 1520.82, "computed": 1520.82, "difference": 0.0,
                  "method": "primary", "detail": None}
        out = g.apply_invoice_balance_check(passed, self.BAD, vendor_id=LISTED)
        self.assertEqual(out["detail"]["invoice_balance"]["mode"], "fail")
        self.assertEqual(out["status"], "mismatch")
        self.assertIsNone(out["method"])
        self.assertEqual(out["detail"]["blocked_pass"], {"method": "primary", "computed": 1520.82, "difference": 0.0})
        self.assertEqual(out["detail"]["invoice_balance"]["flag_count"], 2)
        text = describe_failure(out)
        self.assertTrue(text.startswith("Validation failed: invoice balance check -- 9417731X3 (amount due $-100.00 "
                                        "has the opposite sign of the row's $760.41)"), text)
        self.assertNotIn("off by", text)

    def test_a_failure_only_gains_the_flags_and_keeps_the_teammates_wording(self):
        failed = {"status": "mismatch", "printed": 100.0, "computed": 1620.82, "difference": -1520.82,
                  "method": None, "detail": {"attempts": []}}
        for vendor in (LISTED, "SOME_OTHER_VENDOR", None):
            out = g.apply_invoice_balance_check(failed, self.BAD, vendor_id=vendor)
            self.assertEqual((out["status"], out["method"]), ("mismatch", None))
            self.assertNotIn("blocked_pass", out["detail"])
            self.assertEqual(out["detail"]["invoice_balance"]["flag_count"], 2)
        self.assertEqual(out["detail"]["attempts"], [])
        text = describe_failure(out)
        self.assertTrue(text.startswith("Validation failed: printed total $100.00, extracted lines sum to $1,620.82 "
                                        "(off by $-1,520.82); invoice balance check: 9417731X3"), text)

    def test_a_running_balance_pass_is_left_alone(self):
        # two rows: too few for _is_running_balance(), but the gate's running_balance pass proved it
        passed = {"status": "matches", "method": "running_balance", "difference": 0.0, "detail": None}
        rows = [charge("N1", 100.0, due=100.0), charge("N2", 30.0, due=130.0)]
        self.assertIs(g.apply_invoice_balance_check(passed, rows, vendor_id=LISTED), passed)

    def test_never_adds_a_pass(self):
        for status in ("mismatch", "total_not_found", "no_line_items"):
            out = g.apply_invoice_balance_check({"status": status, "detail": None}, [charge("1", 5.0, due=5.0)],
                                                vendor_id=LISTED)
            self.assertEqual(out["status"], status)

    def test_clean_pass_is_unchanged_apart_from_the_report(self):
        passed = {"status": "matches", "method": "primary", "difference": 0.0, "detail": None}
        out = g.apply_invoice_balance_check(passed, [charge("1", 5.0, due=5.0)], vendor_id=LISTED)
        self.assertEqual((out["status"], out["method"]), ("matches", "primary"))
        self.assertEqual(out["detail"]["invoice_balance"]["flags"], [])

    def test_not_applicable_leaves_the_result_untouched(self):
        passed = {"status": "matches", "method": "primary", "difference": 0.0, "detail": None}
        self.assertIs(g.apply_invoice_balance_check(passed, [charge("1", 5.0)], vendor_id=LISTED), passed)

    def test_an_unlisted_vendor_keeps_its_pass_and_method_with_flags_recorded_as_flag_only(self):
        passed = {"status": "matches", "printed": 1520.82, "computed": 1520.82, "difference": 0.0,
                  "method": "open_balance", "detail": {"attempts": [1]}}
        for vendor in ("SOME_OTHER_VENDOR", None, ""):
            out = g.apply_invoice_balance_check(passed, self.BAD, vendor_id=vendor)
            self.assertEqual((out["status"], out["method"], out["difference"]), ("matches", "open_balance", 0.0))
            self.assertNotIn("blocked_pass", out["detail"])
            self.assertEqual(out["detail"]["attempts"], [1])
            report = out["detail"]["invoice_balance"]
            self.assertEqual((report["mode"], report["flag_count"]), ("flag_only", 2))
            self.assertIsNone(describe_failure(out))

    def test_existing_failure_texts_are_unchanged_without_flags(self):
        self.assertEqual(describe_failure({"status": "mismatch", "difference": 1.5}), "Validation failed: off by $1.50")
        self.assertEqual(describe_failure({"status": "total_not_found"}),
                         "Validation failed: no printed statement total was found to check the extracted lines against")
        self.assertIsNone(describe_failure({"status": "matches"}))


class TestConfig(unittest.TestCase):
    PASSED = {"status": "matches", "method": "primary", "difference": 0.0, "detail": None}

    def setUp(self):
        self.addCleanup(setattr, g, "_invoice_balance_cache", None)
        g._invoice_balance_cache = None

    def run_with_config(self, path):
        g._invoice_balance_cache = None
        with mock.patch.object(g, "INVOICE_BALANCE_CONFIG_PATH", path):
            return g.apply_invoice_balance_check(self.PASSED, TestApply.BAD, vendor_id=LISTED)

    def test_the_shipped_config_lists_only_fred_beans(self):
        self.assertEqual(g.invoice_balance_fail_vendors(), frozenset({"FRED_BEANS_PARTS"}))

    def test_a_missing_config_means_flag_only(self):
        out = self.run_with_config(os.path.join(tempfile.gettempdir(), "no_such_dir_ib", "missing.json"))
        self.assertEqual((out["status"], out["detail"]["invoice_balance"]["mode"]), ("matches", "flag_only"))

    def test_an_unreadable_or_malformed_config_means_flag_only(self):
        for content in ("{not json", "[1, 2]", '{"fail_vendors": 5}', '"FRED_BEANS_PARTS"'):
            with self.subTest(content=content):
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                    f.write(content)
                self.addCleanup(os.remove, f.name)
                out = self.run_with_config(f.name)
                self.assertEqual((out["status"], out["detail"]["invoice_balance"]["mode"]), ("matches", "flag_only"))

    def test_a_listed_vendor_in_another_config_fails(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"_comment": "x", "fail_vendors": {LISTED: {"note": "y"}}}, f)
        self.addCleanup(os.remove, f.name)
        self.assertEqual(self.run_with_config(f.name)["status"], "mismatch")


class TestDetailPage(unittest.TestCase):
    """The validation detail page with every query stubbed (test_pdf_row_match.TestValidationPageBadge's helpers)."""
    FLAGS = {"rows_with_due": 3, "invoices_checked": 1, "flag_count": 1,
             "flags": [{"rule": "due_opposite_sign", "invoice_number": "607385", "row_number": 5,
                        "row_amount": 86.35, "amount_due": -86.35}]}

    def render(self, status, method, detail):
        import test_pdf_row_match as prm
        page = prm.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "H", "source_file": "h.pdf", "vendor_name": "Holman", "statement_period": "2026-08",
                  "statement_total_as_printed": 1574.73, "validation_status": status, "validation_difference": 0.0,
                  "validation_method": method, "previous_balance": None, "previous_balance_source": None,
                  "ingestion_timestamp": "2026-10-01T21:00:00+00:00", "passed": status == "matches",
                  "primary_computed": None, "validation_attempts": [],
                  "invoice_balance": detail.get("invoice_balance"), "blocked_pass": detail.get("blocked_pass")}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": None, "lines": []})
        try:
            return page._client().get("/validation/H").text
        finally:
            page.doCleanups()

    def test_a_flag_only_pass_shows_the_review_notice_and_the_rows(self):
        html = self.render("matches", "primary", {"invoice_balance": {**self.FLAGS, "mode": "flag_only"}})
        self.assertIn("Invoice balance check flagged 1 row - statement still passes; review", html)
        self.assertIn("607385", html)
        self.assertIn("amount due $-86.35 has the opposite sign of the row&#39;s $86.35", html)

    def test_a_blocked_pass_shows_the_failure_wording_without_the_notice(self):
        html = self.render("mismatch", None, {"invoice_balance": {**self.FLAGS, "mode": "fail"},
                                              "blocked_pass": {"method": "primary", "computed": 1, "difference": 0.0}})
        self.assertIn("so the statement failed validation", html)
        self.assertNotIn("statement still passes", html)
        self.assertIn("607385", html)

    def test_no_flags_no_section(self):
        html = self.render("matches", "primary", {"invoice_balance": {**self.FLAGS, "flags": [], "flag_count": 0}})
        self.assertNotIn("Invoice balance check", html)


@unittest.skipUnless(len(ROCKLAND) == 3, "saved Rockland AI extractions (scratchpad/rerun_ai) not present")
class TestRocklandRuns(unittest.TestCase):
    """Rows rebuilt exactly as the client does (_rows_to_invoices) from each saved run's raw rows."""
    PRINTED = 14261.66

    @classmethod
    def setUpClass(cls):
        from src.ai.claude_sonnet_client import ClaudeSonnetClient
        cls.to_invoices = ClaudeSonnetClient.__new__(ClaudeSonnetClient)._rows_to_invoices
        cls.raw = {}
        for name, path in zip(("2-part", "3-part", "carry"), ROCKLAND):
            with open(path, encoding="utf-8") as f:
                schema = json.load(f)["schema_result"]
            cls.raw[name] = ([dict(inv["_raw_row"]) for inv in schema["invoices"]], schema["columns_found"])

    def invoices(self, rows, columns):
        return self.to_invoices(copy.deepcopy(rows), columns)[0]

    def corrected(self):
        rows, columns = copy.deepcopy(self.raw["3-part"])
        e5 = [r for r in rows if r["INVOICE NUMBER"] == "9417731X3" and r.get("CHARGES") == 760.41]
        self.assertEqual(len(e5), 1)
        e5[0]["CHARGES"], e5[0]["CREDITS"] = None, 760.41
        return rows, columns

    def gate(self, invoices):
        computed = g.compute_statement_total_from_invoices(invoices)
        validation = g.validate_with_fallbacks(self.PRINTED, computed, invoices)
        return g.apply_invoice_balance_check(validation, invoices, vendor_id=LISTED)  # the runs' vendor resolves here

    def flagged(self, invoices):
        return sorted({f["invoice_number"] for f in g.check_invoice_balance(invoices)["flags"]})

    def test_each_saved_run_is_flagged_on_exactly_its_known_errors(self):
        expected = {"2-part": ["9417731X3", "9432454", "9432454X1"], "3-part": ["9417731X3"],
                    "carry": ["9391887", "9432454"]}
        for name, want in expected.items():
            with self.subTest(run=name):
                invoices = self.invoices(*self.raw[name])
                self.assertEqual(self.flagged(invoices), want)
                self.assertEqual(self.gate(invoices)["status"], "mismatch")
        carry = g.check_invoice_balance(self.invoices(*self.raw["carry"]))["flags"]
        self.assertIn((g.INVOICE_BALANCE_RULE_DUE_ONLY, "9391887"), [(f["rule"], f["invoice_number"]) for f in carry])

    def test_the_corrected_run_flags_nothing_and_passes_the_existing_total_check(self):
        invoices = self.invoices(*self.corrected())
        self.assertEqual(self.flagged(invoices), [])
        out = self.gate(invoices)
        self.assertEqual((out["status"], out["method"]), ("matches", "primary"))

    def mutate(self, change):
        rows, columns = self.corrected()
        change(rows)
        return self.gate(self.invoices(rows, columns))

    def test_mutations_of_the_corrected_run(self):
        def row(rows, inv, **values):
            hits = [r for r in rows if r["INVOICE NUMBER"] == inv and all(r.get(k) == v for k, v in values.items())]
            self.assertEqual(len(hits), 1, (inv, values))
            return hits[0]

        def swap(rows):   # a charge and a credit of two invoices trade columns (9429288 1,037.55 / 9456441 90.95)
            a, b = row(rows, "9429288", CHARGES=1037.55), row(rows, "9456441", CREDITS=90.95)
            a["CHARGES"], a["CREDITS"], b["CHARGES"], b["CREDITS"] = None, 1037.55, 90.95, None

        def swap_same_invoice(rows):   # 9429288's own 1,037.55 charge and 1,037.55 credit trade columns
            a, b = row(rows, "9429288", CHARGES=1037.55), row(rows, "9429288", CREDITS=1037.55)
            a["CHARGES"], a["CREDITS"], b["CHARGES"], b["CREDITS"] = None, 1037.55, 1037.55, None

        def credit_into_due(rows):   # the carry run's error: 9391887 113.20 credit -> AMOUNT DUE
            r = row(rows, "9391887", CREDITS=113.2)
            r["CREDITS"], r["AMOUNT DUE"] = None, 113.2

        def drop_row(rows):   # the 2-part run's E3: 9432454X1 1.24 credit missing
            rows.remove(row(rows, "9432454X1", CREDITS=1.24))

        def drop_offsetting(rows):   # two errors that cancel in the total: 9432454's 23.28 charge and
            rows.remove(row(rows, "9432454", CHARGES=23.28))  # CM9432454X1's 23.28 credit both missing
            rows.remove(row(rows, "CM9432454X1", CREDITS=23.28))

        def drop_pair(rows):   # an equal charge + credit both missing (9456441 90.95 / 90.95)
            rows.remove(row(rows, "9456441", CHARGES=90.95))
            rows.remove(row(rows, "9456441", CREDITS=90.95))

        outcome = {name: self.mutate(fn)["status"] for name, fn in
                   (("swap", swap), ("swap_same_invoice", swap_same_invoice), ("credit_into_due", credit_into_due),
                    ("drop_row", drop_row), ("drop_offsetting", drop_offsetting), ("drop_pair", drop_pair))}
        self.assertEqual(outcome, {"swap": "mismatch", "credit_into_due": "mismatch", "drop_row": "mismatch",
                                   # the total still matches here; only this check sees it (a blocked pass)
                                   "drop_offsetting": "mismatch",
                                   # Known gaps -- neither moves the total nor any invoice's balance, so only a
                                   # row-by-row PDF check could see them: an equal charge and credit of ONE
                                   # invoice trading columns (only their dates move), and an equal charge +
                                   # credit pair dropped together.
                                   "swap_same_invoice": "matches", "drop_pair": "matches"})


if __name__ == "__main__":
    unittest.main()
