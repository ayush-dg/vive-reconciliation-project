""""Appears to be Paid" (2026-11-05): a statement line that matches a vendor
BILL by its own invoice number and amount is an exception when NetSuite already
shows that bill Paid In Full -- at any shop/location (same vendor is enough).
Not written back to NetSuite. Behind
APPEARS_PAID_ENABLED. run_fabric_matching() runs here as a dry run against a
fake Fabric (warehouse + lakehouse cursors)."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import recon_table
from src.matching import fabric_matching as fm
from src.netsuite import writeback as wb
from web import statement_processing as sp

LINE_COLS = ["statement_line_id", "line_number", "invoice_number", "document_number", "invoice_number_ref",
             "transaction_code", "line_type", "charge_amount", "payment_amount", "po_number", "ro_number",
             "line_date"]


def _line(n, inv, amount, line_type="CHARGE"):
    charge, payment = (amount, None) if line_type == "CHARGE" else (None, amount)
    return (f"L{n}", n, inv, inv, None, None, line_type, charge, payment, None, None, "2026-10-14")


class _Cursor:
    """Answers exactly the reads run_fabric_matching() makes."""

    def __init__(self, fabric):
        self.f, self.description, self._rows = fabric, [], []

    def execute(self, sql, params=None):
        if "FROM silver.statement WHERE" in sql:
            cols = ["statement_id", "vendor_id", "vendor_name_raw", "shop_name_raw", "source_bronze_table"]
            row = ["STMT-P", "HOSELTON", "Hoselton", "Vive Collision Of Vestal", "bronze.raw_statement"]
            self.description, self._rows = [(c,) for c in cols], [tuple(row)]
        elif "FROM silver.statement_line" in sql:
            self.description, self._rows = [(c,) for c in LINE_COLS], list(self.f["lines"])
        elif "FROM bronze.netsuite_vendorbill" in sql:
            self._rows = list(self.f["bills"])
        elif "FROM bronze.netsuite_vendorcredit" in sql:
            self._rows = []
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, fabric):
        self.f = fabric

    def cursor(self):
        return _Cursor(self.f)

    def close(self):
        pass


def _bill(tranid, total, bill_id, location="12", status="B"):
    return (tranid, total, bill_id, f"BILL{bill_id}", "4242", location, status)


def _run(lines, bills, enabled=True):
    fabric = {"lines": lines, "bills": bills}
    env = {"APPEARS_PAID_ENABLED": "true" if enabled else "", "NETSUITE_SOURCE": "fabric"}
    with mock.patch.dict(os.environ, env), \
            mock.patch.object(fm, "_fabric_configured", return_value=True), \
            mock.patch.object(fm, "get_warehouse_connection", lambda: _Conn(fabric)), \
            mock.patch.object(fm, "get_lakehouse_connection", lambda: _Conn(fabric)), \
            mock.patch.object(fm, "resolve_entity_ids", return_value=["4242"]), \
            mock.patch.object(fm, "get_shop_owner", return_value=None), \
            mock.patch.object(fm, "_load_line_selection_rules", return_value={}), \
            mock.patch.object(fm, "_alternate_tranids", return_value=[]):
        result = fm.run_fabric_matching("STMT-P", dry_run=True)
    assert "error" not in result, result
    return result


def _by_invoice(result):
    return {r["invoice_number"]: r for r in result["recon_rows"]}


def test_a_paid_bill_is_flagged():
    result = _run([_line(1, "452527G", 298.47), _line(2, "452600G", 100.00)],
                  [_bill("452527G", 298.47, "4646903", status="B"), _bill("452600G", 100.00, "4646904", status="A")])
    rows = _by_invoice(result)
    assert rows["452527G"]["status"] == "Appears to be paid"
    assert rows["452527G"]["exception_reason"] == fm.APPEARS_PAID
    assert rows["452527G"]["netsuite_internal_id"] == "4646903"   # the paid bill is shown
    assert rows["452600G"]["status"] == recon_table.STATUS_MATCHED  # open bill: matched as before
    assert (result["matched"], result["exceptions"]) == (1, 1)
    exc = result["would_write"]["silver.recon_exceptions"]
    assert any("Appears to be Paid" in map(str, row) for row in exc)


def test_switched_off_a_paid_bill_still_matches():
    result = _run([_line(1, "452527G", 298.47)], [_bill("452527G", 298.47, "1", status="B")], enabled=False)
    assert _by_invoice(result)["452527G"]["status"] == recon_table.STATUS_MATCHED


@pytest.mark.parametrize("location", ["12", "13", None])
def test_shop_does_not_matter_a_paid_bill_anywhere_is_flagged(location):
    # Any shop's location, or none at all: the same vendor is enough (2026-11-05).
    result = _run([_line(1, "452527G", 298.47)], [_bill("452527G", 298.47, "1", location=location, status="B")])
    assert _by_invoice(result)["452527G"]["status"] == "Appears to be paid"


def test_a_paid_bill_with_a_different_amount_stays_an_amount_mismatch():
    result = _run([_line(1, "452527G", 300.00)], [_bill("452527G", 298.47, "1", status="B")])
    assert _by_invoice(result)["452527G"]["exception_reason"] == "Amount Mismatch"


def test_a_paid_bill_found_only_by_an_alternate_number_is_not_flagged():
    line = _line(1, "0000-452527G", 298.47)
    with mock.patch.object(fm, "_alternate_tranids", return_value=["452527G"]):
        fabric = {"lines": [line], "bills": [_bill("452527G", 298.47, "1", status="B")]}
        with mock.patch.dict(os.environ, {"APPEARS_PAID_ENABLED": "true", "NETSUITE_SOURCE": "fabric"}), \
                mock.patch.object(fm, "_fabric_configured", return_value=True), \
                mock.patch.object(fm, "get_warehouse_connection", lambda: _Conn(fabric)), \
                mock.patch.object(fm, "get_lakehouse_connection", lambda: _Conn(fabric)), \
                mock.patch.object(fm, "resolve_entity_ids", return_value=["4242"]), \
                mock.patch.object(fm, "get_shop_owner", return_value=None), \
                mock.patch.object(fm, "_load_line_selection_rules", return_value={}):
            result = fm.run_fabric_matching("STMT-P", dry_run=True)
    assert _by_invoice(result)["0000-452527G"]["status"] == recon_table.STATUS_MATCHED


def test_an_older_six_column_candidate_row_still_works():
    cur = mock.Mock()
    cur.fetchall.return_value = [("452527G", 298.47, "1", "BILL1", "4242", "12")]
    with mock.patch.dict(os.environ, {"NETSUITE_SOURCE": "fabric"}):
        candidates = fm._fetch_netsuite_candidates(cur, ["4242"], "netsuite_vendorbill")
    assert candidates.record_for("452527g", 298.47)["status"] is None


@pytest.mark.parametrize("status,paid", [("B", True), ("VendBill:B", True), ("Paid In Full", True),
                                         ("A", False), ("VendBill:A", False), (None, False), ("", False)])
def test_paid_in_full_codes(status, paid):
    assert fm._is_paid_in_full(status) is paid


# --- not written back ------------------------------------------------------

def test_write_back_skips_appears_to_be_paid():
    plans = wb.plan_exception_row({"invoice_number": "452527G", "statement_amount": 298.47,
                                   "exception_reason": fm.APPEARS_PAID}, [], mock.Mock(), set())
    assert len(plans) == 1
    assert plans[0].action == wb.SKIP_REVIEW and plans[0].category == wb.CAT_NO_BILL_TO_WRITE
    assert "not written back" in plans[0].note


# --- statement page wording -----------------------------------------------

def test_statement_summary_and_reconciliation_tab():
    assert sp.reason_summary({fm.APPEARS_PAID: 2}) == "2 invoices appear to be paid already."
    assert sp.reason_summary({"Amount Mismatch": 1, fm.APPEARS_PAID: 1}) == \
        "Amount mismatch on 1 invoice, 1 invoice appears to be paid already."
    view = sp.recon_view([{"status": "Appears to be paid", "exception_id": "E1", "exception_reason": fm.APPEARS_PAID,
                           "line_number": 1, "invoice_number": "452527G", "line_amount": 298.47}])
    assert view["rows"][0]["label"] == "Appears to be paid"
    assert view["open_reasons"] == {fm.APPEARS_PAID: 1}
    assert view["tiles"]["open"] == 1


def test_recon_status_for_the_new_reason():
    assert recon_table.status_for_reason(fm.APPEARS_PAID) == "Appears to be paid"


# --- review page ------------------------------------------------------------

def test_review_page_shows_the_paid_bill_and_its_payment():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.middleware.sessions import SessionMiddleware
    from web.deps import require_login
    from web.routers import exceptions

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="x")
    app.include_router(exceptions.router)
    app.dependency_overrides[require_login] = lambda: "ap@vive.com"
    statement = {"statement_id": "STMT-P", "vendor_name": "Hoselton"}
    exc = {"exception_id": "EXC-9", "statement_id": "STMT-P", "invoice_number": "452527G", "vendor_id": "HOSELTON",
           "exception_reason": fm.APPEARS_PAID, "statement_amount": 298.47, "erp_amount": 298.47,
           "match_confidence": None, "date_raised": None, "days_open": None, "invoice_date": None}
    record = {"id": "4646903", "tranid": "452527G", "status": "B", "total": 298.47,
              "_source_table": "netsuite_vendorbill"}
    payments = [{"tranid": "CHK 10442", "transactionnumber": "PYMT8812", "trandate": "10/30/2026", "amount": 298.47}]
    with mock.patch.object(exceptions.queries, "get_statement_by_id", return_value=statement), \
            mock.patch.object(exceptions.queries, "get_open_exceptions", return_value=[exc]) as open_exc, \
            mock.patch.object(exceptions.queries, "get_exception_counts", return_value=(1, 0)), \
            mock.patch.object(exceptions.queries, "get_statement_shop", return_value=None), \
            mock.patch.object(exceptions.queries, "get_manual_matches", return_value=[]), \
            mock.patch.object(exceptions.queries, "get_cleared_exceptions", return_value=[]), \
            mock.patch.object(exceptions, "fetch_netsuite_record_for_invoice", return_value=record), \
            mock.patch.object(exceptions, "fetch_bill_payments", return_value=payments) as pays, \
            mock.patch.object(exceptions, "_writeback_status", return_value=None), \
            mock.patch.object(exceptions, "_statement_pdf_url", return_value=None), \
            mock.patch.object(exceptions, "sidebar_context", return_value={}):
        resp = TestClient(app).get("/exceptions/Hoselton?statement_id=STMT-P&filter=paid")
    assert resp.status_code == 200
    html = resp.text
    open_exc.assert_called_once_with("STMT-P", "paid", None)
    pays.assert_called_once_with("4646903")
    assert "Paid in NetSuite" in html and "Paid In Full" in html
    assert "CHK 10442" in html and "PYMT8812" in html
    assert "Appears paid</a>" in html
    assert "filter-tab active" in html.split("Appears paid</a>")[0].rsplit("<a", 1)[1]


def test_paid_filter_selects_only_appears_to_be_paid():
    from web import queries
    assert queries._REASON_FILTER_SQL["paid"] == [fm.APPEARS_PAID]


@pytest.mark.parametrize("table,selects_status", [("netsuite_vendorbill", True), ("netsuite_vendorcredit", False)])
def test_fabric_query_reads_status_only_from_bills(table, selects_status):
    # Fabric's bronze.netsuite_vendorcredit has no status column: selecting it
    # failed every Fabric read (prod, 2026-11-05).
    cur = mock.Mock()
    cur.fetchall.return_value = [("CM1", 10.0, "5", "VC5", "4242", "12", None)]
    with mock.patch.dict(os.environ, {"NETSUITE_SOURCE": "fabric"}):
        fm._fetch_netsuite_candidates(cur, ["4242"], table)
    sql = cur.execute.call_args[0][0]
    assert (", status FROM" in sql) is selects_status
    assert selects_status or "NULL AS status" in sql
