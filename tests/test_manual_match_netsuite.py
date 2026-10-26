"""
tests/test_manual_match_netsuite.py

The NetSuite SANDBOX write for "Accept as match" (src/netsuite/manual_match.py,
2026-10-19), against a fake sandbox that keeps state, so accept -> undo can be
checked end to end: bill reconciled with "Matched Bill" = the statement
invoice, the invoice's Statement Line linked to the bill (updated or
created), another flagged bill's flag cleared, and undo putting everything
back except fields someone changed since.
"""

import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.netsuite import manual_match as mm
from src.netsuite.fields import BODY_FIELDS, MATCHED_BILL_FIELD

RECORD = {"record_type": "Bill", "internal_id": "4677233", "tranid": "23", "entity_id": "81667", "total": 57.54}


class FakeSandbox:
    """Just enough of NetSuiteClient: SuiteQL reads over in-memory records,
    PATCH/POST/DELETE that change them."""

    def __init__(self):
        self.txns = {}      # id -> dict (SuiteQL-shaped: 'T'/'F', ids as strings)
        self.lines = {}     # id -> dict
        self.calls = []
        self.fail_patch = {}  # id -> exception
        self._next = 900

    def add_txn(self, tid, tranid, ns_type="VendBill", entity="81667", total=-57.54, **fields):
        txn = dict(id=str(tid), tranid=tranid, type=ns_type, entity=entity, foreigntotal=total,
                   location="64", custbody_reconciled="F")
        txn.update(fields)
        self.txns[str(tid)] = txn

    def add_line(self, lid, statement_id, invoice, **fields):
        self.lines[str(lid)] = dict(id=str(lid), custrecord_sl_statement_id=statement_id,
                                    custrecord_sl_invoice_number=invoice, **fields)

    @staticmethod
    def _store(value):
        if isinstance(value, bool):
            return "T" if value else "F"
        if isinstance(value, dict):
            return value.get("id")
        return value

    def suiteql(self, q):
        if "FROM transaction t LEFT JOIN" in q:
            ents = re.search(r"t.entity IN \(([^)]*)\)", q).group(1).split(",")
            tranids = re.findall(r"'([^']*)'", q.split("LOWER(t.tranid) IN")[1])
            return [dict(t) for t in self.txns.values() if t["entity"] in ents and t["tranid"].lower() in tranids]
        m = re.search(r"FROM transaction WHERE id = (\d+)", q)
        if m:
            return [dict(self.txns[m.group(1)])] if m.group(1) in self.txns else []
        m = re.search(r"FROM customrecord_statement_line WHERE id = (\d+)", q)
        if m:
            return [dict(self.lines[m.group(1)])] if m.group(1) in self.lines else []
        if "FROM customrecord_statement_line WHERE custrecord_sl_statement_id" in q:
            sid, inv = re.findall(r"'([^']*)'", q)
            return [{"id": l["id"]} for l in self.lines.values()
                    if l["custrecord_sl_statement_id"] == sid and l["custrecord_sl_invoice_number"].lower() == inv]
        raise AssertionError(q)

    def patch_record(self, record_type, record_id, body):
        self.calls.append(("PATCH", record_type, str(record_id), body))
        if str(record_id) in self.fail_patch:
            raise self.fail_patch[str(record_id)]
        target = self.lines if record_type == "customrecord_statement_line" else self.txns
        target[str(record_id)].update({k: self._store(v) for k, v in body.items()})

    def create_record(self, record_type, body):
        self._next += 1
        self.calls.append(("POST", record_type, str(self._next), body))
        self.lines[str(self._next)] = dict({k: self._store(v) for k, v in body.items()}, id=str(self._next))
        return str(self._next)

    def delete_record(self, record_type, record_id, statement_id=None):
        self.calls.append(("DELETE", record_type, str(record_id)))
        self.lines.pop(str(record_id))


def _on():
    return mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true", "NETSUITE_WRITEBACK_PDF_LINK": "false"})


