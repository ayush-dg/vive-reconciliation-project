"""
tests/test_netsuite_guard.py

The NetSuite write guardrails (src/netsuite/guard.py): the code may only write
our custom fields. Offline -- no NetSuite calls are made.
"""

import os
import sys
import unittest
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.netsuite import guard
from src.netsuite import writeback as wb
from src.netsuite.client import NetSuiteClient
from src.netsuite.guard import WriteBlocked

STMT = "STMT-TEST0001"
LINK = "https://vivecollision.sharepoint.com/sites/x/Shared%20Documents/BMW.pdf"


def _ctx(link=LINK):
    return wb.StatementContext(
        statement_id=STMT, vendor_id="V", vendor_name="Vendor", shop="Shop",
        entity_ids=["111"], link=link, link_note="", today="2026-10-07",
        exception_ids={"Amount differs": "1", "Duplicate": "3"}, primary_entity="111", primary_location="33",
    )


def _row(invoice="INV1", amount="100.00", reason=None):
    row = {"invoice_number": invoice, "original_invoice_number": invoice,
           "statement_amount": Decimal(amount), "shop": "Shop"}
    if reason:
        row["exception_reason"] = reason
    return row


def _txn(total="-100", ns_type="VendBill", **extra):
    row = {"id": "500", "tranid": "INV1", "entity": "111", "type": ns_type, "foreigntotal": total}
    row.update(extra)
    return row


class _Client(NetSuiteClient):
    """The real client with the network replaced: records what would have been sent."""

    def __init__(self):
        env = {"SANDBOX_ACCOUNT_ID": "7321761-sb1", "SANDBOX_CONSUMER_KEY": "k", "SANDBOX_CONSUMER_SECRET": "s",
               "SANDBOX_TOKEN_ID": "t", "SANDBOX_TOKEN_SECRET": "ts"}
        with mock.patch.dict(os.environ, env, clear=True):
            super().__init__(session=mock.Mock())
        self.sent = []
        self.rows = []

    def _request(self, method, url, **kwargs):
        self.sent.append((method, url, kwargs.get("json")))
        resp = mock.Mock()
        resp.headers = {"Location": "https://x/record/v1/customrecord_statement_line/101"}
        return resp

    def suiteql(self, query):
        return self.rows


class EveryRealWriteIsAllowedTests(unittest.TestCase):
    """If a planner ever starts sending a field that is not on the allowlist, these fail."""

    def _check(self, plan):
        if plan.action == wb.CREATE_STATEMENT_LINE:
            guard.check_create(plan.record_type or wb.STATEMENT_LINE_RECORD, plan.fields)
        else:
            guard.check_patch(plan.record_type, plan.record_id, plan.fields)

    def test_matched_bill_and_credit(self):
        for ns_type in ("VendBill", "VendCred"):
            self._check(wb.plan_matched(_row(), [_txn(ns_type=ns_type)], _ctx()))

    def test_matched_without_a_link(self):
        self._check(wb.plan_matched(_row(), [_txn()], _ctx(link=None)))

    def test_amount_mismatch_and_duplicate_flags(self):
        for plan in wb.plan_exception_on_bills(_row(), [_txn("-90")], _ctx(), wb.EXCEPTION_AMOUNT_DIFFERS):
            self._check(plan)
        for plan in wb.plan_exception_on_bills(_row(), [_txn(), _txn(id="501")], _ctx(), wb.EXCEPTION_DUPLICATE):
            self._check(plan)

    def test_link_only_write(self):
        txn = _txn(custbody_reconciled="T", custbody_statement_reference=STMT)
        plan = wb.plan_matched(_row(), [txn], _ctx())
        self.assertEqual(plan.action, wb.PATCH_LINK_ONLY)
        self._check(plan)

    def test_not_found_statement_line(self):
        plan = wb.plan_not_found(_row(), _ctx(), set())
        self.assertEqual(plan.action, wb.CREATE_STATEMENT_LINE)
        self._check(plan)

    def test_the_undo_bodies(self):
        for body in (wb._RESET_BODY, dict(wb._RESET_BODY, custbody_statement_link=None)):
            guard.check_patch("vendorbill", "500", body)
        log = {"statement_id": STMT, "writes": [{
            "ok": True, "action": wb.PATCH_MATCHED, "record_type": "vendorbill", "record_id": "500", "invoice_number": "I",
            "fields_sent": list(wb._RESET_BODY), "previous": {"custbody_reconciled": "F", "custbody_reconciled_date": "10/1/2026",
                                                              "custbody_reconciliation_exception": "1"}}]}
        (action,) = wb.build_revert_actions(log)
        guard.check_patch(action["record_type"], action["record_id"], action["body"])

    def test_the_manual_match_bodies(self):
        guard.check_patch("vendorbill", "500", {
            "custbody_reconciled": True, "custbody_reconciled_date": "2026-10-22", "custbody_statement_reference": STMT,
            "custbody_reconciliation_exception": None, "custbody_matched_bill": "INV1", "custbody_statement_link": LINK})
        guard.check_patch("customrecord_statement_line", "9", {
            "custrecord_sl_status": "Matched", "custrecord_sl_exception_type": None,
            "custrecord_sl_matched_bill": {"id": "500"}, "custrecord_sl_reconciled": True,
            "custrecord_sl_reconciled_date": "2026-10-22"})


