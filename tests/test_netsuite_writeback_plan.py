"""
tests/test_netsuite_writeback_plan.py

Offline tests for the pure classification half of src/netsuite/writeback.py
(plan_matched / plan_amount_mismatch / plan_not_found / plan_exception_row).
No NetSuite or Fabric calls are made.
"""

import os
import sys
import unittest
from unittest import mock
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.netsuite import writeback as wb

STMT = "STMT-TEST0001"


def _ctx(link="https://app.example/statements/abc/pdf"):
    return wb.StatementContext(
        statement_id=STMT, vendor_id="V", vendor_name="Vendor", shop="Shop",
        entity_ids=["111", "222"], link=link, link_note="", today="2026-10-07",
        exception_ids={"Amount differs": "7", "Duplicate": "9"},
    )


def _txn(total, ns_type="VendBill", **extra):
    row = {"id": "500", "tranid": "INV1", "entity": "111", "type": ns_type, "foreigntotal": total}
    row.update(extra)
    return row


def _row(amount="100.00", reason=None, invoice="INV1"):
    row = {"invoice_number": invoice, "original_invoice_number": invoice,
           "statement_amount": Decimal(amount), "shop": None}
    if reason:
        row["exception_reason"] = reason
    return row


class PlanMatchedTests(unittest.TestCase):
    def test_bill_total_is_negative_but_still_ties(self):
        plan = wb.plan_matched(_row("100.00"), [_txn("-100.00")], _ctx())
        self.assertEqual(plan.action, wb.PATCH_MATCHED)
        self.assertEqual(plan.record_type, "vendorbill")
        self.assertTrue(plan.fields["custbody_reconciled"])
        self.assertIsNone(plan.fields["custbody_reconciliation_exception"])
        self.assertEqual(plan.fields["custbody_statement_link"], "https://app.example/statements/abc/pdf")

    def test_credit_uses_vendorcredit(self):
        plan = wb.plan_matched(_row("100.00"), [_txn("100", ns_type="VendCred")], _ctx())
        self.assertEqual(plan.record_type, "vendorcredit")

    def test_no_link_means_link_field_is_not_written(self):
        plan = wb.plan_matched(_row(), [_txn("-100")], _ctx(link=None))
        self.assertNotIn("custbody_statement_link", plan.fields)

    def test_missing_in_sandbox_is_skipped_not_written(self):
        plan = wb.plan_matched(_row(), [], _ctx())
        self.assertEqual(plan.action, wb.SKIP_REVIEW)

    def test_sandbox_amount_drift_is_skipped(self):
        plan = wb.plan_matched(_row("100.00"), [_txn("-250.00")], _ctx())
        self.assertEqual(plan.action, wb.SKIP_REVIEW)

    def test_already_reconciled_by_earlier_statement_is_left_alone(self):
        txn = _txn("-100", custbody_reconciled="T", custbody_statement_reference="STMT-OLD")
        self.assertEqual(wb.plan_matched(_row(), [txn], _ctx()).action, wb.SKIP_RECONCILED_EARLIER)

    def test_rerun_of_same_statement_is_up_to_date(self):
        # (A bill with no link yet gets a link-only write -- LinkOnlyPlanTests.)
        txn = _txn("-100", custbody_reconciled="T", custbody_statement_reference=STMT,
                   custbody_statement_link="https://app.example/statements/abc/pdf")
        self.assertEqual(wb.plan_matched(_row(), [txn], _ctx()).action, wb.SKIP_UP_TO_DATE)

    def test_previous_mismatch_flag_is_cleared_when_it_now_matches(self):
        txn = _txn("-100", custbody_reconciled="F", custbody_statement_reference=STMT,
                   custbody_reconciliation_exception="7")
        self.assertEqual(wb.plan_matched(_row(), [txn], _ctx()).action, wb.PATCH_MATCHED)


class PlanExceptionOnBillsTests(unittest.TestCase):
    def _mismatch(self, candidates, existing=None):
        return wb.plan_exception_row(_row("100.00", wb.REASON_AMOUNT_MISMATCH), candidates, _ctx(), existing or set())

    def test_mismatch_writes_exception_to_the_bill(self):
        (plan,) = self._mismatch([_txn("-120.00")])
        self.assertEqual(plan.action, wb.PATCH_EXCEPTION)
        self.assertEqual(plan.record_type, "vendorbill")
        self.assertFalse(plan.fields["custbody_reconciled"])
        self.assertEqual(plan.fields["custbody_reconciliation_exception"]["id"], "7")
        self.assertEqual(plan.fields["custbody_statement_reference"], STMT)
        self.assertIn("custbody_statement_link", plan.fields)
        self.assertNotIn("custbody_reconciled_date", plan.fields)

    def test_mismatch_rerun_is_up_to_date(self):
        txn = _txn("-120", custbody_reconciled="F", custbody_statement_reference=STMT,
                   custbody_reconciliation_exception="7", custbody_statement_link="https://app.example/statements/abc/pdf")
        (plan,) = self._mismatch([txn])
        self.assertEqual(plan.action, wb.SKIP_UP_TO_DATE)

    def test_mismatch_on_a_credit_uses_vendorcredit(self):
        (plan,) = self._mismatch([_txn("120", ns_type="VendCred")])
        self.assertEqual(plan.record_type, "vendorcredit")

    def test_mismatch_with_several_records_needs_a_human(self):
        (plan,) = self._mismatch([_txn("-120"), _txn("-130")])
        self.assertEqual(plan.action, wb.SKIP_REVIEW)

    def test_sandbox_now_ties_is_not_flagged(self):
        (plan,) = self._mismatch([_txn("-100")])
        self.assertEqual(plan.action, wb.SKIP_REVIEW)

    def test_mismatch_missing_from_sandbox_writes_nothing(self):
        (plan,) = self._mismatch([])
        self.assertEqual(plan.action, wb.SKIP_REVIEW)

    def test_mismatch_on_bill_reconciled_by_earlier_statement_is_left_alone(self):
        txn = _txn("-120", custbody_reconciled="T", custbody_statement_reference="STMT-OLD")
        (plan,) = self._mismatch([txn])
        self.assertEqual(plan.action, wb.SKIP_RECONCILED_EARLIER)

    def test_duplicate_flags_every_record_sharing_the_tranid(self):
        first, second = _txn("-5"), dict(_txn("-5"), id="501")
        plans = wb.plan_exception_row(_row("5", wb.REASON_DUPLICATE), [first, second], _ctx(), set())
        self.assertEqual([p.action for p in plans], [wb.PATCH_EXCEPTION, wb.PATCH_EXCEPTION])
        self.assertEqual({p.record_id for p in plans}, {"500", "501"})
        self.assertEqual(plans[0].fields["custbody_reconciliation_exception"]["id"], "9")

    def test_exception_missing_from_the_list_is_not_written(self):
        ctx = _ctx()
        ctx.exception_ids = {}
        (plan,) = wb.plan_exception_row(_row("5", wb.REASON_DUPLICATE), [_txn("-5")], ctx, set())
        self.assertEqual(plan.action, wb.SKIP_REVIEW)


