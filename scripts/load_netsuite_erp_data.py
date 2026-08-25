"""
load_netsuite_erp_data.py

Pulls vendor bill and vendor credit data for one NetSuite entity via SuiteQL
and loads it into bronze_internal_erp_raw / silver_reconciliation_standard,
under the same synthetic statement_id convention as scripts/load_voucher_data.py
("VOUCHER-<vendor_id>") -- src/matching/engine.py's run_matching() reads
INTERNAL_ERP rows from that exact statement_id (hardcoded, not a generic
vendor-scoped lookup, see engine.py's erp_rows query), so this has to match
it precisely for matching to see this data at all.

Consequence worth knowing: this DELETES and REPLACES whatever's currently
under VOUCHER-<vendor_id> (same idempotent-per-vendor pattern as
load_voucher_data.py) -- if that vendor previously had voucher-xlsx data
loaded, this replaces it with NetSuite data as the new source of truth.

Row source labeling deliberately differs from load_voucher_data.py's
("VOUCHER_ACTUAL" / "VOUCHER_ACTUAL_EXTRACT"): these rows are labeled
"NETSUITE_ERP" / "NETSUITE_VENDOR_BILL" or "NETSUITE_VENDOR_CREDIT" instead,
so lineage stays honest at the row level even though the statement_id is
shared with the voucher path.

custbody_cgh_ro is mapped through to ro_number (bronze raw_ro_number /
silver ro_number) -- unlike load_voucher_data.py, which never populates it
(voucher extracts don't carry an RO number), NetSuite's query here does, and
engine.py's Level 2 matching (RO number + amount) can use it.

vendorcredit.total is inserted as-is (not sign-flipped), matching
load_voucher_data.py's own precedent of running "Bill Credit #" rows through
the identical code path as regular bills with no sign adjustment. If credits
don't net correctly against statement amounts during matching, this is the
line to revisit.

Pagination: NetSuite silently ignores a SQL OFFSET in the query body under
Prefer: transient and just re-returns page 1 forever. Offset MUST go through
the URL query string instead, incremented by the actual number of items
returned each page (not a fixed step), until hasMore is false.

Usage:
    AZURE_SQL_SERVER=... AZURE_SQL_DATABASE=... AZURE_SQL_USERNAME=... AZURE_SQL_PASSWORD=... \
    python scripts/load_netsuite_erp_data.py

    python scripts/load_netsuite_erp_data.py --entity-id 18706

Filters by the exact BILL_TRANIDS/CREDIT_TRANIDS lists below (extracted from
sample_data/Fred Beans Lee's.pdf), not a date range -- a prior version used
entity + date range and pulled ~9000 rows for the whole vendor, which was
far broader than intended for this reconciliation run.
"""

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.lakehouse.connection import execute_sql
from src.normalization import normalize_invoice_number

REQUIRED_AZURE_SQL_VARS = ["AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "AZURE_SQL_USERNAME", "AZURE_SQL_PASSWORD"]
PAGE_LIMIT = 100


def _netsuite_auth_and_url():
    """Loads NetSuite credentials from netsuite_tools/.env explicitly (not a
    cwd-relative search) -- same variable names and OAuth1 setup as
    netsuite_tools/netsuite-query-record 1.py."""
    load_dotenv(os.path.join(PROJECT_ROOT, "netsuite_tools", ".env"))

    account_id = os.environ["ACCOUNT_ID"]
    consumer_key = os.environ["CONSUMER_KEY"]
    consumer_secret = os.environ["CONSUMER_SECRET"]
    token_id = os.environ["TOKEN_ID"]
    token_secret = os.environ["TOKEN_SECRET"]

    auth = OAuth1(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=token_id,
        resource_owner_secret=token_secret,
        signature_method="HMAC-SHA256",
        realm=account_id,
    )
    url = f"https://{account_id}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"
    return auth, url


def fetch_all_pages(auth, url, query: str) -> list:
    """Runs `query` against SuiteQL, paginating via the URL's offset param
    (never SQL OFFSET -- see module docstring). Increments offset by the
    actual page size returned, not a fixed step, so a final partial page
    still terminates the loop correctly."""
    items = []
    offset = 0
    while True:
        resp = requests.post(
            url,
            auth=auth,
            params={"limit": PAGE_LIMIT, "offset": offset},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Prefer": "transient",
            },
            json={"q": query},
            timeout=30,
        )
        try:
            data = resp.json()
        except ValueError:
            sys.exit(f"NetSuite returned non-JSON response (HTTP {resp.status_code}): {resp.text[:500]}")
        if resp.status_code != 200:
            sys.exit(f"NetSuite query failed (HTTP {resp.status_code}): {data}")

        page_items = data.get("items", [])
        items.extend(page_items)
        if not data.get("hasMore") or not page_items:
            break
        offset += len(page_items)

    return items