class WhatIsRefusedTests(unittest.TestCase):
    def test_any_other_record_type(self):
        for rtype in ("vendor", "vendorpayment", "journalentry", "transaction", "customer", ""):
            with self.subTest(rtype=rtype):
                with self.assertRaises(WriteBlocked):
                    guard.check_patch(rtype, "1", {"custbody_reconciled": True})
                with self.assertRaises(WriteBlocked):
                    guard.check_create(rtype, {"name": "x"})
                with self.assertRaises(WriteBlocked):
                    guard.check_delete(rtype, "1", STMT)

    def test_bills_and_credits_can_never_be_created_or_deleted(self):
        for rtype in ("vendorbill", "vendorcredit"):
            with self.assertRaises(WriteBlocked):
                guard.check_create(rtype, {"custbody_reconciled": True})
            with self.assertRaises(WriteBlocked):
                guard.check_delete(rtype, "500", STMT)

    def test_a_field_that_is_not_ours(self):
        for body in ({"memo": "x"}, {"custbody_reconciled": True, "total": 5}, {"tranid": "X"},
                     {"custbody_other": "x"}, {"item": {"items": []}}, {"entity": {"id": "1"}}, {"trandate": "2026-01-01"}):
            with self.subTest(body=body), self.assertRaises(WriteBlocked):
                guard.check_patch("vendorbill", "500", body)
        with self.assertRaises(WriteBlocked):
            guard.check_patch("customrecord_statement_line", "9", {"custrecord_other": "x"})

    def test_an_empty_or_odd_body(self):
        for body in ({}, None, [], "x", [("custbody_reconciled", True)]):
            with self.subTest(body=body), self.assertRaises(WriteBlocked):
                guard.check_patch("vendorbill", "500", body)

    def test_a_record_id_that_is_not_a_number(self):
        for rid in ("500/../vendorbill/1", "5 0", "", None, "abc", True, "1;DROP"):
            with self.subTest(rid=rid), self.assertRaises(WriteBlocked):
                guard.check_patch("vendorbill", rid, {"custbody_reconciled": True})

    def test_bad_values(self):
        bad = [
            {"custbody_reconciled": "T"}, {"custbody_reconciled": 1}, {"custbody_reconciled": None},
            {"custbody_reconciled_date": "10/22/2026"}, {"custbody_reconciled_date": "2026-10-22T00:00:00"},
            {"custbody_statement_reference": 5}, {"custbody_statement_reference": "S" * 101},
            {"custbody_statement_link": "http://insecure.example/x.pdf"}, {"custbody_statement_link": "https://x/ y"},
            {"custbody_statement_link": "https://x/" + "a" * 999}, {"custbody_statement_link": "javascript:alert(1)"},
            {"custbody_reconciliation_exception": "1"}, {"custbody_reconciliation_exception": {"id": "x"}},
            {"custbody_reconciliation_exception": {"id": None}}, {"custbody_reconciliation_exception": {"id": "1", "x": "2"}},
            {"custbody_matched_bill": "M" * 201},
        ]
        for body in bad:
            with self.subTest(body=body), self.assertRaises(WriteBlocked):
                guard.check_patch("vendorbill", "500", body)

    def test_a_new_statement_line_needs_its_identity(self):
        with self.assertRaises(WriteBlocked):
            guard.check_create(wb.STATEMENT_LINE_RECORD, {"custrecord_sl_status": "No match found"})
        with self.assertRaises(WriteBlocked):
            guard.check_create(wb.STATEMENT_LINE_RECORD, {"name": "x", "custrecord_sl_statement_id": STMT})

    def test_statement_line_value_checks(self):
        base = {"name": "n", "custrecord_sl_statement_id": STMT, "custrecord_sl_invoice_number": "I"}
        guard.check_create(wb.STATEMENT_LINE_RECORD, dict(base, custrecord_sl_statement_amount=12.5,
                                                          custrecord_sl_vendor={"id": "1"}, custrecord_sl_location=None))
        for extra in ({"custrecord_sl_statement_amount": "12"}, {"custrecord_sl_statement_amount": True},
                      {"custrecord_sl_vendor": {"id": "abc"}}, {"custrecord_sl_vendor": "1"},
                      {"custrecord_sl_date": "yesterday"}, {"custrecord_sl_reconciled": "F"}):
            with self.subTest(extra=extra), self.assertRaises(WriteBlocked):
                guard.check_create(wb.STATEMENT_LINE_RECORD, dict(base, **extra))

    def test_delete_needs_a_statement_id(self):
        for statement_id in (None, "", 5):
            with self.assertRaises(WriteBlocked):
                guard.check_delete(wb.STATEMENT_LINE_RECORD, "9", statement_id)
        guard.check_delete(wb.STATEMENT_LINE_RECORD, "9", STMT)