class PlanNotFoundTests(unittest.TestCase):
    def test_not_found_creates_statement_line(self):
        (plan,) = wb.plan_exception_row(_row("55.50", wb.REASON_NOT_FOUND), [], _ctx(), set())
        self.assertEqual(plan.action, wb.CREATE_STATEMENT_LINE)
        self.assertEqual(plan.fields["custrecord_sl_status"], "No match found")
        self.assertEqual(plan.fields["custrecord_sl_statement_amount"], 55.5)
        self.assertEqual(plan.fields["custrecord_sl_vendor"], {"id": "111"})
        self.assertIn("custrecord_sl_statement_link", plan.fields)

    def test_vendor_is_the_statements_primary_entity(self):
        ctx = _ctx()
        ctx.primary_entity = "222"
        (plan,) = wb.plan_exception_row(_row("5", wb.REASON_NOT_FOUND), [], ctx, set())
        self.assertEqual(plan.fields["custrecord_sl_vendor"], {"id": "222"})

    def test_existing_statement_line_is_not_duplicated(self):
        existing = {wb._line_key("INV1", "55.50")}
        (plan,) = wb.plan_exception_row(_row("55.50", wb.REASON_NOT_FOUND), [], _ctx(), existing)
        self.assertEqual(plan.action, wb.SKIP_UP_TO_DATE)

    def test_same_invoice_with_a_different_amount_is_a_separate_line(self):
        existing = {wb._line_key("INV1", "832.14")}
        (plan,) = wb.plan_exception_row(_row("75.00", wb.REASON_NOT_FOUND), [], _ctx(), existing)
        self.assertEqual(plan.action, wb.CREATE_STATEMENT_LINE)

    def test_not_found_is_taken_as_given_even_if_the_tranid_exists_as_a_bill(self):
        (plan,) = wb.plan_exception_row(_row("75.00", wb.REASON_NOT_FOUND), [_txn("-832.14")], _ctx(), set())
        self.assertEqual(plan.action, wb.CREATE_STATEMENT_LINE)

    def test_statement_line_has_the_mandatory_name(self):
        (plan,) = wb.plan_exception_row(_row("5", wb.REASON_NOT_FOUND), [], _ctx(), set())
        self.assertEqual(plan.fields["name"], f"{STMT} INV1")

    def test_statement_line_uses_the_stripped_invoice_number(self):
        row = _row("10", wb.REASON_NOT_FOUND, invoice="626699T")
        row["original_invoice_number"] = "TOW626699T"
        (plan,) = wb.plan_exception_row(row, [], _ctx(), set())
        self.assertEqual(plan.fields["custrecord_sl_invoice_number"], "626699T")


class BlankStatementAmountTests(unittest.TestCase):
    def _blank_row(self, reason=None):
        row = _row("1", reason)
        row["statement_amount"] = None
        return row

    def test_blank_amount_exception_still_flags_the_bill(self):
        (plan,) = wb.plan_exception_row(self._blank_row(wb.REASON_AMOUNT_MISMATCH), [_txn("-50")], _ctx(), set())
        self.assertEqual(plan.action, wb.PATCH_EXCEPTION)
        self.assertIsNone(plan.statement_amount)

    def test_blank_amount_matched_row_is_skipped_not_crashed(self):
        plan = wb.plan_matched(self._blank_row(), [_txn("-50")], _ctx())
        self.assertEqual(plan.action, wb.SKIP_REVIEW)

    def test_blank_amount_not_found_still_creates_a_line_without_the_amount_field(self):
        (plan,) = wb.plan_exception_row(self._blank_row(wb.REASON_NOT_FOUND), [], _ctx(), set())
        self.assertEqual(plan.action, wb.CREATE_STATEMENT_LINE)
        self.assertNotIn("custrecord_sl_statement_amount", plan.fields)


class RevertTests(unittest.TestCase):
    def _log(self, writes):
        return {"statement_id": STMT, "applied_at": "2026-10-07T15:24:02", "writes": writes}

    def _bill_entry(self, action, fields, previous=None, ok=True):
        entry = {"action": action, "invoice_number": "INV1", "record_type": "vendorbill",
                 "record_id": "500", "fields_sent": fields, "ok": ok}
        if previous is not None:
            entry["previous"] = previous
        return entry

    def test_matched_write_is_undone_to_empty_when_no_previous_was_recorded(self):
        fields = {"custbody_reconciled": True, "custbody_reconciled_date": "2026-10-07",
                  "custbody_statement_reference": STMT, "custbody_reconciliation_exception": None}
        (action,) = wb.build_revert_actions(self._log([self._bill_entry(wb.PATCH_MATCHED, fields)]))
        self.assertEqual(action["op"], "PATCH")
        self.assertEqual(action["body"], {
            "custbody_reconciled": False, "custbody_reconciled_date": None,
            "custbody_statement_reference": None, "custbody_reconciliation_exception": None})

    def test_recorded_previous_values_are_restored(self):
        fields = {"custbody_reconciled": True, "custbody_statement_reference": STMT}
        previous = {"custbody_reconciled": "F", "custbody_statement_reference": "OLD-REF"}
        (action,) = wb.build_revert_actions(self._log([self._bill_entry(wb.PATCH_MATCHED, fields, previous)]))
        self.assertEqual(action["body"], {"custbody_reconciled": False,
                                          "custbody_statement_reference": "OLD-REF"})

    def test_exception_value_is_restored_as_a_list_reference(self):
        fields = {"custbody_reconciliation_exception": {"id": "1"}}
        previous = {"custbody_reconciliation_exception": "3"}
        (action,) = wb.build_revert_actions(self._log([self._bill_entry(wb.PATCH_EXCEPTION, fields, previous)]))
        self.assertEqual(action["body"], {"custbody_reconciliation_exception": {"id": "3"}})

    def test_statement_line_is_deleted(self):
        entry = {"action": wb.CREATE_STATEMENT_LINE, "invoice_number": "X", "ok": True,
                 "record_type": "customrecord_statement_line", "record_id": "42", "fields_sent": {}}
        (action,) = wb.build_revert_actions(self._log([entry]))
        self.assertEqual((action["op"], action["record_id"]), ("DELETE", "42"))

    def test_failed_writes_are_not_undone(self):
        entry = self._bill_entry(wb.PATCH_MATCHED, {"custbody_reconciled": True}, ok=False)
        self.assertEqual(wb.build_revert_actions(self._log([entry])), [])


SP_URL = ("https://vivecollision.sharepoint.com/sites/AIVendorStatements/Shared%20Documents/General/"
          "Vendor%20Statements/_dev_test/fred_beans/2026/09/Fred%20Beans__abababababab.pdf")


class PdfLinkSwitchTests(unittest.TestCase):
    ON = {"NETSUITE_WRITEBACK_PDF_LINK": "true"}

    def _resolve(self, rows, env=None):
        with mock.patch.dict(os.environ, env or self.ON, clear=True), \
             mock.patch("src.lakehouse.connection.execute_query", return_value=rows) as query:
            url, note = wb.resolve_pdf_link("STMT-1")
        return url, note, query

    def test_link_is_off_unless_explicitly_switched_on(self):
        for env in ({}, {"NETSUITE_WRITEBACK_PDF_LINK": "false"}, {"NETSUITE_WRITEBACK_PDF_LINK": ""}):
            with self.subTest(env=env):
                url, note, query = self._resolve([{"sharepoint_status": "uploaded", "sharepoint_web_url": SP_URL}],
                                                 env=dict(env, APP_PUBLIC_BASE_URL="https://app.example"))
                self.assertIsNone(url)
                self.assertIn("switched off", note)
                query.assert_not_called()

    def test_switched_on_uses_the_sharepoint_link_from_the_intake_log(self):
        url, note, query = self._resolve([{"sharepoint_status": "uploaded", "sharepoint_web_url": SP_URL}])
        self.assertEqual((url, note), (SP_URL, ""))
        sql, params = query.call_args.args
        self.assertIn("FROM document_intake_log", sql)
        self.assertEqual(params, ["STMT-1"])

    def test_an_existing_file_is_linked_too(self):
        url, _, _ = self._resolve([{"sharepoint_status": "existing", "sharepoint_web_url": SP_URL}])
        self.assertEqual(url, SP_URL)

    def test_the_base_url_is_no_longer_needed_or_used(self):
        env = dict(self.ON, APP_PUBLIC_BASE_URL="https://app.example")
        url, _, _ = self._resolve([{"sharepoint_status": "uploaded", "sharepoint_web_url": SP_URL}], env=env)
        self.assertEqual(url, SP_URL)
        self.assertNotIn("/statements/", url)

    def test_no_link_unless_the_upload_succeeded(self):
        for rows, status in (([], "none"),
                             ([{"sharepoint_status": None, "sharepoint_web_url": None}], "none"),
                             ([{"sharepoint_status": "failed", "sharepoint_web_url": None}], "failed"),
                             ([{"sharepoint_status": "skipped", "sharepoint_web_url": None}], "skipped"),
                             ([{"sharepoint_status": "uploaded", "sharepoint_web_url": ""}], "uploaded")):
            with self.subTest(rows=rows):
                url, note, _ = self._resolve(rows)
                self.assertIsNone(url)
                self.assertEqual(note, f"no SharePoint link for this statement (status: {status})")

    def test_url_longer_than_the_field_limit_is_not_written(self):
        long_url = "https://x.sharepoint.com/" + "a" * wb.NETSUITE_LINK_MAX_LEN
        url, note, _ = self._resolve([{"sharepoint_status": "uploaded", "sharepoint_web_url": long_url}])
        self.assertIsNone(url)
        self.assertIn("too long", note)
        exact = "h" * wb.NETSUITE_LINK_MAX_LEN
        self.assertEqual(self._resolve([{"sharepoint_status": "uploaded", "sharepoint_web_url": exact}])[0], exact)

    def test_lookup_failure_is_not_fatal(self):
        with mock.patch.dict(os.environ, self.ON, clear=True), \
             mock.patch("src.lakehouse.connection.execute_query", side_effect=RuntimeError("db down")):
            url, note = wb.resolve_pdf_link("STMT-1")
        self.assertIsNone(url)
        self.assertEqual(note, "SharePoint link lookup failed (RuntimeError)")

    def test_plans_carry_no_link_fields_when_there_is_no_link(self):
        ctx = _ctx(link=None)
        matched = wb.plan_matched(_row(), [_txn("-100")], ctx)
        (line,) = wb.plan_exception_row(_row("5", wb.REASON_NOT_FOUND), [], ctx, set())
        self.assertNotIn("custbody_statement_link", matched.fields)
        self.assertNotIn("custrecord_sl_statement_link", line.fields)


