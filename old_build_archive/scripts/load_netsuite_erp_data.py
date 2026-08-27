"""
load_netsuite_erp_data.py

Loads real ERP data directly from the NetSuite REST/SuiteQL API
(vendorbill + vendorcredit) into bronze_internal_erp_raw /
silver_reconciliation_standard as record_source='INTERNAL_ERP' rows --
the live-API counterpart to scripts/load_voucher_data.py (which reads
pre-extracted xlsx voucher workbooks instead). Written under the same
synthetic, vendor-scoped statement_id (f"VOUCHER-{vendor_id}") so
src/matching/engine.py's existing vendor-scoped ERP lookup picks this up
with zero engine changes -- re-running this script for a vendor replaces
that vendor's own rows (whether they previously came from the xlsx loader
or a prior NetSuite run), same idempotent-per-vendor contract as
load_voucher_data.py.

invoice_number is sourced from tranid on both vendorbill and vendorcredit
-- verified against a real Fred Beans AR statement
(sample_data/Fred_Beans_MidNJ_053126.pdf): the numeric bill number
("9269292") and the CM-prefixed credit memo number ("CM9270525") NetSuite
calls tranid are exactly what appears in the vendor's own "INVOICE
NUMBER" column -- not custbody_kes_inv_number, an internal cross-reference
field never shown to AP. vendorcredit rows are written as their own line
with outstanding_amount negated, matching how load_voucher_data.py already
represents "Bill Credit #..." rows. True early-payment discounts (a
payment-application-line concept, e.g. the "Discount" column on a payment
voucher) are NOT available here -- they live on transactionline /
previoustransactionlinelink, which this integration role's SuiteQL access
does not expose (confirmed: both return "Record not found"). That's a
known, separate gap, not something this script papers over.

Bulk-write performance: src/lakehouse/connection.py's execute_sql()/
execute_query() open a brand-new Azure SQL connection on every single
call -- fine for the rest of the pipeline's per-statement call volume, but
prohibitive at this script's row count (thousands of bills/credits over a
multi-month window). This script instead opens ONE connection via the
same public get_connection() and reuses it for every insert, committing
once at the end. It avoids execute_sql()'s INSERT OR REPLACE path (which
would need _translate_for_azure()'s MERGE rewrite) by doing its own
delete-then-plain-INSERT per vendor, which needs no dialect translation on
either backend.

Usage:
    python scripts/load_netsuite_erp_data.py \\
        --entity-id 18706 --vendor-id FRED_BEANS_PARTS \\
        --vendor-name "FRED BEANS PARTS" \\
        --start 2026-04-01 --end 2026-06-30
"""

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

# Two separate .env files, both loaded by explicit path (see docs/Claude.md
# RULE-04 -- bare load_dotenv() is cwd/call-stack dependent): the project
# root .env for AZURE_SQL_* (the DB this script writes to), and
# netsuite_ingest/.env for the NetSuite integration credentials (kept
# alongside the ad hoc query tool that first exercised this API, see
# netsuite_ingest/netsuite-query-record 1.py).
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
load_dotenv(os.path.join(PROJECT_ROOT, "netsuite_ingest", ".env"))

import requests
from requests_oauthlib import OAuth1

from src.lakehouse.connection import get_connection
from src.normalization import normalize_invoice_number

PAGE_SIZE = 100


def _netsuite_auth():
    account_id = os.environ["ACCOUNT_ID"]
    return account_id, OAuth1(
        os.environ["CONSUMER_KEY"],
        client_secret=os.environ["CONSUMER_SECRET"],
        resource_owner_key=os.environ["TOKEN_ID"],
        resource_owner_secret=os.environ["TOKEN_SECRET"],
        signature_method="HMAC-SHA256",
        realm=account_id,
    )


