"""
tests/test_matched_bill_field.py

The Statement Line's Matched Bill (custrecord_sl_matched_bill) is being
switched in NetSuite from one bill link to a Multiple Select (2026-11-06).
src/netsuite/matched_bill_field.py lets every write, read-back, undo and
re-create work with both shapes, so the code can ship BEFORE the switch:

    single:   {"id": "555"}                   SuiteQL reads "555"
    multiple: {"items": [{"id": "555"}, ...]} SuiteQL reads "555, 556"
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.netsuite import clear_exception as ce
from src.netsuite import guard
from src.netsuite import manual_match as mm
from src.netsuite import matched_bill_field as mbf
from test_manual_match_netsuite import RECORD, FakeSandbox, _on

FIELD = mbf.FIELD
SINGLE_SCHEMA = {"properties": {FIELD: {"type": "object", "properties": {
    "id": {"type": "string"}, "refName": {"type": "string"}}}}}
MULTIPLE_SCHEMA = {"properties": {FIELD: {"type": "object", "properties": {
    "items": {"type": "array", "items": {"type": "object"}}}}}}


class FakeNetSuite(FakeSandbox):
    """FakeSandbox whose Matched Bill can be either type -- and switched,
    like the admin will -- and which, like NetSuite, rejects the wrong shape."""

    def __init__(self, mode=mbf.SINGLE):
        super().__init__()
        self.mode = mode
        self.schema_reads = 0

    def get_record_schema(self, record_type):
        self.schema_reads += 1
        return MULTIPLE_SCHEMA if self.mode == mbf.MULTIPLE else SINGLE_SCHEMA

    def _check(self, record_type, body):
        if record_type == mbf.STATEMENT_LINE_RECORD and body.get(FIELD) is not None:
            is_multi = isinstance(body[FIELD], dict) and "items" in body[FIELD]
            if is_multi != (self.mode == mbf.MULTIPLE):
                raise Exception(f"HTTP 400: wrong shape for {FIELD} ({self.mode})")

    @staticmethod
    def _store(value):
        if isinstance(value, dict) and "items" in value:
            return ", ".join(str(i["id"]) for i in value["items"]) or None
        return FakeSandbox._store(value)

    def patch_record(self, record_type, record_id, body):
        guard.check_patch(record_type, record_id, body)
        self._check(record_type, body)
        # Like the real sandbox (checked 2026-11-06): an empty {"items": []}
        # changes nothing on a Multiple Select -- only null clears it.
        body = {k: v for k, v in body.items() if not (isinstance(v, dict) and v.get("items") == [])}
        if body:
            super().patch_record(record_type, record_id, body)

    def create_record(self, record_type, body):
        guard.check_create(record_type, body)
        self._check(record_type, body)
        return super().create_record(record_type, body)


class Base(unittest.TestCase):
    def setUp(self):
        mbf.reset_cache()
        self.addCleanup(mbf.reset_cache)
        patcher = mock.patch.dict(os.environ, {})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(mbf.ENV_MODE, None)


class TestValues(Base):
    def test_ids_from_every_shape(self):
        self.assertEqual(mbf.ids_from("555"), ["555"])
        self.assertEqual(mbf.ids_from("555, 556"), ["555", "556"])
        self.assertEqual(mbf.ids_from(555), ["555"])
        self.assertEqual(mbf.ids_from({"id": "555"}), ["555"])
        self.assertEqual(mbf.ids_from({"items": [{"id": "555"}, {"id": 556}]}), ["555", "556"])
        self.assertEqual(mbf.ids_from(None), [])
        self.assertEqual(mbf.ids_from(""), [])
        self.assertEqual(mbf.ids_from({"items": []}), [])

    def test_same_bills_ignores_shape_and_order(self):
        self.assertTrue(mbf.same_bills("556, 555", {"items": [{"id": "555"}, {"id": "556"}]}))
        self.assertTrue(mbf.same_bills("555", {"id": "555"}))
        self.assertFalse(mbf.same_bills("555", {"items": [{"id": "555"}, {"id": "556"}]}))

    def test_value_for(self):
        self.assertEqual(mbf.value_for(mbf.SINGLE, ["555"]), {"id": "555"})
        self.assertIsNone(mbf.value_for(mbf.SINGLE, []))
        self.assertEqual(mbf.value_for(mbf.MULTIPLE, "555, 556"), {"items": [{"id": "555"}, {"id": "556"}]})
        self.assertIsNone(mbf.value_for(mbf.MULTIPLE, None))   # an empty list would not clear it
        self.assertIsNone(mbf.value_for(mbf.MULTIPLE, []))
        self.assertEqual(mbf.value_for(mbf.MULTIPLE, ["555", "555"]), {"items": [{"id": "555"}]})


class TestMode(Base):
    def test_read_from_the_metadata(self):
        self.assertEqual(mbf.field_mode(FakeNetSuite(mbf.SINGLE)), mbf.SINGLE)
        mbf.reset_cache()
        self.assertEqual(mbf.field_mode(FakeNetSuite(mbf.MULTIPLE)), mbf.MULTIPLE)

    def test_cached_then_re_read_so_the_switch_is_picked_up_without_a_restart(self):
        ns, clock = FakeNetSuite(mbf.SINGLE), mock.Mock(return_value=1000.0)
        self.assertEqual(mbf.field_mode(ns, now=clock), mbf.SINGLE)
        ns.mode = mbf.MULTIPLE                                  # the admin switches it
        self.assertEqual(mbf.field_mode(ns, now=clock), mbf.SINGLE)     # cached
        self.assertEqual(ns.schema_reads, 1)
        clock.return_value = 1000.0 + mbf.MODE_CACHE_SECONDS + 1
        self.assertEqual(mbf.field_mode(ns, now=clock), mbf.MULTIPLE)

    def test_the_setting_wins(self):
        os.environ[mbf.ENV_MODE] = "multiple"
        ns = FakeNetSuite(mbf.SINGLE)
        self.assertEqual(mbf.field_mode(ns), mbf.MULTIPLE)
        self.assertEqual(ns.schema_reads, 0)

    def test_unreadable_metadata_means_single_and_is_not_cached(self):
        ns = mock.Mock()
        ns.get_record_schema.side_effect = Exception("HTTP 403")
        with self.assertLogs(mbf.logger, "WARNING"):
            self.assertEqual(mbf.field_mode(ns), mbf.SINGLE)
        ns.get_record_schema.side_effect = None
        ns.get_record_schema.return_value = MULTIPLE_SCHEMA
        self.assertEqual(mbf.field_mode(ns), mbf.MULTIPLE)

    def test_field_missing_from_the_metadata_means_single(self):
        ns = mock.Mock()
        ns.get_record_schema.return_value = {"properties": {}}
        with self.assertLogs(mbf.logger, "WARNING"):
            self.assertEqual(mbf.field_mode(ns), mbf.SINGLE)


class TestGuard(Base):
    def _patch(self, value):
        guard.check_patch(mbf.STATEMENT_LINE_RECORD, "77", {FIELD: value})

    def test_both_shapes_are_allowed(self):
        self._patch({"id": "555"})
        self._patch({"items": [{"id": "555"}, {"id": "556"}]})
        self._patch({"items": []})
        self._patch(None)

    def test_bad_shapes_are_refused(self):
        for bad in ({"items": [{"id": "abc"}]}, {"items": "555"}, {"items": [], "id": "1"},
                    {"items": [{"id": "1", "x": 1}]}, {"items": [{"id": str(i)} for i in range(51)]}, "555"):
            with self.assertRaises(guard.WriteBlocked, msg=bad):
                self._patch(bad)


class TestAcceptAsMatch(Base):
    def _accept(self, ns, **kw):
        with _on():
            return mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ["81667"], ns=ns,
                                         today="2026-11-06", **kw)

    def test_single_works_as_before(self):
        ns = FakeNetSuite(mbf.SINGLE)
        ns.add_txn(555, "23")
        ns.add_line(77, "STMT-1", "INV123", custrecord_sl_status="No match found")
        out = self._accept(ns)
        self.assertEqual(out["status"], "written", out["detail"])
        sent = [c[3] for c in ns.calls if c[1] == mbf.STATEMENT_LINE_RECORD][0]
        self.assertEqual(sent[FIELD], {"id": "555"})
        self.assertEqual(ns.lines["77"][FIELD], "555")

    def test_multiple_select_existing_line(self):
        ns = FakeNetSuite(mbf.MULTIPLE)
        ns.add_txn(555, "23")
        ns.add_line(77, "STMT-1", "INV123", custrecord_sl_status="No match found")
        out = self._accept(ns)
        self.assertEqual(out["status"], "written", out["detail"])
        sent = [c[3] for c in ns.calls if c[1] == mbf.STATEMENT_LINE_RECORD][0]
        self.assertEqual(sent[FIELD], {"items": [{"id": "555"}]})
        self.assertEqual(ns.lines["77"][FIELD], "555")

    def test_multiple_select_created_line(self):
        ns = FakeNetSuite(mbf.MULTIPLE)
        ns.add_txn(555, "23")
        out = self._accept(ns)
        self.assertEqual(out["status"], "written", out["detail"])
        self.assertEqual(ns.lines[out["statement_line_id"]][FIELD], "555")

    def test_before_this_code_the_switch_would_have_broken_it(self):
        # What happens today if the admin switches first: the line write is rejected.
        ns = FakeNetSuite(mbf.MULTIPLE)
        ns.add_txn(555, "23")
        ns.add_line(77, "STMT-1", "INV123", custrecord_sl_status="No match found")
        with mock.patch.object(mbf, "field_mode", return_value=mbf.SINGLE):   # the old behaviour
            out = self._accept(ns)
        self.assertEqual(out["status"], "partly written")


class TestUndoAcrossTheSwitch(Base):
    """A match written while the field was single, undone after the admin switched it."""

    def _accept_then_switch_then_undo(self, line_before):
        ns = FakeNetSuite(mbf.SINGLE)
        ns.add_txn(555, "23")
        ns.add_line(77, "STMT-1", "INV123", **line_before)
        with _on():
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ["81667"], ns=ns, today="2026-11-06")
            self.assertEqual(out["status"], "written", out["detail"])
            ns.mode = mbf.MULTIPLE
            mbf.reset_cache()
            undone = mm.undo_manual_match_writes(out["before"], ns=ns)
        return ns, undone

    def test_empty_before_is_cleared_in_the_new_shape(self):
        ns, undone = self._accept_then_switch_then_undo(
            {"custrecord_sl_status": "No match found", "custrecord_sl_exception_type": "No match found"})
        self.assertEqual(undone["status"], "undone", undone["detail"])
        self.assertNotIn("left alone", undone["detail"])
        self.assertIsNone(ns.lines["77"][FIELD])
        self.assertEqual(ns.lines["77"]["custrecord_sl_status"], "No match found")
        last_line_patch = [c[3] for c in ns.calls if c[1] == mbf.STATEMENT_LINE_RECORD][-1]
        self.assertIsNone(last_line_patch[FIELD])   # null clears; {"items": []} would not

    def test_a_previous_bill_goes_back_in_the_new_shape(self):
        ns, undone = self._accept_then_switch_then_undo({"custrecord_sl_status": "Amount differs", FIELD: "333"})
        self.assertEqual(undone["status"], "undone", undone["detail"])
        self.assertEqual(ns.lines["77"][FIELD], "333")

    def test_someone_else_adding_a_bill_since_is_left_alone(self):
        ns = FakeNetSuite(mbf.MULTIPLE)
        ns.add_txn(555, "23")
        ns.add_line(77, "STMT-1", "INV123", custrecord_sl_status="No match found")
        with _on():
            out = mm.write_manual_match("STMT-1", "INV123", 50.51, RECORD, ["81667"], ns=ns, today="2026-11-06")
            ns.lines["77"][FIELD] = "555, 999"                 # edited by hand in NetSuite
            undone = mm.undo_manual_match_writes(out["before"], ns=ns)
        self.assertIn(f"changed since: {FIELD}", undone["detail"])
        self.assertEqual(ns.lines["77"][FIELD], "555, 999")


class TestClearExceptionRecreate(Base):
    COPY = {"name": "STMT-1 INV123", "custrecord_sl_statement_id": "STMT-1", "custrecord_sl_invoice_number": "INV123",
            "custrecord_sl_status": "No match found", "custrecord_sl_vendor": "81667"}

    def test_recreate_body_in_each_shape(self):
        copy = dict(self.COPY, **{FIELD: "555, 556"})
        self.assertEqual(ce.recreate_body(copy, mbf.MULTIPLE)[FIELD], {"items": [{"id": "555"}, {"id": "556"}]})
        self.assertEqual(ce.recreate_body(dict(self.COPY, **{FIELD: "555"}))[FIELD], {"id": "555"})
        self.assertNotIn(FIELD, ce.recreate_body(self.COPY, mbf.MULTIPLE))
        self.assertEqual(ce.recreate_body(self.COPY)["custrecord_sl_vendor"], {"id": "81667"})

    def test_undo_re_creates_a_line_with_a_bill_after_the_switch(self):
        ns = FakeNetSuite(mbf.MULTIPLE)
        before = json.dumps({"writes": [{"kind": ce.DELETED_KIND, "record_type": mbf.STATEMENT_LINE_RECORD,
                                         "record_id": "77", "sent": {}, "deleted": True, "ok": True,
                                         "before": dict(self.COPY, **{FIELD: "555"})}]})
        with _on():
            out = ce.undo_clear_writes(before, ns=ns)
        self.assertEqual(out["status"], "undone", out["detail"])
        created = [c[3] for c in ns.calls if c[0] == "POST"][0]
        self.assertEqual(created[FIELD], {"items": [{"id": "555"}]})

    def test_undo_without_a_bill_does_not_read_the_metadata(self):
        ns = FakeNetSuite(mbf.MULTIPLE)
        before = json.dumps({"writes": [{"kind": ce.DELETED_KIND, "record_type": mbf.STATEMENT_LINE_RECORD,
                                         "record_id": "77", "sent": {}, "deleted": True, "ok": True,
                                         "before": dict(self.COPY)}]})
        with _on():
            self.assertEqual(ce.undo_clear_writes(before, ns=ns)["status"], "undone")
        self.assertEqual(ns.schema_reads, 0)


if __name__ == "__main__":
    unittest.main()