class _FakeNs:
    """Records PATCHes and answers the read-back with `row` (SuiteQL leaves
    out null columns, so an absent key means empty)."""

    domain_id = "7321761-sb1"

    def __init__(self, row):
        self.row = row
        self.patches = []
        self.queries = []

    def patch_record(self, record_type, record_id, body):
        self.patches.append((record_type, record_id, dict(body)))

    def suiteql(self, query):
        self.queries.append(query)
        return [self.row] if self.row is not None else []


class ReadBackTests(unittest.TestCase):
    def _matched(self, link=SP_URL):
        return wb.plan_matched(_row(), [_txn("-100")], _ctx(link=link))

    def _stored(self, plan, **override):
        row = {"custbody_reconciled": "T", "custbody_statement_reference": STMT}
        if "custbody_statement_link" in plan.fields:
            row["custbody_statement_link"] = plan.fields["custbody_statement_link"]
        row.update(override)
        return row

    def test_matched_write_reads_back_the_link_too(self):
        plan = self._matched()
        ns = _FakeNs(self._stored(plan))
        result = wb.apply_plan(ns, plan)
        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "updated")
        self.assertFalse(result.link_mismatch)
        self.assertIn("custbody_statement_link", ns.queries[0])

    def test_link_mismatch_on_a_result_write_is_ok_but_flagged(self):
        plan = self._matched()
        ns = _FakeNs(self._stored(plan, custbody_statement_link=SP_URL[:100]))   # truncated
        result = wb.apply_plan(ns, plan)
        self.assertTrue(result.ok)
        self.assertTrue(result.link_mismatch)
        self.assertEqual(result.detail, "updated; link not stored as sent")

    def test_a_truncated_link_on_the_first_write_does_not_stop_the_run(self):
        first = wb.plan_matched(_row(invoice="INV1"), [dict(_txn("-100"), id="501", tranid="INV1")], _ctx(link=SP_URL))
        second = wb.plan_matched(_row(invoice="INV2"), [dict(_txn("-100"), id="502", tranid="INV2")], _ctx(link=SP_URL))

        class Ns(_FakeNs):
            def suiteql(self, query):
                self.queries.append(query)
                truncated = "WHERE t.id = 501" in query
                return [{"custbody_reconciled": "T", "custbody_statement_reference": STMT,
                         "custbody_statement_link": SP_URL[:100] if truncated else SP_URL}]

        ns = Ns(None)
        results = wb.apply_plans(ns, [first, second])
        self.assertEqual([p[1] for p in ns.patches], ["501", "502"], "both bills written")
        self.assertEqual(len(results), 2, "the run did not stop after the first write")
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual([r.link_mismatch for r in results], [True, False])

    def test_result_mismatch_still_fails(self):
        plan = self._matched()
        ns = _FakeNs(self._stored(plan, custbody_statement_reference="STMT-OTHER"))
        result = wb.apply_plan(ns, plan)
        self.assertFalse(result.ok)
        self.assertIn("statement reference", result.detail)

    def test_no_link_sent_means_no_link_check(self):
        plan = self._matched(link=None)
        ns = _FakeNs(self._stored(plan, custbody_statement_link="https://something-else"))
        self.assertTrue(wb.apply_plan(ns, plan).ok)

    def test_link_only_plan_is_checked_without_a_key_error(self):
        txn = _txn("-100", custbody_reconciled="T", custbody_statement_reference=STMT)
        plan = wb._txn_plan_base("INV1", Decimal("100"), txn, wb.PATCH_MATCHED, {"custbody_statement_link": SP_URL})
        ok = wb.apply_plan(_FakeNs({"custbody_statement_link": SP_URL}), plan)
        self.assertTrue(ok.ok, ok.detail)
        bad = wb.apply_plan(_FakeNs({"custbody_statement_link": SP_URL[:100]}), plan)
        self.assertFalse(bad.ok)
        self.assertEqual(bad.detail, "link not stored as sent")
        self.assertFalse(bad.link_mismatch)

    def test_exception_write_checks_the_exception(self):
        plan = wb.plan_exception_row(_row("100.00", wb.REASON_AMOUNT_MISMATCH), [_txn("-90")], _ctx(link=None),
                                     set())[0]
        self.assertEqual(plan.action, wb.PATCH_EXCEPTION)
        good = {"custbody_reconciled": "F", "custbody_statement_reference": STMT,
                "custbody_reconciliation_exception": "7"}
        self.assertTrue(wb.apply_plan(_FakeNs(good), plan).ok)
        self.assertFalse(wb.apply_plan(_FakeNs(dict(good, custbody_reconciliation_exception="9")), plan).ok)

    def test_record_gone_on_read_back(self):
        result = wb.apply_plan(_FakeNs(None), self._matched())
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "record not found on read-back")


OLD_LINK = "https://app.example/statements/abc/pdf"


def _done(**extra):
    """A matched bill already carrying THIS statement's result."""
    return _txn("-100", custbody_reconciled="T", custbody_statement_reference=STMT, **extra)