class TheClientEnforcesItTests(unittest.TestCase):
    """The guard sits inside the real client, ahead of the network."""

    def test_a_blocked_write_sends_nothing(self):
        client = _Client()
        with self.assertRaises(WriteBlocked):
            client.patch_record("vendorbill", "500", {"memo": "hello"})
        with self.assertRaises(WriteBlocked):
            client.patch_record("vendor", "500", {"custbody_reconciled": True})
        with self.assertRaises(WriteBlocked):
            client.create_record("vendorbill", {"custbody_reconciled": True})
        with self.assertRaises(WriteBlocked):
            client.delete_record("vendorbill", "500", STMT)
        self.assertEqual(client.sent, [])

    def test_an_allowed_write_is_sent(self):
        client = _Client()
        client.patch_record("vendorbill", "500", {"custbody_reconciled": True})
        self.assertEqual(client.sent[0][0], "PATCH")
        self.assertEqual(client.sent[0][2], {"custbody_reconciled": True})

    def test_a_statement_line_is_deleted_only_for_its_own_statement(self):
        client = _Client()
        client.rows = [{"sid": "STMT-OTHER"}]
        with self.assertRaises(WriteBlocked):
            client.delete_record(wb.STATEMENT_LINE_RECORD, "9", STMT)
        self.assertEqual(client.sent, [])
        client.rows = [{"sid": STMT}]
        client.delete_record(wb.STATEMENT_LINE_RECORD, "9", STMT)
        self.assertEqual([m for m, _, _ in client.sent], ["DELETE"])

    def test_a_delete_with_no_statement_id_or_no_row_is_refused(self):
        client = _Client()
        with self.assertRaises(WriteBlocked):
            client.delete_record(wb.STATEMENT_LINE_RECORD, "9")
        client.rows = []
        with self.assertRaises(WriteBlocked):
            client.delete_record(wb.STATEMENT_LINE_RECORD, "9", STMT)
        self.assertEqual(client.sent, [])