# Extracted from sample_data/Fred Beans Lee's.pdf (VIVE COLLISION - LEE'S AUTO
# BODY (W60), customer Z63461611, statement 31JUL26). Confirmed against live
# NetSuite data that `tranid` (not custbody_cgh_ro, which holds an unrelated
# RO-number series) is the field these match, and that vendorcredit.tranid
# does carry the literal "CM" prefix as printed on the statement -- see the
# two spot-check queries this script's diff was reviewed alongside.
#
# Excludes NM070826CU / NM073026Z (a different code pattern -- "60 80"/"60 56"
# rather than "60 35"/"99 57" -- and one is a $14,681.56 lump sum, unlike any
# individual invoice on the statement; unconfirmed whether these are even
# vendorbill/vendorcredit records). Also corrects two OCR-ambiguous reads
# caught by spot-checking against NetSuite: statement showed both "9394147"
# and "9294147" (identical $542.21) -- only 9294147 exists in NetSuite, so
# 9394147 is dropped; same for "9314571X1"/"9354571X1" -- only 9314571X1
# exists.
BILL_TRANIDS = [
    "8944468", "9148606", "9154082", "9154082X1", "9173819X1", "9154082X2",
    "9189267", "9193811", "9304198X1", "9323355", "9334677", "9337199",
    "9337199X1", "9345121", "9346270", "9346648", "9350828", "9352752",
    "9361394", "9363590", "9204799", "9361394X1", "9314571X1", "9373900",
    "9374279", "9374279X1", "9377547", "9377602", "9377829", "9379820",
    "9381515", "8941083", "9382052", "9382356", "9382826", "9385899",
    "9386293", "9386727", "9385886", "9388190", "9388489", "9390665",
    "9392343", "9392353", "9393771", "9294147", "9394188", "9394193",
    "9394208", "9394216", "9394222", "9394841", "9395832", "9396972",
    "9397481", "9397934", "9392343X1", "9400977", "9401022", "9403325",
    "9404007", "9406411", "9409579", "9409929", "9411513", "9412733",
    "9412747", "9412787", "9413458", "9412747X1", "9415971", "9415217",
    "9424476", "9425173", "9424476X1", "9426496", "9427080", "9427251",
    "9428769", "9429198", "9427080X1", "9428769X1", "9431470", "9432440",
    "9434372", "9434372X1", "9437509", "9437906", "9437906X1", "9440604",
    "9438735", "9444877", "9446586", "9446623", "9446986", "9447417",
    "9448200", "9448345", "9449517", "9449524", "9444668", "9437906X2",
    "9452468", "9456172", "9457040", "9457823", "9457937", "9459291",
    "9462067", "9462074", "9462861", "9464366", "9466688", "9467517",
    "9470711", "9470718", "9462861X1", "9470700", "9471316", "9471339",
    "9471406", "9472626", "9474399", "9452436", "9470711X1", "9475105",
    "9475271", "9475399", "9475568", "9476208", "9289628", "9377528",
    "9479190", "9481764", "9482756", "9482929", "9483693",
]