class LinkOnlyPlanTests(unittest.TestCase):
    def test_up_to_date_bill_without_a_link_gets_a_link_only_write(self):
        plan = wb.plan_matched(_row(), [_done()], _ctx(link=SP_URL))
        self.assertEqual(plan.action, wb.PATCH_LINK_ONLY)
        self.assertEqual(plan.fields, {"custbody_statement_link": SP_URL})
        self.assertEqual(plan.previous, {"custbody_reconciled": "T", "custbody_statement_reference": STMT,
                                         "custbody_statement_link": None})
        self.assertIn(wb.PATCH_LINK_ONLY, wb.WRITE_ACTIONS)

    def test_up_to_date_exception_bill_without_a_link_gets_a_link_only_write(self):
        txn = _txn("-120", custbody_reconciled="F", custbody_statement_reference=STMT,
                   custbody_reconciliation_exception="7")
        (plan,) = wb.plan_exception_row(_row("100.00", wb.REASON_AMOUNT_MISMATCH), [txn], _ctx(link=SP_URL), set())
        self.assertEqual((plan.action, plan.fields), (wb.PATCH_LINK_ONLY, {"custbody_statement_link": SP_URL}))

    def test_never_over_an_existing_link_even_a_different_one(self):
        for existing in (OLD_LINK, SP_URL):
            with self.subTest(existing=existing):
                plan = wb.plan_matched(_row(), [_done(custbody_statement_link=existing)], _ctx(link=SP_URL))
                self.assertEqual(plan.action, wb.SKIP_UP_TO_DATE)
                self.assertEqual(plan.fields, {})

    def test_never_for_a_bill_reconciled_by_another_statement(self):
        for link in (None, OLD_LINK):
            with self.subTest(link=link):
                txn = _txn("-100", custbody_reconciled="T", custbody_statement_reference="STMT-OLD",
                           **({"custbody_statement_link": link} if link else {}))
                plan = wb.plan_matched(_row(), [txn], _ctx(link=SP_URL))
                self.assertEqual(plan.action, wb.SKIP_RECONCILED_EARLIER)
                self.assertEqual(plan.fields, {})

    def test_never_without_a_link_for_this_statement(self):
        plan = wb.plan_matched(_row(), [_done()], _ctx(link=None))
        self.assertEqual(plan.action, wb.SKIP_UP_TO_DATE)

    def test_defensive_reference_check(self):
        # Even if a skip were ever mislabelled "up to date", a bill whose
        # reference isn't this statement never gets a link-only write.
        txn = _txn("-100", custbody_reconciled="T", custbody_statement_reference="STMT-OTHER")
        plan = wb._skipped_or_link_only("INV1", Decimal("100"), txn, _ctx(link=SP_URL), wb.SKIP_UP_TO_DATE)
        self.assertEqual(plan.action, wb.SKIP_UP_TO_DATE)

    def test_link_only_is_a_write_not_a_skip_in_the_counts(self):
        plans = [wb.plan_matched(_row(), [_done()], _ctx(link=SP_URL)),
                 wb.plan_matched(_row(), [_done(custbody_statement_link=OLD_LINK)], _ctx(link=SP_URL))]
        self.assertEqual(wb.skip_counts(plans), {wb.CAT_UP_TO_DATE: 1})

    def test_build_plans_puts_link_only_writes_last(self):
        results = {"header": {"vendor_id": "V", "vendor_name_raw": "Vendor", "shop_name_raw": None},
                   "matched": [_row(invoice="DONE1"), _row(invoice="NEW1"), _row(invoice="DONE2")],
                   "exceptions": [], "lines": []}
        sandbox = {"done1": [_done(id="601", tranid="DONE1")], "new1": [dict(_txn("-100"), id="602", tranid="NEW1")],
                   "done2": [_done(id="603", tranid="DONE2")]}
        with mock.patch.object(wb, "load_statement_results", return_value=results), \
             mock.patch.object(wb, "resolve_entity_ids", return_value=["111"]), \
             mock.patch.object(wb, "resolve_pdf_link", return_value=(SP_URL, "")), \
             mock.patch.object(wb, "fetch_exception_list_ids", return_value={}), \
             mock.patch.object(wb, "fetch_sandbox_transactions", return_value=sandbox), \
             mock.patch.object(wb, "load_recon_rows", return_value=[]), \
             mock.patch.object(wb, "fetch_transactions_by_id", return_value={}), \
             mock.patch.object(wb, "fetch_existing_statement_lines", return_value=set()), \
             mock.patch.object(wb, "_primary_entity", return_value="111"), \
             mock.patch.object(wb, "_statement_location", return_value=None):
            ctx, plans = wb.build_plans(STMT, mock.Mock())
        self.assertEqual([(p.action, p.invoice_number) for p in plans],
                         [(wb.PATCH_MATCHED, "NEW1"), (wb.PATCH_LINK_ONLY, "DONE1"), (wb.PATCH_LINK_ONLY, "DONE2")])


class LinkOnlyApplyTests(unittest.TestCase):
    LOCKED = ('{"o:errorDetails":[{"detail":"You cannot make changes to this period without the '
              'Allow Non-G/L Changes permission."}]}')

    def _link_only(self, record_id):
        return wb.plan_matched(_row(invoice=f"DONE{record_id}"), [_done(id=record_id, tranid=f"DONE{record_id}")],
                               _ctx(link=SP_URL))

    def _ns(self, fail_ids=(), locked_ids=(), truncate_ids=()):
        outer = self

        class Ns(_FakeNs):
            def patch_record(self, record_type, record_id, body):
                if record_id in fail_ids or record_id in locked_ids:
                    exc = RuntimeError("HTTP 400")
                    exc.status_code = 400
                    exc.body = outer.LOCKED if record_id in locked_ids else "bad value"
                    raise exc
                super().patch_record(record_type, record_id, body)

            def suiteql(self, query):
                self.queries.append(query)
                rid = query.rsplit("= ", 1)[1].strip()
                return [{"custbody_reconciled": "T", "custbody_statement_reference": STMT,
                         "custbody_statement_link": SP_URL[:50] if rid in truncate_ids else SP_URL}]
        return Ns(None)

    def test_only_the_link_is_sent(self):
        ns = self._ns()
        (result,) = wb.apply_plans(ns, [self._link_only("701")])
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(ns.patches, [("vendorbill", "701", {"custbody_statement_link": SP_URL})])

    def test_a_failed_link_only_write_never_stops_the_run(self):
        ns = self._ns(fail_ids=("701",))
        results = wb.apply_plans(ns, [self._link_only("701"), self._link_only("702")])
        self.assertEqual(len(results), 2, "the run carried on after the first (link-only) write failed")
        self.assertEqual([r.ok for r in results], [False, True])
        self.assertEqual(results[0].category, wb.CAT_LINK_ONLY_FAILED)

    def test_a_link_only_write_in_a_locked_period_is_labelled_period_locked(self):
        (result, after) = wb.apply_plans(self._ns(locked_ids=("701",)), [self._link_only("701"), self._link_only("702")])
        self.assertEqual(result.category, wb.CAT_PERIOD_LOCKED)
        self.assertTrue(after.ok)

    def test_a_link_only_write_whose_link_comes_back_different_fails(self):
        (result,) = wb.apply_plans(self._ns(truncate_ids=("701",)), [self._link_only("701")])
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, wb.LINK_NOT_STORED)

    def test_failed_link_only_writes_do_not_count_toward_the_first_write_rule(self):
        # A link-only failure, then a failing RESULT write: the result write is
        # the run's first, so the run stops there.
        result_write = wb.plan_matched(_row(invoice="NEW1"), [dict(_txn("-100"), id="801", tranid="NEW1")],
                                       _ctx(link=SP_URL))
        results = wb.apply_plans(self._ns(fail_ids=("701", "801")),
                                 [self._link_only("701"), result_write, self._link_only("702")])
        self.assertEqual(len(results), 2)

    def test_pipeline_summary_counts_link_only_writes_separately(self):
        from src.netsuite import pipeline_hook
        plans = [wb.plan_matched(_row(invoice="NEW1"), [dict(_txn("-100"), id="801", tranid="NEW1")], _ctx(link=SP_URL)),
                 self._link_only("701"), self._link_only("702"), self._link_only("703")]
        ns = self._ns(fail_ids=("702",), locked_ids=("703",))
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}, clear=True), \
             mock.patch.object(pipeline_hook, "NetSuiteClient", return_value=ns), \
             mock.patch.object(pipeline_hook, "build_plans", return_value=(mock.Mock(), plans)), \
             mock.patch.object(pipeline_hook, "write_apply_log", return_value="log.json"), \
             mock.patch.object(pipeline_hook, "save_run"):
            summary = pipeline_hook.run_netsuite_writeback(STMT)
        self.assertEqual({k: summary[k] for k in ("written", "failed", "period_locked", "links_added",
                                                  "link_only_failed", "link_mismatch")},
                         {"written": 1, "failed": 0, "period_locked": 1, "links_added": 1,
                          "link_only_failed": 1, "link_mismatch": 0})


