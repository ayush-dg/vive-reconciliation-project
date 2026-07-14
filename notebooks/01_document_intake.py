"""
01_document_intake.py

Main document intake pipeline.
Run this to process any vendor statement PDF.

Usage:
    python notebooks/01_document_intake.py --pdf sample_data/your_statement.pdf
    python notebooks/01_document_intake.py --pdf sample_data/your_statement.pdf --statement-id STMT-001

What it does:
    1. Checks extraction cache (skip AI if already processed)
    2. Extracts PDF text with pdfplumber
    3. Calls Document Understanding Engine (Azure OpenAI gpt-5-mini → pdfplumber/OCR)
    4. Validates extracted invoices
    5. Writes valid invoices to bronze_vendor_statement_raw
    6. Normalizes to silver_reconciliation_standard
    7. Logs to document_intake_log
    8. Updates extraction_cache
"""

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows' default console codepage (cp1252) can't encode every character
# that might appear in AI-extracted vendor/warning text — force UTF-8
# regardless of the console's active codepage.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Load .env file
from dotenv import load_dotenv
load_dotenv()

from src.ai.document_understanding_engine import DocumentUnderstandingEngine, extract_pdf_text
from src.lakehouse.connection import execute_sql, execute_query
from src.normalization import normalize_invoice_number