class TestWrite(unittest.TestCase):

    def test_off_writes_nothing(self):
        ns = FakeSandbox()
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "false"}):
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ns=ns)
        self.assertEqual(out["status"], "write-back off")
        self.assertEqual(ns.calls, [])

    def test_not_found_line_updates_the_statement_line_and_reconciles_the_bill(self):
        ns = FakeSandbox()
        ns.add_txn(555, "23")
        ns.add_line(77, "STMT-1", "INV123", custrecord_sl_status="No match found",
                    custrecord_sl_exception_type="No match found", custrecord_sl_reconciled="F")
        with _on():
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ["81667"], ns=ns, today="2026-10-19")
        self.assertEqual((out["status"], out["statement_line_id"]), ("written", "77"))
        bill = ns.txns["555"]
        self.assertEqual((bill["custbody_reconciled"], bill[MATCHED_BILL_FIELD], bill["custbody_statement_reference"]),
                         ("T", "INV123", "STMT-1"))
        line = ns.lines["77"]
        self.assertEqual((line["custrecord_sl_status"], line["custrecord_sl_matched_bill"], line["custrecord_sl_reconciled"]),
                         ("Matched", "555", "T"))
        self.assertFalse(any(c[0] == "POST" for c in ns.calls))

    def test_mismatch_with_a_different_bill_creates_the_line_and_clears_the_old_flag(self):
        ns = FakeSandbox()
        ns.add_txn(555, "23")                                  # picked
        ns.add_txn(444, "INV123", total=-50.0, custbody_reconciliation_exception="2",
                   custbody_statement_reference="STMT-1")      # flagged "Amount differs" earlier
        with _on():
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ["81667"], shop="Lamon", ns=ns,
                                        today="2026-10-19")
        self.assertEqual(out["status"], "written")
        created = ns.lines[out["statement_line_id"]]
        self.assertEqual((created["custrecord_sl_matched_bill"], created["custrecord_sl_invoice_number"],
                          created["custrecord_sl_statement_amount"], created["custrecord_sl_shop"]),
                         ("555", "INV123", 50.51, "Lamon"))
        old = ns.txns["444"]
        self.assertIsNone(old["custbody_reconciliation_exception"])
        self.assertEqual(old["custbody_reconciled"], "F")      # cleared, not reconciled

    def test_not_in_sandbox_and_reconciled_elsewhere_write_nothing(self):
        ns = FakeSandbox()
        with _on():
            self.assertEqual(mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ns=ns)["status"], "not in sandbox")
        ns.add_txn(555, "23", custbody_reconciled="T", custbody_statement_reference="STMT-OTHER")
        with _on():
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ns=ns)
        self.assertEqual(out["status"], "reconciled by another statement")
        self.assertEqual([c for c in ns.calls if c[0] != "GET"], [])

    def test_amount_must_tie_the_picked_record(self):
        ns = FakeSandbox()
        ns.add_txn(555, "23", total=-99.0)
        with _on():
            self.assertEqual(mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ns=ns)["status"], "not in sandbox")

    def test_a_locked_period_is_reported(self):
        ns = FakeSandbox()
        ns.add_txn(555, "23")
        err = Exception("HTTP 400")
        err.body = "You cannot make changes to this period without the Allow Non-G/L Changes permission."
        ns.fail_patch["555"] = err
        with _on():
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ns=ns)
        self.assertEqual(out["status"], "period locked")
        self.assertIn("Non-G/L", out["detail"])


class TestUndo(unittest.TestCase):

    def test_round_trip_restores_everything_and_deletes_a_created_line(self):
        ns = FakeSandbox()
        ns.add_txn(555, "23")
        ns.add_txn(444, "INV123", total=-50.0, custbody_reconciliation_exception="2",
                   custbody_statement_reference="STMT-1")
        before_state = json.loads(json.dumps({"txns": ns.txns, "lines": ns.lines}))
        with _on():
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ["81667"], ns=ns, today="2026-10-19")
            undone = mm.undo_manual_match_writes(out["before"], ns=ns)
        self.assertEqual(undone["status"], "undone")
        self.assertEqual(ns.lines, before_state["lines"])                       # created line deleted
        self.assertEqual(ns.txns["444"]["custbody_reconciliation_exception"], "2")  # flag back
        bill = ns.txns["555"]
        self.assertEqual((bill["custbody_reconciled"], bill.get(MATCHED_BILL_FIELD)), ("F", None))

    def test_a_field_someone_changed_since_is_left_alone(self):
        ns = FakeSandbox()
        ns.add_txn(555, "23")
        with _on():
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ns=ns, today="2026-10-19")
            ns.txns["555"][MATCHED_BILL_FIELD] = "INV999"      # edited by hand in NetSuite
            undone = mm.undo_manual_match_writes(out["before"], ns=ns)
        self.assertIn(f"left alone, changed since: {MATCHED_BILL_FIELD}", undone["detail"])
        self.assertEqual(ns.txns["555"][MATCHED_BILL_FIELD], "INV999")
        self.assertEqual(ns.txns["555"]["custbody_reconciled"], "F")

    def test_nothing_recorded_or_write_back_off(self):
        self.assertEqual(mm.undo_manual_match_writes(None)["status"], "nothing to undo")
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "false"}):
            self.assertEqual(mm.undo_manual_match_writes('{"writes": []}')["status"], "write-back off")


class TestFields(unittest.TestCase):

    def test_preflight_checks_the_matched_bill_field(self):
        self.assertEqual(MATCHED_BILL_FIELD, "custbody_matched_bill")
        self.assertIn(MATCHED_BILL_FIELD, BODY_FIELDS)


if __name__ == "__main__":
    unittest.main()