def suiteql_paginate(select_cols: str, table: str, where: str, order_by: str = "id"):
    """Yields every row from a SuiteQL query, paginating via the `limit`/
    `offset` URL query-string params on the suiteql endpoint itself.

    NOT the same as an OFFSET/FETCH NEXT clause embedded in the SQL text --
    verified by direct testing that this endpoint (with the `Prefer:
    transient` header this account's integration role requires) silently
    ignores a SQL-level OFFSET and always returns the first page, which
    turns a naive "loop until fewer than PAGE_SIZE rows come back" into an
    infinite loop over the same first page. The URL query-string form
    returns accurate `hasMore`/`totalResults` and does paginate correctly."""
    account_id, auth = _netsuite_auth()
    base_url = f"https://{account_id}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"
    query = f"SELECT {select_cols} FROM {table} WHERE {where} ORDER BY {order_by}"

    offset = 0
    while True:
        resp = requests.post(
            f"{base_url}?limit={PAGE_SIZE}&offset={offset}", auth=auth,
            headers={"Accept": "application/json", "Content-Type": "application/json", "Prefer": "transient"},
            json={"q": query}, timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        for item in items:
            yield item
        offset += len(items)
        print(f"  [{table}] fetched {offset} rows so far...")
        if not data.get("hasMore") or not items:
            return


def parse_ns_date(value: str):
    """NetSuite returns dates as 'M/D/YYYY' strings. Returns YYYY-MM-DD, or
    None if value is missing/unparseable."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_bills(entity_id: int, start: str, end: str):
    where = (
        f"entity = {entity_id} AND "
        f"trandate >= TO_DATE('{start}','YYYY-MM-DD') AND trandate <= TO_DATE('{end}','YYYY-MM-DD')"
    )
    for row in suiteql_paginate(
        "id, tranid, trandate, duedate, total, custbody_cgh_ro", "vendorbill", where
    ):
        yield {
            "invoice_number": row["tranid"],
            "invoice_date": parse_ns_date(row.get("trandate")),
            "due_date": parse_ns_date(row.get("duedate")),
            "outstanding_amount": float(row["total"]) if row.get("total") not in (None, "") else None,
            "ro_number": row.get("custbody_cgh_ro"),
            "description": f"Bill #{row['tranid']}",
            "netsuite_id": row["id"],
        }


def fetch_credits(entity_id: int, start: str, end: str):
    where = (
        f"entity = {entity_id} AND "
        f"trandate >= TO_DATE('{start}','YYYY-MM-DD') AND trandate <= TO_DATE('{end}','YYYY-MM-DD')"
    )
    for row in suiteql_paginate(
        "id, tranid, trandate, total, custbody_cgh_ro", "vendorcredit", where
    ):
        total = float(row["total"]) if row.get("total") not in (None, "") else None
        yield {
            "invoice_number": row["tranid"],
            "invoice_date": parse_ns_date(row.get("trandate")),
            "due_date": None,
            "outstanding_amount": -total if total is not None else None,
            "ro_number": row.get("custbody_cgh_ro"),
            "description": f"Bill Credit #{row['tranid']}",
            "netsuite_id": row["id"],
        }


def load_rows(conn, vendor_id: str, vendor_name: str, rows: list, source_label: str):
    """Bulk-inserts via cursor.executemany() with fast_executemany=True --
    measured at ~130x faster than one conn.execute() per row against this
    Azure SQL instance (500 rows: 1.87s vs ~242s), which matters at this
    script's row count (thousands of bills/credits per multi-month
    window). fast_executemany is a pyodbc-specific flag (no-op/absent on
    the local SQLite connection, which is plenty fast for row-by-row
    already) -- only meaningful on the cursor it's set on."""
    statement_id = f"VOUCHER-{vendor_id}"
    now = datetime.now(timezone.utc).isoformat()

    cur = conn.cursor()
    if hasattr(cur, "fast_executemany"):
        cur.fast_executemany = True

    cur.execute("DELETE FROM bronze_internal_erp_raw WHERE statement_id = ?", [statement_id])
    cur.execute(
        "DELETE FROM silver_reconciliation_standard WHERE statement_id = ? AND record_source = 'INTERNAL_ERP'",
        [statement_id],
    )

    bronze_params = []
    silver_by_record_id = {}  # last-write-wins per record_id -- see below
    for row in rows:
        if not row["invoice_number"] or row["outstanding_amount"] is None:
            continue
        statement_period = row["invoice_date"][:7] if row["invoice_date"] else None

        bronze_params.append([
            vendor_id, source_label, statement_id, statement_period, now,
            row["invoice_number"], row["invoice_date"], row["invoice_date"],
            row["outstanding_amount"], row["outstanding_amount"],
            row["ro_number"], None, None, "POSTED", 1,
        ])

        invoice_number_normalized = normalize_invoice_number(row["invoice_number"])
        record_id = hashlib.sha256(
            f"INTERNAL_ERP|{statement_id}|{row['invoice_number']}|{row['outstanding_amount']}|1".encode()
        ).hexdigest()

        # record_id is a hash of (statement_id, invoice_number,
        # outstanding_amount) -- a handful of NetSuite bills/credits across
        # a full company-wide multi-month window legitimately share that
        # exact pair (confirmed: a live 3-month pull hit a UNIQUE
        # constraint violation on silver_reconciliation_standard).
        # load_voucher_data.py never hits this because it writes via
        # INSERT OR REPLACE (translated to a T-SQL MERGE for Azure), which
        # is exactly a last-write-wins upsert -- deduping here in Python
        # before the bulk insert reproduces that same semantics while
        # keeping the fast_executemany path (a plain INSERT, not a MERGE).
        silver_by_record_id[record_id] = [
            record_id, "INTERNAL_ERP", "NETSUITE_API_EXTRACT", statement_id,
            row["invoice_date"], vendor_id, vendor_name, None,
            row["invoice_number"], invoice_number_normalized, row["invoice_date"],
            row["ro_number"], None, None, row["outstanding_amount"], None,
            row["outstanding_amount"], row["due_date"], row["invoice_date"], "POSTED",
            row["description"], "USD", statement_period, "netsuite_api", now,
        ]
    silver_params = list(silver_by_record_id.values())

    if bronze_params:
        cur.executemany(
            """
            INSERT INTO bronze_internal_erp_raw (
                vendor_id, source, statement_id, statement_period,
                ingestion_timestamp, raw_invoice_number, raw_invoice_date,
                raw_posting_date, raw_amount, raw_outstanding_amount,
                raw_ro_number, raw_po_number, raw_shop, raw_status, erp_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            bronze_params,
        )
    if silver_params:
        cur.executemany(
            """
            INSERT INTO silver_reconciliation_standard (
                record_id, record_source, document_type, statement_id,
                statement_date, vendor_id, vendor_name, shop,
                invoice_number, invoice_number_normalized, invoice_date,
                ro_number, po_number, work_order_number, amount, credit,
                outstanding_amount, due_date, posting_date, status,
                description, currency, statement_period, source_file,
                ingestion_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            silver_params,
        )

    conn.commit()
    return len(silver_params)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity-id", type=int, required=True, help="NetSuite internal id for the vendor entity")
    parser.add_argument("--vendor-id", required=True, help="Canonical vendor_id, e.g. FRED_BEANS_PARTS")
    parser.add_argument("--vendor-name", required=True, help="Vendor display name, e.g. 'FRED BEANS PARTS'")
    parser.add_argument("--start", required=True, help="Period start, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Period end, YYYY-MM-DD")
    args = parser.parse_args()

    print(f"Fetching vendorbill rows for entity={args.entity_id}, {args.start}..{args.end}...")
    bills = list(fetch_bills(args.entity_id, args.start, args.end))
    print(f"  {len(bills)} bills fetched.")

    print(f"Fetching vendorcredit rows for entity={args.entity_id}, {args.start}..{args.end}...")
    credits = list(fetch_credits(args.entity_id, args.start, args.end))
    print(f"  {len(credits)} credits fetched.")

    all_rows = bills + credits
    print(f"\nWriting {len(all_rows)} rows to bronze_internal_erp_raw / silver_reconciliation_standard...")
    conn = get_connection()
    try:
        written = load_rows(conn, args.vendor_id, args.vendor_name, all_rows, "NETSUITE_API")
    finally:
        conn.close()

    print(f"\nDone. {written} rows loaded under statement_id=VOUCHER-{args.vendor_id}")
    print("Note: early-payment discounts are not included -- see this script's module docstring.")


if __name__ == "__main__":
    main()
