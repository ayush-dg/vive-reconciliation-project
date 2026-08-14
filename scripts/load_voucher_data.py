"""
load_voucher_data.py

Loads vendor payment-voucher data (already extracted into per-vendor
xlsx workbooks by scripts/extract_vendor_wise_vouchers.py) into
bronze_internal_erp_raw / silver_reconciliation_standard as
record_source='INTERNAL_ERP' rows -- standing in for the real
ERP/NetSuite side of reconciliation for vendors where live NetSuite
access doesn't exist yet (see docs/Claude.md Section 3).

Unlike src/mock_erp/generator.py, which regenerates ERP rows scoped to
one specific uploaded statement's statement_id, voucher data is
standing payment history independent of any single upload. Rows here
are written under a synthetic, vendor-scoped statement_id
(f"VOUCHER-{vendor_id}"), one per vendor, that never collides with a
real upload's "STMT-xxxxxxxx" id -- src/matching/engine.py's ERP
lookup must be vendor-scoped (not statement-scoped) to see them.

Re-running this script is idempotent per vendor: it deletes and
replaces that vendor's own rows, not the whole table, so it's safe to
re-run after adding a new voucher_*.xlsx for a vendor already loaded.

Usage:
    python scripts/load_voucher_data.py
    python scripts/load_voucher_data.py --input-dir path/to/vouchers
"""

import argparse
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

import pandas as pd

from src.lakehouse.connection import execute_sql
from src.normalization import normalize_invoice_number
from src.vendor_identity import resolve_vendor_id

DESCRIPTION_RE = re.compile(r"^Bill(?: Credit)? #(.+)$", re.IGNORECASE)


def fallback_vendor_id(vendor_name: str) -> str:
    return vendor_name.upper().replace(" ", "_").replace(",", "")[:50]


def parse_amount(value) -> float:
    """Handles raw-text amounts with thousand-separator commas (e.g.
    "-1,687.60"), as produced by extract_vendor_wise_vouchers.py's PDF
    text extraction. Returns None if value is blank/unparseable."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value) -> str:
    """Returns YYYY-MM-DD, or None if unparseable."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def load_voucher_workbook(path: Path) -> list:
    """Returns parsed line-item dicts for one voucher_*.xlsx, one per
    Bill/Bill Credit row -- rows whose description doesn't match that
    pattern (or have no applied_amount) are skipped, not raised on."""
    xls = pd.ExcelFile(path)
    summary = pd.read_excel(xls, "Voucher Summary").iloc[0]
    detail = pd.read_excel(xls, "Line Items")

    vendor_name = str(summary["vendor"]).strip()
    voucher_date = parse_date(summary.get("voucher_date"))
    vendor_id = resolve_vendor_id(vendor_name) or fallback_vendor_id(vendor_name)

    rows = []
    skipped = 0
    for _, row in detail.iterrows():
        description = str(row["description"]).strip()
        match = DESCRIPTION_RE.match(description)
        outstanding = parse_amount(row.get("applied_amount"))
        if not match or outstanding is None:
            skipped += 1
            continue
        rows.append(
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "invoice_number": match.group(1).strip(),
                "invoice_date": parse_date(row.get("date")),
                "outstanding_amount": outstanding,
                "posting_date": voucher_date,
                "source_file": row.get("file") or path.name,
                "description": description,
            }
        )

    print(
        f"  {path.name}: vendor={vendor_name!r} vendor_id={vendor_id!r} "
        f"rows={len(rows)} skipped={skipped}"
    )
    return rows


def load_vendor_rows(vendor_id: str, rows: list):
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
                "VOUCHER_ACTUAL",
                statement_id,
                statement_period,
                now,
                row["invoice_number"],
                row["invoice_date"],
                row["posting_date"],
                row["outstanding_amount"],
                row["outstanding_amount"],
                None,
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
                "VOUCHER_ACTUAL_EXTRACT",
                statement_id,
                row["posting_date"],
                row["vendor_id"],
                row["vendor_name"],
                None,
                row["invoice_number"],
                invoice_number_normalized,
                row["invoice_date"],
                None,
                None,
                None,
                row["outstanding_amount"],
                None,
                row["outstanding_amount"],
                None,
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
    parser.add_argument(
        "--input-dir",
        default=PROJECT_ROOT,
        help="Directory containing voucher_*.xlsx workbooks (as produced by scripts/extract_vendor_wise_vouchers.py).",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    paths = sorted(input_dir.glob("voucher_*.xlsx"))
    if not paths:
        raise SystemExit(f"No voucher_*.xlsx files found in {input_dir}")

    by_vendor = {}
    print("Reading voucher workbooks...")
    for path in paths:
        for row in load_voucher_workbook(path):
            by_vendor.setdefault(row["vendor_id"], []).append(row)

    print("\nLoading into bronze_internal_erp_raw / silver_reconciliation_standard...")
    for vendor_id, rows in by_vendor.items():
        load_vendor_rows(vendor_id, rows)
        print(f"  {vendor_id}: {len(rows)} rows loaded under statement_id=VOUCHER-{vendor_id}")

    print(
        "\nNote: this only populates the INTERNAL_ERP side. Matching against it still "
        "requires src/matching/engine.py's vendor-scoped lookup, and a real vendor "
        "statement processed through 01_document_intake.py for the VENDOR_STATEMENT side."
    )


if __name__ == "__main__":
    main()