class LinkOnlyRevertTests(unittest.TestCase):
    def test_revert_from_log_puts_back_the_empty_link(self):
        plan = wb.plan_matched(_row(), [_done(id="701")], _ctx(link=SP_URL))
        entry = {"action": plan.action, "invoice_number": plan.invoice_number, "record_type": plan.record_type,
                 "record_id": plan.record_id, "fields_sent": plan.fields, "previous": plan.previous, "ok": True}
        (action,) = wb.build_revert_actions({"writes": [entry]})
        self.assertEqual(action["op"], "PATCH")
        self.assertEqual(action["body"], {"custbody_statement_link": None})

    def test_revert_by_statement_finds_it_by_this_statements_reference_and_clears_the_link(self):
        queries = []

        class Ns:
            def suiteql(self, query):
                queries.append(query)
                if "FROM transaction" in query:
                    return [{"id": "701", "tranid": "DONE701", "type": "VendBill", "custbody_statement_link": SP_URL}]
                return []
        (action,) = wb.find_revert_actions_for_statement(Ns(), STMT)
        self.assertIn(f"custbody_statement_reference = '{STMT}'", queries[0])
        self.assertIsNone(action["body"]["custbody_statement_link"])


class LockedPeriodRunControlTests(unittest.TestCase):
    LOCKED_BODY = ('{"o:errorDetails":[{"detail":"Error while accessing a resource. You cannot make changes '
                   'to this period without the Allow Non-G/L Changes permission."}]}')

    def _plans(self, n):
        return [wb.plan_matched(_row(invoice=f"INV{i}"), [dict(_txn("-100"), id=str(500 + i), tranid=f"INV{i}")], _ctx())
                for i in range(n)]

    def _run(self, errors):
        """errors: one entry per write -- None for success, else an exception."""
        from src.netsuite.client import NetSuiteAPIError  # noqa: F401  (used by callers building errors)
        ns = mock.Mock()
        ns.patch_record.side_effect = errors
        with mock.patch.object(wb, "_read_back_bill", return_value=""):
            return wb.apply_plans(ns, self._plans(len(errors))), ns

    def _locked(self):
        from src.netsuite.client import NetSuiteAPIError
        return NetSuiteAPIError(400, "Bad Request", self.LOCKED_BODY)

    def test_a_locked_period_on_the_first_write_does_not_stop_the_run(self):
        results, ns = self._run([self._locked(), None, None])
        self.assertEqual([r.ok for r in results], [False, True, True])
        self.assertEqual(results[0].category, wb.CAT_PERIOD_LOCKED)
        self.assertEqual(ns.patch_record.call_count, 3)

    def test_locked_periods_in_the_middle_do_not_stop_it_either(self):
        results, _ = self._run([None, self._locked(), self._locked(), None])
        self.assertEqual([r.ok for r in results], [True, False, False, True])

    def test_any_other_failure_on_the_first_write_still_stops_the_run(self):
        from src.netsuite.client import NetSuiteAPIError
        results, ns = self._run([NetSuiteAPIError(400, "Bad Request", "Invalid field value"), None, None])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].category, wb.CAT_WRITE_FAILED)
        self.assertEqual(ns.patch_record.call_count, 1)

    def test_an_auth_or_permission_error_stops_the_run_even_mid_way(self):
        from src.netsuite.client import NetSuiteAPIError
        results, _ = self._run([None, NetSuiteAPIError(403, "Forbidden", "Permission violation"), None, None])
        self.assertEqual([r.ok for r in results], [True, False])

    def test_a_non_locked_failure_after_the_first_write_does_not_stop_the_run(self):
        from src.netsuite.client import NetSuiteAPIError
        results, _ = self._run([None, NetSuiteAPIError(400, "Bad Request", "Record not found"), None])
        self.assertEqual([r.ok for r in results], [True, False, True])

    def test_failure_counts_separate_locked_periods_from_other_failures(self):
        from src.netsuite.client import NetSuiteAPIError
        results, _ = self._run([None, self._locked(), NetSuiteAPIError(400, "Bad Request", "x"), self._locked()])
        self.assertEqual(wb.failure_counts(results), {wb.CAT_PERIOD_LOCKED: 2, wb.CAT_WRITE_FAILED: 1})

    def test_the_log_records_each_writes_category_and_the_failure_totals(self):
        import json, tempfile
        results, _ = self._run([None, self._locked()])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(wb, "_LOG_DIR", tmp):
            path = wb.write_apply_log(mock.Mock(domain_id="x-sb1"), STMT, results, [])
            log = json.load(open(path, encoding="utf-8"))
        self.assertEqual([w["category"] for w in log["writes"]], ["written", "period locked"])
        self.assertEqual(log["failed_counts"], {"period locked": 1})


class RecordChangedRetryTests(unittest.TestCase):
    CHANGED = "Error while accessing a resource. Record has been changed."

    def _plan(self):
        return wb.plan_matched(_row(), [dict(_txn("-100"), id="501")], _ctx())

    def _changed(self):
        from src.netsuite.client import NetSuiteAPIError
        return NetSuiteAPIError(400, "Bad Request", '{"detail":"' + self.CHANGED + '"}')

    def _apply(self, errors, held_by=""):
        ns = mock.Mock()
        ns.patch_record.side_effect = errors
        ns.suiteql.return_value = [{"ref": held_by}] if held_by else [{}]
        with mock.patch.object(wb, "_read_back_bill", return_value=""), \
             mock.patch.object(wb.time, "sleep"):
            return wb.apply_plan(ns, self._plan()), ns

    def test_a_conflict_is_retried_and_then_succeeds(self):
        result, ns = self._apply([self._changed(), None])
        self.assertTrue(result.ok)
        self.assertEqual(ns.patch_record.call_count, 2)

    def test_if_another_statement_saved_first_ours_does_not_overwrite_it(self):
        result, ns = self._apply([self._changed(), None], held_by="STMT-OTHER")
        self.assertFalse(result.ok)
        self.assertEqual(result.category, wb.CAT_HELD_BY_OTHER)
        self.assertIn("STMT-OTHER", result.detail)
        self.assertEqual(ns.patch_record.call_count, 1)   # no second write

    def test_a_record_stamped_with_our_own_id_is_not_treated_as_someone_elses(self):
        result, ns = self._apply([self._changed(), None], held_by=STMT)
        self.assertTrue(result.ok)
        self.assertEqual(ns.patch_record.call_count, 2)

    def test_persistent_conflicts_give_up_as_an_ordinary_failure(self):
        result, ns = self._apply([self._changed()] * 3)
        self.assertFalse(result.ok)
        self.assertEqual(result.category, wb.CAT_WRITE_FAILED)
        self.assertEqual(ns.patch_record.call_count, 3)   # first try + 2 retries

    def test_other_errors_are_not_retried(self):
        from src.netsuite.client import NetSuiteAPIError
        result, ns = self._apply([NetSuiteAPIError(400, "Bad Request", "Invalid field value")])
        self.assertEqual(ns.patch_record.call_count, 1)
        self.assertEqual(result.category, wb.CAT_WRITE_FAILED)

    def test_a_bill_another_statement_saved_first_does_not_stop_the_run(self):
        ns = mock.Mock()
        ns.patch_record.side_effect = [self._changed(), None, None]
        ns.suiteql.return_value = [{"ref": "STMT-OTHER"}]
        plans = [wb.plan_matched(_row(invoice=f"INV{i}"), [dict(_txn("-100"), id=str(600 + i), tranid=f"INV{i}")], _ctx())
                 for i in range(3)]
        with mock.patch.object(wb, "_read_back_bill", return_value=""), mock.patch.object(wb.time, "sleep"):
            results = wb.apply_plans(ns, plans)
        self.assertEqual([r.ok for r in results], [False, True, True])
        self.assertEqual(wb.failure_counts(results), {wb.CAT_HELD_BY_OTHER: 1})