def compute_file_hash(pdf_path: str) -> str:
    """SHA-256 hash of the PDF file — used for cache lookup."""
    with open(pdf_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_cache(document_hash: str):
    """Returns the most recent successful extraction cache row for this PDF, or None.

    See RULES.md RULE-02 — row_count > 0 is required; a failed run must
    never be treated as a valid cache hit.
    """
    rows = execute_query(
        """
        SELECT * FROM extraction_cache
        WHERE document_hash = ? AND row_count > 0
        ORDER BY ingestion_timestamp DESC
        LIMIT 1
        """,
        [document_hash]
    )
    return rows[0] if rows else None


def validate_invoice(invoice: dict, rules: dict):
    """
    Validate a single extracted invoice line.
    Returns (is_valid, rejection_reason).
    """
    # If outstanding_amount is missing but amount exists, use amount as fallback.
    # This handles vendors whose statements use a single amount column (e.g. KSI "Remaining Amount").
    if invoice.get("outstanding_amount") is None and invoice.get("amount") is not None:
        invoice["outstanding_amount"] = invoice["amount"]

    required = rules.get("required_fields", ["invoice_number", "outstanding_amount"])
    for field in required:
        val = invoice.get(field)
        if val is None or str(val).strip() == "":
            return False, f"MISSING_MANDATORY_FIELD: {field} is required"

    numeric = rules.get("numeric_fields", ["amount", "outstanding_amount"])
    for field in numeric:
        val = invoice.get(field)
        if val is not None:
            try:
                float(val)
            except (TypeError, ValueError):
                return False, f"INVALID_FIELD_TYPE: {field} must be numeric, got '{val}'"

    # See RULES.md RULE-10 — OCR-derived rows are tagged at 0.50 specifically
    # so they fail this check and route to review; don't lower this threshold
    # without revisiting that rule.
    confidence = invoice.get("line_confidence")
    threshold = rules.get("confidence_threshold", 0.60)
    if confidence is not None and float(confidence) < threshold:
        return False, f"LOW_CONFIDENCE: line_confidence {confidence} < threshold {threshold}"

    return True, ""


def write_to_bronze(invoices: list, schema_result: dict, statement_id: str,
                    pdf_path: str, statement_period: str, vendor_id: str) -> int:
    """
    Write validated invoice rows to bronze_vendor_statement_raw.
    Returns count of rows written.
    """
    now = datetime.now(timezone.utc).isoformat()
    source_file = os.path.basename(pdf_path)
    vendor_name = schema_result.get("vendor_metadata", {}).get("vendor_name")
    provider_used = schema_result.get("_provider_used", "unknown")
    model_used = schema_result.get("_model_used", "")

    # Delete existing rows for this statement_id before re-inserting (idempotent)
    execute_sql(
        "DELETE FROM bronze_vendor_statement_raw WHERE statement_id = ?",
        [statement_id]
    )

    count = 0
    for inv in invoices:
        execute_sql(
            """
            INSERT INTO bronze_vendor_statement_raw (
                vendor_id, vendor_name, source_file, statement_id, statement_period,
                page_number, row_number, ingestion_timestamp,
                raw_invoice_number, raw_invoice_date, raw_due_date,
                raw_amount, raw_outstanding_amount, raw_ro_number,
                raw_po_number, raw_work_order_number, raw_description,
                raw_credit, raw_shop_name, raw_currency,
                extraction_confidence, extraction_model, raw_ai_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                vendor_id,
                vendor_name,
                source_file,
                statement_id,
                statement_period,
                inv.get("page_number"),
                inv.get("row_number"),
                now,
                inv.get("invoice_number"),
                inv.get("invoice_date"),
                inv.get("due_date"),
                str(inv.get("amount") or inv.get("outstanding_amount")) if (inv.get("amount") or inv.get("outstanding_amount")) is not None else None,
                str(inv.get("outstanding_amount") or inv.get("amount")) if (inv.get("outstanding_amount") or inv.get("amount")) is not None else None,
                inv.get("ro_number"),
                inv.get("po_number"),
                inv.get("work_order_number"),
                inv.get("description"),
                str(inv.get("credit")) if inv.get("credit") is not None else None,
                inv.get("shop") or (schema_result.get("vendor_metadata", {}).get("shop_or_entity") or [None])[0],
                schema_result.get("statement_metadata", {}).get("currency"),
                inv.get("line_confidence"),
                f"{provider_used}/{model_used}",
                None,  # don't store full AI response in every row
            ]
        )
        count += 1

    return count


def write_to_review_queue(invalid_invoices: list, reasons: list,
                           statement_id: str, source_file: str, stage: str):
    """Write invalid records to the review queue."""
    now = datetime.now(timezone.utc).isoformat()
    for inv, reason in zip(invalid_invoices, reasons):
        execute_sql(
            """
            INSERT INTO validation_document_review_queue (
                review_id, source_file, statement_id,
                pipeline_stage, rejection_category, rejection_details,
                raw_payload, review_status, flagged_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING_REVIEW', ?)
            """,
            [
                str(uuid.uuid4()),
                source_file,
                statement_id,
                stage,
                reason.split(":")[0],  # e.g. "MISSING_MANDATORY_FIELD"
                reason,
                json.dumps(inv),
                now,
            ]
        )


def normalize_to_silver(bronze_statement_id: str, silver_statement_id: str, vendor_id: str):
    """
    Read Bronze rows for bronze_statement_id and write normalized rows
    to silver_reconciliation_standard (record_source = VENDOR_STATEMENT),
    tagged with silver_statement_id.

    These differ on a cache hit: Bronze rows live under the previous
    successful run's statement_id, but Silver rows are written under the
    current run's statement_id.
    """
    bronze_rows = execute_query(
        "SELECT * FROM bronze_vendor_statement_raw WHERE statement_id = ?",
        [bronze_statement_id]
    )

    if not bronze_rows:
        print("  [Silver] No Bronze rows to normalize.")
        return 0

    # Delete existing Silver rows for this statement_id (idempotent)
    execute_sql(
        "DELETE FROM silver_reconciliation_standard WHERE statement_id = ? AND record_source = 'VENDOR_STATEMENT'",
        [silver_statement_id]
    )

    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for row in bronze_rows:
        # Parse amount
        def safe_float(val):
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        amount = safe_float(row.get("raw_amount")) or safe_float(row.get("raw_outstanding_amount"))
        outstanding = safe_float(row.get("raw_outstanding_amount"))
        credit = safe_float(row.get("raw_credit"))

        invoice_number = row.get("raw_invoice_number")
        invoice_number_normalized = normalize_invoice_number(invoice_number)

        # Generate a stable record_id
        record_id = hashlib.sha256(
            f"VENDOR_STATEMENT|{silver_statement_id}|{invoice_number}|{outstanding}".encode()
        ).hexdigest()

        execute_sql(
            """
            INSERT OR REPLACE INTO silver_reconciliation_standard (
                record_id, record_source, document_type, statement_id,
                statement_date, vendor_id, vendor_name, shop,
                invoice_number, invoice_number_normalized, invoice_date,
                ro_number, po_number, work_order_number,
                amount, credit, outstanding_amount, due_date,
                posting_date, status, description, currency,
                statement_period, source_file, ingestion_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record_id,
                "VENDOR_STATEMENT",
                "VENDOR_STATEMENT",
                silver_statement_id,
                row.get("statement_period"),   # statement_date — use period as proxy
                row.get("vendor_id"),
                row.get("vendor_name"),
                row.get("raw_shop_name"),
                invoice_number,
                invoice_number_normalized,
                row.get("raw_invoice_date"),
                row.get("raw_ro_number"),
                row.get("raw_po_number"),
                row.get("raw_work_order_number"),
                amount,
                credit,
                outstanding,
                row.get("raw_due_date"),
                None,   # posting_date — ERP concept, not applicable here
                None,   # status — ERP concept
                row.get("raw_description"),
                row.get("raw_currency"),
                row.get("statement_period"),
                row.get("source_file"),
                now,
            ]
        )
        count += 1

    return count


def write_intake_log(document_id: str, pdf_path: str, document_hash: str,
                     schema_result: dict, statement_id: str, statement_period: str,
                     invoice_count: int, routing_decision: str):
    """Write one row to document_intake_log."""
    now = datetime.now(timezone.utc).isoformat()
    meta = schema_result.get("document_metadata", {})
    vendor = schema_result.get("vendor_metadata", {})
    stmt = schema_result.get("statement_metadata", {})
    conf = schema_result.get("extraction_confidence", {})
    warnings = schema_result.get("warnings", [])

    execute_sql(
        "DELETE FROM document_intake_log WHERE statement_id = ?",
        [statement_id]
    )

    execute_sql(
        """
        INSERT INTO document_intake_log (
            document_id, document_hash, source_file, ingestion_timestamp,
            document_type, document_type_confidence,
            vendor_name, shop_or_entity, statement_date, statement_period,
            currency, statement_total_as_printed,
            extraction_confidence_overall, extraction_model, extraction_method,
            routing_decision, statement_id, invoice_count, warnings, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            document_id,
            document_hash,
            os.path.basename(pdf_path),
            now,
            meta.get("document_type"),
            meta.get("document_type_confidence"),
            vendor.get("vendor_name"),
            json.dumps(vendor.get("shop_or_entity", [])),
            stmt.get("statement_date"),
            statement_period,
            stmt.get("currency"),
            stmt.get("statement_total_as_printed"),
            conf.get("overall"),
            schema_result.get("_model_used"),
            schema_result.get("_provider_used"),
            routing_decision,
            statement_id,
            invoice_count,
            json.dumps(warnings),
            "1.0",
        ]
    )


def update_cache(document_hash: str, statement_id: str, source_file: str,
                 provider_used: str, row_count: int):
    """Insert or replace a cache entry."""
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        INSERT OR REPLACE INTO extraction_cache
            (document_hash, statement_id, source_file, extraction_method, row_count, ingestion_timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [document_hash, statement_id, source_file, provider_used, row_count, now]
    )


def run_intake(pdf_path: str, statement_id: str = None, statement_period: str = None):
    """
    Main intake function. Called by the CLI or directly from other scripts.
    Returns a summary dict.
    """
    print(f"\n{'='*60}")
    print(f"DOCUMENT INTAKE")
    print(f"PDF: {pdf_path}")
    print(f"{'='*60}")

    # Validate PDF exists
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Generate IDs
    document_id = str(uuid.uuid4())
    if not statement_id:
        statement_id = f"STMT-{uuid.uuid4().hex[:8].upper()}"
    if not statement_period:
        statement_period = datetime.now().strftime("%Y-%m")

    # Derive vendor_id from filename (generic — AI will discover the real vendor name)
    vendor_id = os.path.splitext(os.path.basename(pdf_path))[0].upper().replace(" ", "_")

    print(f"Statement ID: {statement_id}")
    print(f"Statement Period: {statement_period}")

    # Step 1: Cache check
    print(f"\n[Step 1] Checking extraction cache...")
    document_hash = compute_file_hash(pdf_path)
    cached = check_cache(document_hash)
    if cached:
        cached_statement_id = cached["statement_id"]
        bronze_count = execute_query(
            "SELECT COUNT(*) as cnt FROM bronze_vendor_statement_raw WHERE statement_id = ?",
            [cached_statement_id]
        )[0]["cnt"]
        print(f"  Cache HIT — {bronze_count} rows already in Bronze under {cached_statement_id}. Skipping AI extraction.")
        print(f"  Re-running Silver normalization...")
        silver_count = normalize_to_silver(cached_statement_id, statement_id, vendor_id)
        print(f"  Silver: {silver_count} rows normalized.")
        return {
            "statement_id": statement_id,
            "cache_hit": True,
            "bronze_count": bronze_count,
            "silver_count": silver_count,
        }

    print(f"  Cache MISS — proceeding with extraction.")

    # Step 2: Extract PDF text
    print(f"\n[Step 2] Extracting PDF text with pdfplumber...")
    pdf_text, page_count = extract_pdf_text(pdf_path)
    print(f"  Extracted text from {page_count} pages ({len(pdf_text)} characters)")

    # Step 3: Document Understanding Engine
    print(f"\n[Step 3] Running Document Understanding Engine...")
    engine = DocumentUnderstandingEngine()
    schema_result = engine.understand(pdf_text, pdf_path, statement_id=statement_id)

    provider_used = schema_result.get("_provider_used", "unknown")
    invoices = schema_result.get("invoices", [])
    print(f"  Provider used: {provider_used}")
    print(f"  Invoices found: {len(invoices)}")
    print(f"  Overall confidence: {schema_result.get('extraction_confidence', {}).get('overall', 'N/A')}")

    # Update vendor_id from AI-detected vendor name if available
    vendor_name = schema_result.get("vendor_metadata", {}).get("vendor_name")
    if vendor_name:
        vendor_id = vendor_name.upper().replace(" ", "_").replace(",", "")[:50]

    # Update statement_period from AI-detected dates if available
    stmt_meta = schema_result.get("statement_metadata", {})
    if stmt_meta.get("statement_period_end"):
        # Derive YYYY-MM from the end date
        end_date = stmt_meta["statement_period_end"]
        if len(end_date) >= 7:
            statement_period = end_date[:7]  # "2026-05"

    # Step 4: Validate invoices
    print(f"\n[Step 4] Validating extracted invoices...")
    with open("config/validation/extraction_rules.json", "r") as f:
        validation_rules = json.load(f)

    valid_invoices = []
    invalid_invoices = []
    invalid_reasons = []

    seen_keys = set()
    dup_fields = validation_rules.get("duplicate_key_fields", ["invoice_number", "outstanding_amount"])

    for inv in invoices:
        is_valid, reason = validate_invoice(inv, validation_rules)
        if not is_valid:
            invalid_invoices.append(inv)
            invalid_reasons.append(reason)
            continue

        # Duplicate check
        dup_key = tuple(str(inv.get(f)) for f in dup_fields)
        if dup_key in seen_keys:
            invalid_invoices.append(inv)
            invalid_reasons.append(f"DUPLICATE_RECORD: duplicate key {dup_key}")
            continue
        seen_keys.add(dup_key)
        valid_invoices.append(inv)

    print(f"  Valid: {len(valid_invoices)} | Invalid/queued: {len(invalid_invoices)}")

    # Step 5: Write to Bronze
    print(f"\n[Step 5] Writing to Bronze...")
    bronze_count = write_to_bronze(
        valid_invoices, schema_result, statement_id,
        pdf_path, statement_period, vendor_id
    )
    print(f"  Bronze rows written: {bronze_count}")

    # Write invalid to review queue
    if invalid_invoices:
        write_to_review_queue(
            invalid_invoices, invalid_reasons,
            statement_id, os.path.basename(pdf_path), "AI_EXTRACTION"
        )
        print(f"  Review queue entries: {len(invalid_invoices)}")

    # Step 6: Silver normalization
    print(f"\n[Step 6] Normalizing to Silver...")
    silver_count = normalize_to_silver(statement_id, statement_id, vendor_id)
    print(f"  Silver rows written: {silver_count}")

    # Step 7: Write intake log
    doc_type = schema_result.get("document_metadata", {}).get("document_type", "UNKNOWN")
    routing = "RECONCILIATION" if doc_type == "VENDOR_STATEMENT" else "PARKED"
    write_intake_log(
        document_id, pdf_path, document_hash, schema_result,
        statement_id, statement_period, bronze_count, routing
    )

    # Step 8: Update cache
    update_cache(document_hash, statement_id, os.path.basename(pdf_path),
                 provider_used, bronze_count)

    # Final summary
    print(f"\n{'='*60}")
    print(f"INTAKE COMPLETE")
    print(f"  Statement ID:    {statement_id}")
    print(f"  Vendor:          {vendor_name or 'Unknown (see intake log)'}")
    print(f"  Period:          {statement_period}")
    print(f"  Provider used:   {provider_used}")
    print(f"  Invoices found:  {len(invoices)}")
    print(f"  Bronze rows:     {bronze_count}")
    print(f"  Silver rows:     {silver_count}")
    print(f"  Invalid/queued:  {len(invalid_invoices)}")
    print(f"  Routing:         {routing}")
    print(f"{'='*60}\n")

    # Auto-suggest exception targets from extracted Silver rows
    if bronze_count > 0:
        try:
            # Get a sample of real invoice numbers and amounts from Silver
            sample_rows = execute_query(
                """
                SELECT invoice_number, outstanding_amount
                FROM silver_reconciliation_standard
                WHERE statement_id = ? AND record_source = 'VENDOR_STATEMENT'
                  AND invoice_number IS NOT NULL
                  AND outstanding_amount IS NOT NULL
                ORDER BY outstanding_amount DESC
                LIMIT 10
                """,
                [statement_id]
            )

            if sample_rows and len(sample_rows) >= 3:
                # Pick 2 for missing, 1 for amount mismatch
                missing_candidates = [r["invoice_number"] for r in sample_rows[:2]]
                mismatch_candidate = sample_rows[2]
                mismatch_amount = round(mismatch_candidate["outstanding_amount"] * 0.85, 2)

                print(f"\n{'='*60}")
                print(f"SUGGESTED EXCEPTION TARGETS")
                print(f"(All from extracted data — safe to use in scenario_config.json)")
                print(f"{'='*60}")
                print(f"""
{{
  "controlled_exceptions": {{
    "missing_invoices": {json.dumps(missing_candidates)},
    "amount_mismatches": {{"{mismatch_candidate['invoice_number']}": {mismatch_amount}}},
    "duplicate_invoices": [],
    "pending_posting": []
  }}
}}""")
                print(f"{'='*60}\n")
        except Exception:
            pass  # Suggestions are optional — never block the pipeline

    return {
        "statement_id": statement_id,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "statement_period": statement_period,
        "provider_used": provider_used,
        "cache_hit": False,
        "total_invoices": len(invoices),
        "bronze_count": bronze_count,
        "silver_count": silver_count,
        "invalid_count": len(invalid_invoices),
        "routing": routing,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Document Intake — process a vendor statement PDF")
    parser.add_argument("--pdf", required=True, help="Path to the PDF file")
    parser.add_argument("--statement-id", help="Optional statement ID (auto-generated if not provided)")
    parser.add_argument("--period", help="Statement period override, e.g. 2026-05")
    args = parser.parse_args()

    result = run_intake(
        pdf_path=args.pdf,
        statement_id=args.statement_id,
        statement_period=args.period,
    )

    print(f"Done. Statement ID for next steps: {result['statement_id']}")
