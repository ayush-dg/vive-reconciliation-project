"""
tests/test_netsuite_source_switch.py

NETSUITE_SOURCE=fabric|connect (src/netsuite/connect_source.py): matching's
NetSuite reads -- bills/credits per vendor, the Keystone credit list and the
vendor lookups -- come from the Fabric copy by default, from live Connect when
switched on, and fall back to Fabric when a Connect read fails. Offline: no
Fabric, ODBC or NetSuite call is made.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching import fabric_matching as fm
from src.matching import netsuite_vendor_resolver as resolver
from src.netsuite import connect_source

ROWS = [("INV-1", 100.0, "11", "VENDBILL1", "7", "3"), ("inv-1", 50.0, "12", "VENDBILL2", "7", None)]


class _Cursor:
    def __init__(self, rows):
        self.rows, self.executed = rows, []

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchall(self):
        return self.rows


def _env(source):
    return mock.patch.dict(os.environ, {"NETSUITE_SOURCE": source} if source is not None else {}, clear=False)


class SourceSettingTests(unittest.TestCase):
    def test_default_is_fabric(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NETSUITE_SOURCE", None)
            self.assertEqual(connect_source.netsuite_source(), "fabric")

    def test_connect_any_case(self):
        with _env(" Connect "):
            self.assertEqual(connect_source.netsuite_source(), "connect")

    def test_unknown_value_means_fabric(self):
        with _env("live"):
            self.assertEqual(connect_source.netsuite_source(), "fabric")


class CandidateTests(unittest.TestCase):
    def setUp(self):
        connect_source.reset_used()

    def test_fabric_reads_the_copy(self):
        cur = _Cursor(ROWS)
        with _env("fabric"), mock.patch.object(connect_source, "candidate_rows") as live:
            got = fm._fetch_netsuite_candidates(cur, ["7"], "netsuite_vendorbill")
        live.assert_not_called()
        self.assertIn("bronze.netsuite_vendorbill", cur.executed[0])
        self.assertEqual(got["inv-1"], [100.0, 50.0])
        self.assertEqual(connect_source.used_summary(), "fabric")

    def test_connect_gives_the_same_candidates_without_touching_fabric(self):
        cur = _Cursor([])
        with _env("connect"), mock.patch.object(connect_source, "candidate_rows", return_value=ROWS) as live:
            got = fm._fetch_netsuite_candidates(cur, ["7"], "netsuite_vendorbill")
        live.assert_called_once_with(["7"], "netsuite_vendorbill")
        self.assertEqual(cur.executed, [])
        self.assertEqual(got["inv-1"], [100.0, 50.0])
        self.assertEqual(got.record_for("INV-1", 100.0)["id"], "11")
        self.assertEqual(connect_source.used_summary(), "connect")

    def test_connect_failure_falls_back_to_fabric(self):
        cur = _Cursor(ROWS)
        with _env("connect"), mock.patch.object(connect_source, "candidate_rows", side_effect=RuntimeError("down")):
            got = fm._fetch_netsuite_candidates(cur, ["7"], "netsuite_vendorcredit")
        self.assertIn("bronze.netsuite_vendorcredit", cur.executed[0])
        self.assertEqual(got["inv-1"], [100.0, 50.0])
        self.assertEqual(connect_source.used_summary(), "fabric (connect failed)")

    def test_keystone_credit_list_follows_the_switch(self):
        with _env("connect"), mock.patch.object(connect_source, "credit_rows", return_value=[("CM-Z1", 9.5)]):
            got = fm._fetch_netsuite_credit_candidates(_Cursor([]), ["7"])
        self.assertEqual(got, [("cm-z1", 9.5)])

    def test_no_entities_reads_nothing(self):
        with _env("connect"), mock.patch.object(connect_source, "candidate_rows") as live:
            self.assertEqual(dict(fm._fetch_netsuite_candidates(_Cursor([]), [], "netsuite_vendorbill")), {})
        live.assert_not_called()


class ResolverTests(unittest.TestCase):
    def setUp(self):
        connect_source.reset_used()

    def test_vendor_rows_come_from_connect_when_switched_on(self):
        rows = [("5", "Gates GMC Nissan", "Gates GMC Nissan", None)]
        with _env("connect"), mock.patch.object(connect_source, "active_vendor_rows", return_value=rows), \
                mock.patch.object(resolver, "get_lakehouse_connection") as fabric:
            self.assertEqual(resolver._dynamic_lookup("Gates GMC Nissan"), ["5"])
        fabric.assert_not_called()

    def test_vendor_rows_fall_back_to_fabric(self):
        cur = _Cursor([("6", "Gates GMC Nissan", None, None)])
        conn = mock.Mock(cursor=mock.Mock(return_value=cur))
        with _env("connect"), mock.patch.object(connect_source, "active_vendor_rows", side_effect=RuntimeError("x")), \
                mock.patch.object(resolver, "get_lakehouse_connection", return_value=conn):
            self.assertEqual(resolver._dynamic_lookup("Gates GMC Nissan"), ["6"])
        self.assertEqual(connect_source.used_summary(), "fabric (connect failed)")

    def test_first_word_search_uses_connect(self):
        with _env("connect"), mock.patch.object(connect_source, "active_vendor_ids_like", return_value=["8", "9"]) as live:
            self.assertEqual(resolver._first_word_like_lookup("Berlin City Toyota"), ["8", "9"])
        live.assert_called_once_with("%berlin%")


class ConnectQueryTests(unittest.TestCase):
    """The SQL connect_source sends, and the row shape it returns."""

    def _fake_client(self, rows):
        client = mock.Mock()
        client.query.return_value = rows
        return client

    def test_candidate_rows_shape_and_filters(self):
        client = self._fake_client([{"tranid": "A1", "total": 12.5, "id": 4, "transactionnumber": "VB1",
                                     "entity": 7, "location": None}])
        with mock.patch.object(connect_source, "_client", return_value=client):
            rows = connect_source.candidate_rows(["7", "8; DROP TABLE x", 9], "netsuite_vendorcredit")
        sql = client.query.call_args[0][0]
        self.assertIn("t.type = 'VendCred'", sql)
        self.assertIn("t.voided = 'F'", sql)
        self.assertIn("ABS(t.foreigntotal)", sql)
        self.assertIn("t.entity IN (7,9)", sql)
        self.assertNotIn("DROP", sql)
        self.assertEqual(rows, [("A1", 12.5, "4", "VB1", "7", None)])

    def test_no_valid_entities_sends_no_query(self):
        client = self._fake_client([])
        with mock.patch.object(connect_source, "_client", return_value=client):
            self.assertEqual(connect_source.candidate_rows(["abc"], "netsuite_vendorbill"), [])
        client.query.assert_not_called()

    def test_vendor_search_pattern_is_quoted(self):
        client = self._fake_client([{"id": 3}])
        with mock.patch.object(connect_source, "_client", return_value=client):
            self.assertEqual(connect_source.active_vendor_ids_like("%o'neil%"), ["3"])
        self.assertIn("'%o''neil%'", client.query.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