class ErrorLogTests(unittest.TestCase):
    def test_a_failed_run_leaves_a_log_naming_the_error(self):
        import json, tempfile
        try:
            raise AttributeError("'NoneType' object has no attribute 'lower'")
        except AttributeError as exc:
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(wb, "_LOG_DIR", tmp):
                path = wb.write_error_log(STMT, exc)
                log = json.load(open(path, encoding="utf-8"))
        self.assertTrue(path.endswith("_ERROR.json"))
        self.assertEqual((log["statement_id"], log["error_type"]), (STMT, "AttributeError"))
        self.assertIn("has no attribute 'lower'", log["error"])
        self.assertTrue(any("raise AttributeError" in line for line in log["traceback"]))

    def test_an_unwritable_log_directory_is_not_fatal(self):
        with mock.patch.object(wb.os, "makedirs", side_effect=OSError("read-only")):
            self.assertEqual(wb.write_error_log(STMT, RuntimeError("x")), "")


class UnattemptedWritesTests(unittest.TestCase):
    """A run that stops early must not make the writes it never reached vanish."""

    def _plans(self, n=3):
        return [wb.plan_matched(_row(invoice=f"INV{i}"), [dict(_txn("-100"), id=str(700 + i), tranid=f"INV{i}")], _ctx())
                for i in range(n)]

    def _stopped_run(self, plans):
        """First write fails for a reason that ends the run, so only one result exists."""
        from src.netsuite.client import NetSuiteAPIError
        ns = mock.Mock()
        ns.patch_record.side_effect = NetSuiteAPIError(400, "Bad Request", "Invalid field value")
        with mock.patch.object(wb, "_read_back_bill", return_value=""):
            return wb.apply_plans(ns, plans)

    def test_the_writes_a_stopped_run_never_reached_are_identified(self):
        plans = self._plans(3)
        results = self._stopped_run(plans)
        self.assertEqual(len(results), 1)
        self.assertEqual([p.invoice_number for p in wb.unattempted_plans(plans, results)], ["INV1", "INV2"])

    def test_plans_that_are_not_writes_are_never_called_unattempted(self):
        skipped = wb._skip("X", None, "nope", category=wb.CAT_NOT_IN_SANDBOX)
        self.assertEqual(wb.unattempted_plans([skipped], []), [])

    def test_a_complete_run_has_nothing_unattempted(self):
        plans = self._plans(2)
        ns = mock.Mock()
        with mock.patch.object(wb, "_read_back_bill", return_value=""):
            results = wb.apply_plans(ns, plans)
        self.assertEqual(wb.unattempted_plans(plans, results), [])

    def test_the_counts_include_them_only_when_results_are_given(self):
        plans = self._plans(3) + [wb._skip("S", None, "gone", category=wb.CAT_NOT_IN_SANDBOX)]
        results = self._stopped_run(plans)
        self.assertEqual(wb.skip_counts(plans, results),
                         {wb.CAT_NOT_IN_SANDBOX: 1, wb.CAT_NOT_ATTEMPTED: 2})
        self.assertEqual(wb.skip_counts(plans), {wb.CAT_NOT_IN_SANDBOX: 1})      # old call still works

    def test_the_file_log_lists_each_one_with_its_reason(self):
        import json, tempfile
        plans = self._plans(3)
        results = self._stopped_run(plans)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(wb, "_LOG_DIR", tmp):
            path = wb.write_apply_log(mock.Mock(domain_id="x-sb1"), STMT, results, plans)
            log = json.load(open(path, encoding="utf-8"))
        self.assertEqual([n["invoice_number"] for n in log["not_written"]], ["INV1", "INV2"])
        self.assertEqual({n["reason"] for n in log["not_written"]}, {wb.CAT_NOT_ATTEMPTED})
        self.assertEqual(log["not_written_counts"], {wb.CAT_NOT_ATTEMPTED: 2})
        self.assertEqual(len(log["writes"]), 1)


