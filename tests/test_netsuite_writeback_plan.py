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
        txn = _txn("-100", custbody_reconciled="T", custbody_statement_reference=STMT)
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
                   custbody_reconciliation_exception="7")
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


class PdfLinkSwitchTests(unittest.TestCase):
    def test_link_is_off_unless_explicitly_switched_on(self):
        for env in ({}, {"NETSUITE_WRITEBACK_PDF_LINK": "false"}, {"NETSUITE_WRITEBACK_PDF_LINK": ""}):
            with self.subTest(env=env), mock.patch.dict(
                    os.environ, dict(env, APP_PUBLIC_BASE_URL="https://app.example"), clear=True):
                url, note = wb.resolve_pdf_link("STMT-1")
            self.assertIsNone(url)
            self.assertIn("switched off", note)

    def test_switched_on_uses_the_base_url_and_the_document_hash(self):
        env = {"NETSUITE_WRITEBACK_PDF_LINK": "true", "APP_PUBLIC_BASE_URL": "https://app.example/"}
        with mock.patch.dict(os.environ, env, clear=True),              mock.patch("src.lakehouse.connection.execute_query", return_value=[{"document_hash": "ab" * 32}]):
            url, note = wb.resolve_pdf_link("STMT-1")
        self.assertEqual(url, "https://app.example/statements/" + "ab" * 32 + "/pdf")

    def test_plans_carry_no_link_fields_when_there_is_no_link(self):
        ctx = _ctx(link=None)
        matched = wb.plan_matched(_row(), [_txn("-100")], ctx)
        (line,) = wb.plan_exception_row(_row("5", wb.REASON_NOT_FOUND), [], ctx, set())
        self.assertNotIn("custbody_statement_link", matched.fields)
        self.assertNotIn("custrecord_sl_statement_link", line.fields)


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
        done = _txn("-100", custbody_reconciled="T", custbody_statement_reference=STMT)
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


if __name__ == "__main__":
    unittest.main()