CREDIT_TRANIDS = [
    "CM8944468", "CM9148606", "CM9154082X1", "CM9173819X1", "CM9154082X2",
    "CM9189267", "CM9189267A", "CM9193811", "CM9304198X1", "CM9323355",
    "CM9346648", "CM9204799", "CM9204799A", "CM8941083", "CM9382052",
    "CM9382052A", "CM9385899", "CM9388489", "CM9394216", "CM9396972",
    "CM9397481", "CM9397934", "CM9392343X1", "CM9403325", "CM9409579",
    "CM9411513", "CM9412733", "CM9412733A", "CM9412747", "CM9413458",
    "CM9415971", "CM9424476", "CM9429198", "CM9437906", "CM9437906X1",
    "CM9440604", "CM9444877", "CM9448200", "CM9444668", "CM9470711X1",
    "CM9479190",
]


def build_vendorbill_query(entity_id: int, tranids: list) -> str:
    tranid_list = ",".join(f"'{t}'" for t in tranids)
    return (
        "SELECT id, tranid, trandate, duedate, total, custbody_cgh_ro "
        "FROM vendorbill "
        f"WHERE entity = {entity_id} AND tranid IN ({tranid_list}) "
        "ORDER BY id"
    )


def build_vendorcredit_query(entity_id: int, tranids: list) -> str:
    tranid_list = ",".join(f"'{t}'" for t in tranids)
    return (
        "SELECT id, tranid, trandate, total, custbody_cgh_ro "
        "FROM vendorcredit "
        f"WHERE entity = {entity_id} AND tranid IN ({tranid_list}) "
        "ORDER BY id"
    )


def transform(items: list, record_type: str, vendor_id: str, vendor_name: str) -> list:
    """record_type: 'BILL' or 'CREDIT'. Maps NetSuite columns onto the
    bronze/silver row shape: tranid -> invoice_number, trandate -> both
    invoice_date and posting_date (NetSuite has no separate single posting
    date for a batch the way a voucher workbook does), total ->
    amount/outstanding_amount, duedate -> due_date (bills only), and
    custbody_cgh_ro -> ro_number."""
    rows = []
    for item in items:
        invoice_date = (item.get("trandate") or "")[:10] or None
        rows.append(
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "invoice_number": str(item["tranid"]),
                "invoice_date": invoice_date,
                "posting_date": invoice_date,
                "due_date": (item.get("duedate") or "")[:10] or None,
                "outstanding_amount": float(item["total"]) if item.get("total") not in (None, "") else None,
                "ro_number": item.get("custbody_cgh_ro") or None,
                "source_file": f"NetSuite {record_type.title()} #{item['tranid']} (internal id {item['id']})",
                "description": f"NetSuite {'VendorBill' if record_type == 'BILL' else 'VendorCredit'} {item['tranid']}",
            }
        )
    return rows