class RevertLogTests(unittest.TestCase):
    def _results(self):
        patch = {"op": "PATCH", "record_type": "vendorbill", "record_id": "1", "invoice_number": "A",
                 "body": {"custbody_reconciled": False}}
        delete = {"op": "DELETE", "record_type": "customrecord_statement_line", "record_id": "9", "invoice_number": "B"}
        return [(patch, True, "reverted"), (delete, False, "HTTPError: nope")]

    def test_an_undo_run_is_written_to_its_own_file_with_the_counts(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(wb, "_LOG_DIR", tmp):
            path = wb.write_revert_log(mock.Mock(domain_id="x-sb1"), STMT, self._results())
            log = json.load(open(path, encoding="utf-8"))
        self.assertTrue(path.endswith("_REVERT.json"))
        self.assertEqual((log["statement_id"], log["reverted"], log["failed"]), (STMT, 1, 1))
        self.assertEqual([r["op"] for r in log["reverts"]], ["PATCH", "DELETE"])
        self.assertEqual(log["reverts"][0]["body"], {"custbody_reconciled": False})
        self.assertFalse(log["reverts"][1]["ok"])

    def test_an_unwritable_log_directory_is_not_fatal(self):
        with mock.patch.object(wb.os, "makedirs", side_effect=OSError("read-only")):
            self.assertEqual(wb.write_revert_log(mock.Mock(domain_id="x"), STMT, self._results()), "")


class StatementLineDateTests(unittest.TestCase):
    def _line_ctx(self, lines):
        ctx = _ctx()
        ctx.line_dates = wb._index_line_dates(lines)
        return ctx

    def _line(self, invoice, day, charge):
        from datetime import date
        return {"invoice_number": invoice, "line_date": date.fromisoformat(day),
                "charge_amount": charge, "payment_amount": None}

    def _plan(self, ctx, amount="75.00", invoice="INV1"):
        (plan,) = wb.plan_exception_row(_row(amount, wb.REASON_NOT_FOUND, invoice=invoice), [], ctx, set())
        return plan

    def test_statement_line_gets_the_invoice_date(self):
        plan = self._plan(self._line_ctx([self._line("INV1", "2026-08-13", -75.0)]))
        self.assertEqual(plan.fields["custrecord_sl_date"], "2026-08-13")
        self.assertIn("invoice date", plan.note)

    def test_falls_back_to_the_run_date_when_the_statement_has_no_date(self):
        plan = self._plan(self._line_ctx([]))
        self.assertEqual(plan.fields["custrecord_sl_date"], "2026-10-07")
        self.assertIn("run date", plan.note)

    def test_several_lines_pick_the_one_whose_amount_matches(self):
        lines = [self._line("INV1", "2026-07-03", 832.14), self._line("INV1", "2026-08-13", -75.0)]
        plan = self._plan(self._line_ctx(lines), amount="75.00")
        self.assertEqual(plan.fields["custrecord_sl_date"], "2026-08-13")

    def test_several_lines_with_no_amount_match_take_the_earliest(self):
        lines = [self._line("INV1", "2026-08-13", -10.0), self._line("INV1", "2026-07-03", 20.0)]
        plan = self._plan(self._line_ctx(lines), amount="999.00")
        self.assertEqual(plan.fields["custrecord_sl_date"], "2026-07-03")

    def test_lines_without_an_invoice_number_do_not_break_planning(self):
        # Regression: a payment/summary line with a NULL invoice_number made
        # the whole statement fail to plan, so nothing was written for it.
        lines = [self._line("INV1", "2026-08-13", 75.0),
                 {"invoice_number": None, "line_date": __import__("datetime").date(2026, 8, 1),
                  "charge_amount": None, "payment_amount": -50.0}]
        plan = self._plan(self._line_ctx(lines))
        self.assertEqual(plan.fields["custrecord_sl_date"], "2026-08-13")

    def test_invoice_lookup_ignores_case(self):
        plan = self._plan(self._line_ctx([self._line("inv1", "2026-08-13", 75.0)]))
        self.assertEqual(plan.fields["custrecord_sl_date"], "2026-08-13")

    def test_reconciled_starts_unchecked_and_its_date_is_not_sent(self):
        plan = self._plan(self._line_ctx([]))
        self.assertIs(plan.fields["custrecord_sl_reconciled"], False)
        self.assertNotIn("custrecord_sl_reconciled_date", plan.fields)

    def test_bills_are_left_alone(self):
        matched = wb.plan_matched(_row(), [_txn("-100")], _ctx())
        self.assertNotIn("custrecord_sl_date", matched.fields)
        self.assertNotIn("custrecord_sl_reconciled", matched.fields)


class StatementLineLocationTests(unittest.TestCase):
    def test_all_records_at_one_location_gives_that_location(self):
        sandbox = {"a": [_txn("-1", location="19")], "b": [_txn("-2", location="19")]}
        self.assertEqual(wb._statement_location(sandbox), "19")

    def test_records_without_a_location_are_ignored(self):
        sandbox = {"a": [_txn("-1", location="19")], "b": [_txn("-2")]}
        self.assertEqual(wb._statement_location(sandbox), "19")

    def test_disagreeing_locations_stay_blank(self):
        sandbox = {"a": [_txn("-1", location="19")], "b": [_txn("-2", location="23")]}
        self.assertIsNone(wb._statement_location(sandbox))

    def test_no_records_found_stays_blank(self):
        self.assertIsNone(wb._statement_location({}))

    def test_statement_line_carries_the_statements_location(self):
        ctx = _ctx()
        ctx.primary_location = "19"
        (plan,) = wb.plan_exception_row(_row("5", wb.REASON_NOT_FOUND), [], ctx, set())
        self.assertEqual(plan.fields["custrecord_sl_location"], {"id": "19"})

    def test_statement_line_has_no_location_field_when_unknown(self):
        (plan,) = wb.plan_exception_row(_row("5", wb.REASON_NOT_FOUND), [], _ctx(), set())
        self.assertNotIn("custrecord_sl_location", plan.fields)


class NotWrittenReasonTests(unittest.TestCase):
    def test_matched_but_missing_from_sandbox_is_counted_as_not_in_sandbox(self):
        plan = wb.plan_matched(_row(), [], _ctx())
        self.assertEqual(wb.skip_category(plan), wb.CAT_NOT_IN_SANDBOX)

    def test_sandbox_amount_drift_has_its_own_reason(self):
        plan = wb.plan_matched(_row("100.00"), [_txn("-250.00")], _ctx())
        self.assertEqual(wb.skip_category(plan), wb.CAT_AMOUNT_NOT_TIED)

    def test_up_to_date_and_reconciled_earlier_have_reasons(self):
        done = _txn("-100", custbody_reconciled="T", custbody_statement_reference=STMT,
                    custbody_statement_link="https://app.example/statements/abc/pdf")
        earlier = _txn("-100", custbody_reconciled="T", custbody_statement_reference="STMT-OLD")
        self.assertEqual(wb.skip_category(wb.plan_matched(_row(), [done], _ctx())), wb.CAT_UP_TO_DATE)
        self.assertEqual(wb.skip_category(wb.plan_matched(_row(), [earlier], _ctx())), wb.CAT_RECONCILED_EARLIER)

    def test_reasons_with_no_bill_are_labelled(self):
        (plan,) = wb.plan_exception_row(_row("5", "Vendor Not Resolved in NetSuite"), [], _ctx(), set())
        self.assertEqual(wb.skip_category(plan), wb.CAT_NO_BILL_TO_WRITE)

    def test_counts_only_cover_lines_that_were_not_written(self):
        write = wb.plan_matched(_row(), [_txn("-100")], _ctx())
        missing_a = wb.plan_matched(_row(invoice="A"), [], _ctx())
        missing_b = wb.plan_matched(_row(invoice="B"), [], _ctx())
        self.assertEqual(wb.skip_counts([write, missing_a, missing_b]), {wb.CAT_NOT_IN_SANDBOX: 2})

    def test_apply_log_records_skipped_lines_with_their_reason(self):
        import json, tempfile
        write = wb.plan_matched(_row(), [_txn("-100")], _ctx())
        missing = wb.plan_matched(_row(invoice="GONE"), [], _ctx())
        result = wb.ApplyResult(write, True, "updated", write.record_id)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(wb, "_LOG_DIR", tmp):
            path = wb.write_apply_log(mock.Mock(domain_id="x-sb1"), STMT, [result], [write, missing])
            log = json.load(open(path, encoding="utf-8"))
        self.assertEqual(len(log["writes"]), 1)
        self.assertEqual([n["invoice_number"] for n in log["not_written"]], ["GONE"])
        self.assertEqual(log["not_written"][0]["reason"], wb.CAT_NOT_IN_SANDBOX)
        self.assertEqual(log["not_written_counts"], {wb.CAT_NOT_IN_SANDBOX: 1})


class RevertByStatementTests(unittest.TestCase):
    def _ns(self, bills, lines):
        ns = mock.Mock()
        ns.suiteql.side_effect = [bills, lines]
        return ns

    def test_finds_bills_credits_and_statement_lines_by_statement_id(self):
        ns = self._ns(
            [{"id": "1", "tranid": "A", "type": "VendBill"}, {"id": "2", "tranid": "CM-B", "type": "VendCred"}],
            [{"id": "9", "inv": "C"}])
        actions = wb.find_revert_actions_for_statement(ns, STMT)
        self.assertEqual([(a["op"], a["record_type"], a["record_id"]) for a in actions], [
            ("PATCH", "vendorbill", "1"), ("PATCH", "vendorcredit", "2"),
            ("DELETE", "customrecord_statement_line", "9")])
        self.assertEqual(actions[0]["body"], {
            "custbody_reconciled": False, "custbody_reconciled_date": None,
            "custbody_statement_reference": None, "custbody_reconciliation_exception": None})

    def test_the_search_is_by_this_statement_id_only(self):
        ns = self._ns([], [])
        wb.find_revert_actions_for_statement(ns, STMT)
        for call in ns.suiteql.call_args_list:
            self.assertIn(f"'{STMT}'", call.args[0])

    def test_link_field_is_cleared_only_when_it_holds_a_value(self):
        ns = self._ns([{"id": "1", "tranid": "A", "type": "VendBill", "custbody_statement_link": "https://x"},
                       {"id": "2", "tranid": "B", "type": "VendBill"}], [])
        with_link, without_link = wb.find_revert_actions_for_statement(ns, STMT)
        self.assertIn("custbody_statement_link", with_link["body"])
        self.assertNotIn("custbody_statement_link", without_link["body"])

    def test_nothing_found_means_no_actions(self):
        self.assertEqual(wb.find_revert_actions_for_statement(self._ns([], []), STMT), [])

    def test_unsafe_statement_ids_are_refused_before_any_query(self):
        ns = mock.Mock()
        for bad in ("", None, "x or y", "STMT 1", "a;b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                wb.find_revert_actions_for_statement(ns, bad)
        ns.suiteql.assert_not_called()


class PlanUnwrittenReasonsTests(unittest.TestCase):
    def test_reasons_with_no_bill_to_write_to_are_skipped(self):
        for reason in ("Vendor Not Resolved in NetSuite", "EXTRACTION_INCOMPLETE"):
            with self.subTest(reason=reason):
                (plan,) = wb.plan_exception_row(_row("5", reason), [], _ctx(), set())
                self.assertEqual(plan.action, wb.SKIP_REVIEW)


def _recon(invoice, record_id=None, amount=None, source="auto", status="Matched"):
    return {"invoice_number": invoice, "source": source, "status": status,
            "netsuite_internal_id": record_id, "netsuite_amount": amount}


class MatchedRecordFromReconTests(unittest.TestCase):
    """2026-10-30: matched lines are written to the record the matcher picked
    (recon.netsuite_internal_id)."""

    def _plans(self, matched=(), exceptions=(), recon=(), sandbox=None, by_id=None):
        results = {"header": {"vendor_id": "V", "vendor_name_raw": "Vendor", "shop_name_raw": None},
                   "matched": list(matched), "exceptions": list(exceptions), "lines": []}
        self.asked_ids = []

        def fetch_by_id(ns, entity_ids, record_ids):
            self.asked_ids = sorted(record_ids)
            return {k: v for k, v in (by_id or {}).items() if k in record_ids}

        with mock.patch.object(wb, "load_statement_results", return_value=results), \
             mock.patch.object(wb, "resolve_entity_ids", return_value=["111"]), \
             mock.patch.object(wb, "resolve_pdf_link", return_value=(None, "")), \
             mock.patch.object(wb, "fetch_exception_list_ids", return_value={"Amount differs": "7"}), \
             mock.patch.object(wb, "fetch_sandbox_transactions", return_value=sandbox or {}), \
             mock.patch.object(wb, "load_recon_rows", return_value=None if recon is None else list(recon)), \
             mock.patch.object(wb, "fetch_transactions_by_id", side_effect=fetch_by_id), \
             mock.patch.object(wb, "fetch_existing_statement_lines", return_value=set()):
            return wb.build_plans(STMT, mock.Mock())[1]

    def test_credit_found_under_another_number_is_written_to_the_matchers_record(self):
        # Parts By Cochran, STMT-8D0C0DCB: line 81122710 $50 matched credit CM81122710-1;
        # the printed number is a $67.52 bill.
        bill = dict(_txn("-67.52"), id="4420349", tranid="81122710")
        credit = dict(_txn("50", ns_type="VendCred"), id="4536787", tranid="CM81122710-1")
        (plan,) = self._plans(matched=[_row("50.00", invoice="81122710")],
                              recon=[_recon("81122710", "4536787", 50.0)],
                              sandbox={"81122710": [bill]}, by_id={"4536787": credit})
        self.assertEqual((plan.action, plan.record_type, plan.record_id), (wb.PATCH_MATCHED, "vendorcredit", "4536787"))
        self.assertEqual(plan.invoice_number, "81122710")

    def test_exact_number_match_writes_the_same_record_as_before(self):
        txn = dict(_txn("-100"), id="500")
        (plan,) = self._plans(matched=[_row()], recon=[_recon("INV1", "500", 100.0)],
                              sandbox={"inv1": [txn]}, by_id={"500": txn})
        self.assertEqual((plan.action, plan.record_id), (wb.PATCH_MATCHED, "500"))

    def test_no_recon_row_falls_back_to_the_printed_number(self):
        (plan,) = self._plans(matched=[_row()], recon=[], sandbox={"inv1": [dict(_txn("-100"), id="500")]})
        self.assertEqual((plan.action, plan.record_id), (wb.PATCH_MATCHED, "500"))
        self.assertEqual(self.asked_ids, [])

    def test_record_gone_from_netsuite_falls_back_to_the_printed_number(self):
        # Voided since, or filed under another vendor: the by-id read returns nothing.
        (plan,) = self._plans(matched=[_row()], recon=[_recon("INV1", "999", 100.0)],
                              sandbox={"inv1": [dict(_txn("-100"), id="500")]}, by_id={})
        self.assertEqual(plan.record_id, "500")

    def test_record_whose_amount_no_longer_ties_is_skipped(self):
        credit = dict(_txn("40", ns_type="VendCred"), id="4536787", tranid="CM81122710-1")
        (plan,) = self._plans(matched=[_row("50.00", invoice="81122710")],
                              recon=[_recon("81122710", "4536787", 50.0)], by_id={"4536787": credit})
        self.assertEqual(wb.skip_category(plan), wb.CAT_AMOUNT_NOT_TIED)

    def test_invoice_printed_twice_pairs_each_line_by_amount(self):
        a = dict(_txn("-100"), id="601", tranid="INV1")
        b = dict(_txn("30", ns_type="VendCred"), id="602", tranid="CMINV1")
        plans = self._plans(matched=[_row("100.00"), _row("30.00")],
                            recon=[_recon("INV1", "601", 100.0), _recon("INV1", "602", 30.0)],
                            by_id={"601": a, "602": b})
        self.assertEqual([p.record_id for p in plans], ["601", "602"])

    def test_two_picked_records_at_the_same_amount_fall_back(self):
        plans = self._plans(matched=[_row()], recon=[_recon("INV1", "601", 100.0), _recon("INV1", "602", 100.0)],
                            sandbox={"inv1": [dict(_txn("-100"), id="500")]})
        self.assertEqual(plans[0].record_id, "500")

    def test_manual_rows_are_not_used_to_pick_the_record(self):
        # Only the matcher's own (auto) rows decide WHERE a matched line is written.
        (plan,) = self._plans(matched=[_row()], recon=[_recon("INV1", "777", 100.0, source="manual",
                                                               status="Matched manually")],
                              sandbox={"inv1": [dict(_txn("-100"), id="500")]})
        self.assertEqual(plan.record_id, "500")
        self.assertEqual(self.asked_ids, [])

    def test_unreadable_recon_falls_back_to_the_printed_number(self):
        plans = self._plans(matched=[_row(invoice="M1")],
                            exceptions=[_row("100.00", wb.REASON_AMOUNT_MISMATCH), _row("5", wb.REASON_NOT_FOUND, "NF1")],
                            recon=None, sandbox={"m1": [dict(_txn("-100"), id="501", tranid="M1")],
                                                 "inv1": [_txn("-90")]})
        self.assertEqual([p.action for p in plans], [wb.PATCH_MATCHED, wb.PATCH_EXCEPTION, wb.CREATE_STATEMENT_LINE])

    def test_exceptions_are_written_as_before(self):
        plans = self._plans(matched=[_row(invoice="M1")], exceptions=[_row("100.00", wb.REASON_AMOUNT_MISMATCH)],
                            recon=[_recon("M1", "501", 100.0)],
                            sandbox={"m1": [dict(_txn("-100"), id="501", tranid="M1")], "inv1": [_txn("-90")]},
                            by_id={"501": dict(_txn("-100"), id="501", tranid="M1")})
        self.assertEqual([p.action for p in plans], [wb.PATCH_MATCHED, wb.PATCH_EXCEPTION])


class LoadReconRowsTests(unittest.TestCase):
    def test_reads_only_this_statements_active_rows(self):
        with mock.patch("src.lakehouse.connection.execute_query", return_value=[]) as query:
            self.assertEqual(wb.load_recon_rows(STMT), [])
        sql, params = query.call_args[0]
        self.assertIn("is_active = 1", sql)
        self.assertEqual(params, [STMT])

    def test_read_failure_returns_none(self):
        with mock.patch("src.lakehouse.connection.execute_query", side_effect=RuntimeError("db down")):
            self.assertIsNone(wb.load_recon_rows(STMT))


class FetchTransactionsByIdTests(unittest.TestCase):
    def test_reads_by_id_for_the_vendors_entities_only(self):
        ns = mock.Mock()
        ns.suiteql.return_value = [dict(_txn("50", ns_type="VendCred"), id=4536787)]
        found = wb.fetch_transactions_by_id(ns, ["410838", "x;drop"], ["4536787", "bad'id"])
        self.assertEqual(list(found), ["4536787"])
        query = ns.suiteql.call_args[0][0]
        self.assertIn("t.id IN (4536787)", query)
        self.assertIn("t.entity IN (410838)", query)
        self.assertIn("t.voided = 'F'", query)

    def test_nothing_to_read(self):
        ns = mock.Mock()
        self.assertEqual(wb.fetch_transactions_by_id(ns, ["1"], []), {})
        ns.suiteql.assert_not_called()


if __name__ == "__main__":
    unittest.main()