class ABlockedWriteEndsTheRunTests(unittest.TestCase):
    class _Ns:
        domain_id = "7321761-sb1"

        def __init__(self, block_on=None, key_change=None):
            self.block_on, self.key_change, self.patched = block_on, key_change, []

        def patch_record(self, record_type, record_id, body):
            if record_id == self.block_on:
                raise WriteBlocked("field not on the allowlist")
            self.patched.append(record_id)

        def suiteql(self, query):
            row = {"custbody_reconciled": "T", "custbody_statement_reference": STMT,
                   "custbody_statement_link": LINK, "custbody_reconciliation_exception": None}
            if self.key_change:
                row.update(self.key_change)
            return [row]

    def _plans(self):
        return [wb.plan_matched(_row(invoice=f"INV{i}"), [dict(_txn(), id=str(500 + i), tranid=f"INV{i}")], _ctx())
                for i in (1, 2, 3)]

    def test_a_blocked_write_stops_the_run_and_is_recorded_as_blocked(self):
        ns = self._Ns(block_on="501")
        results = wb.apply_plans(ns, self._plans())
        self.assertEqual(len(results), 1, "the run stopped at the first blocked write")
        self.assertEqual(results[0].category, wb.CAT_WRITE_BLOCKED)
        self.assertEqual(ns.patched, [])

    def test_a_key_field_that_changed_stops_the_run(self):
        plans = [wb.plan_matched(_row(invoice=f"INV{i}"),
                                 [dict(_txn(), id=str(500 + i), tranid=f"INV{i}", trandate="10/1/2026", status="B")], _ctx())
                 for i in (1, 2, 3)]
        ns = self._Ns(key_change={"trandate": "10/1/2026", "status": "A"})
        results = wb.apply_plans(ns, plans)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].category, wb.CAT_KEY_FIELD_CHANGED)
        self.assertIn("status", results[0].detail)
        self.assertEqual(len(ns.patched), 1, "the first record was written; nothing after it")

    def test_unchanged_key_fields_do_not_stop_anything(self):
        plans = [wb.plan_matched(_row(invoice=f"INV{i}"),
                                 [dict(_txn(), id=str(500 + i), tranid=f"INV{i}", trandate="10/1/2026", status="B")], _ctx())
                 for i in (1, 2, 3)]
        ns = self._Ns(key_change={"trandate": "10/1/2026", "status": "B"})
        results = wb.apply_plans(ns, plans)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.ok for r in results))


class KeyFieldTests(unittest.TestCase):
    def test_numbers_compare_as_numbers(self):
        self.assertEqual(guard.key_field_changes({"foreigntotal": "-100"}, {"foreigntotal": "-100.00"}), [])
        self.assertEqual(guard.key_field_changes({"foreigntotal": "-100"}, {"foreigntotal": "-101"}), ["foreigntotal"])

    def test_text_is_compared_loosely(self):
        self.assertEqual(guard.key_field_changes({"tranid": "Inv1"}, {"tranid": "INV1 "}), [])
        self.assertEqual(guard.key_field_changes({"tranid": "INV1"}, {"tranid": "INV2"}), ["tranid"])

    def test_a_missing_side_cannot_be_compared_and_is_skipped(self):
        self.assertEqual(guard.key_field_changes({}, {"status": "A"}), [])
        self.assertEqual(guard.key_field_changes({"status": "A"}, {}), [])
        self.assertEqual(guard.key_field_changes(None, None), [])

    def test_every_key_field_is_watched(self):
        before = {name: "1" for name in guard.KEY_FIELDS}
        for name in guard.KEY_FIELDS:
            with self.subTest(name=name):
                self.assertEqual(guard.key_field_changes(before, dict(before, **{name: "2"})), [name])

    def test_the_snapshot_only_keeps_what_is_present(self):
        self.assertEqual(guard.key_snapshot({"tranid": "A", "status": None, "memo": "x"}), {"tranid": "A"})


if __name__ == "__main__":
    unittest.main()