def load_vendor_rows(vendor_id: str, rows: list) -> None:
    """Same idempotent delete-then-insert-per-vendor pattern as
    load_voucher_data.py's load_vendor_rows() -- same target statement_id
    convention so run_matching() can find it, different source/document_type
    labels so lineage reflects NetSuite rather than a voucher extract."""
    statement_id = f"VOUCHER-{vendor_id}"
    now = datetime.now(timezone.utc).isoformat()

    execute_sql("DELETE FROM bronze_internal_erp_raw WHERE statement_id = ?", [statement_id])
    execute_sql(
        "DELETE FROM silver_reconciliation_standard WHERE statement_id = ? AND record_source = 'INTERNAL_ERP'",
        [statement_id],
    )

    for row in rows:
        statement_period = row["invoice_date"][:7] if row["invoice_date"] else None

        execute_sql(
            """
            INSERT INTO bronze_internal_erp_raw (
                vendor_id, source, statement_id, statement_period,
                ingestion_timestamp, raw_invoice_number, raw_invoice_date,
                raw_posting_date, raw_amount, raw_outstanding_amount,
                raw_ro_number, raw_po_number, raw_shop, raw_status, erp_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                row["vendor_id"],
                "NETSUITE_ERP",
                statement_id,
                statement_period,
                now,
                row["invoice_number"],
                row["invoice_date"],
                row["posting_date"],
                row["outstanding_amount"],
                row["outstanding_amount"],
                row["ro_number"],
                None,
                None,
                "POSTED",
                1,
            ],
        )

        invoice_number_normalized = normalize_invoice_number(row["invoice_number"])
        record_id = hashlib.sha256(
            f"INTERNAL_ERP|{statement_id}|{row['invoice_number']}|{row['outstanding_amount']}|1".encode()
        ).hexdigest()

        execute_sql(
            """
            INSERT OR REPLACE INTO silver_reconciliation_standard (
                record_id, record_source, document_type, statement_id,
                statement_date, vendor_id, vendor_name, shop,
                invoice_number, invoice_number_normalized, invoice_date,
                ro_number, po_number, work_order_number, amount, credit,
                outstanding_amount, due_date, posting_date, status,
                description, currency, statement_period, source_file,
                ingestion_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record_id,
                "INTERNAL_ERP",
                "NETSUITE_VENDOR_BILL" if row["description"].startswith("NetSuite VendorBill") else "NETSUITE_VENDOR_CREDIT",
                statement_id,
                row["posting_date"],
                row["vendor_id"],
                row["vendor_name"],
                None,
                row["invoice_number"],
                invoice_number_normalized,
                row["invoice_date"],
                row["ro_number"],
                None,
                None,
                row["outstanding_amount"],
                None,
                row["outstanding_amount"],
                row["due_date"],
                row["posting_date"],
                "POSTED",
                row["description"],
                "USD",
                statement_period,
                row["source_file"],
                now,
            ],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity-id", type=int, default=18706, help="NetSuite internal entity ID.")
    parser.add_argument("--vendor-id", default="FRED_BEANS_PARTS", help="Canonical vendor_id (see config/vendor_aliases.json).")
    parser.add_argument("--vendor-name", default="Fred Beans Parts, Inc.", help="Display vendor name.")
    args = parser.parse_args()

    missing = [v for v in REQUIRED_AZURE_SQL_VARS if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing required environment variable(s): {', '.join(missing)}")

    auth, url = _netsuite_auth_and_url()

    print(f"Fetching vendorbill rows for entity {args.entity_id} ({len(BILL_TRANIDS)} tranids from Lee's statement)...")
    bill_items = fetch_all_pages(auth, url, build_vendorbill_query(args.entity_id, BILL_TRANIDS))
    print(f"  {len(bill_items)} vendorbill rows fetched (of {len(BILL_TRANIDS)} tranids requested)")

    print(f"Fetching vendorcredit rows for entity {args.entity_id} ({len(CREDIT_TRANIDS)} tranids from Lee's statement)...")
    credit_items = fetch_all_pages(auth, url, build_vendorcredit_query(args.entity_id, CREDIT_TRANIDS))
    print(f"  {len(credit_items)} vendorcredit rows fetched (of {len(CREDIT_TRANIDS)} tranids requested)")

    rows = transform(bill_items, "BILL", args.vendor_id, args.vendor_name)
    rows += transform(credit_items, "CREDIT", args.vendor_id, args.vendor_name)

    print(f"\nLoading {len(rows)} rows into bronze_internal_erp_raw / silver_reconciliation_standard "
          f"under statement_id=VOUCHER-{args.vendor_id}...")
    load_vendor_rows(args.vendor_id, rows)

    print("\nSummary:")
    print(f"  vendorbill rows pulled:   {len(bill_items)}")
    print(f"  vendorcredit rows pulled: {len(credit_items)}")
    print(f"  total rows written:      {len(rows)}")
    print(f"  vendor_id:               {args.vendor_id}")
    print(f"  statement_id:            VOUCHER-{args.vendor_id}")


if __name__ == "__main__":
    main()
