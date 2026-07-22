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
    8. Uploads the PDF to Azure Blob Storage (never blocks the pipeline)
    9. Updates extraction_cache
"""

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Windows' default console codepage (cp1252) can't encode every character
# that might appear in AI-extracted vendor/warning text — force UTF-8
# regardless of the console's active codepage.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Load .env file by explicit absolute path, matching web/app.py — a bare
# load_dotenv() discovers the file via cwd/call-stack heuristics, which
# depend on how this module was invoked (this script also gets exec'd via
# importlib.util.spec_from_file_location by scripts/run_full_pipeline.py,
# not just run directly). An explicit path removes that ambiguity, so the
# same AZURE_SQL_SERVER check in src/lakehouse/connection.py always sees
# the same .env the web app loaded — otherwise this process can silently
# fall back to the local SQLite db while the web app reads/writes Azure
# SQL, and the two never see each other's extraction_cache rows.
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.ai.document_understanding_engine import DocumentUnderstandingEngine, extract_pdf_text
from src.lakehouse.connection import execute_sql, execute_query
from src.normalization import normalize_invoice_number
from src.storage.blob_client import BlobStorageClient


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


def get_skip_reason(invoice: dict) -> str:
    """
    A row is genuinely unusable — not just low-confidence — when it has
    neither an invoice identifier nor any amount at all. Returns a skip
    reason string for such rows, or "" if the row should proceed to
    normal validation (validate_invoice), which may still route it to the
    review queue for other reasons (missing a single required field,
    low confidence, etc).
    """
    def has_value(field):
        val = invoice.get(field)
        return val is not None and str(val).strip() != ""

    if not has_value("invoice_number") and not has_value("ro_number"):
        return "no invoice identifier found"

    if not has_value("outstanding_amount") and not has_value("amount") and not has_value("credit"):
        return "no amount found"

    return ""


def log_row_skip(statement_id: str, source_file: str, message: str):
    """Log a genuinely-unusable skipped row to ai_audit_log
    (interaction_type='ROW_SKIP'). Never raises — a logging failure must
    never block intake."""
    try:
        execute_sql(
            """
            INSERT INTO ai_audit_log (
                audit_id, source_file, statement_id, interaction_type,
                request_timestamp, success, response_status, error_message
            ) VALUES (?, ?, ?, 'ROW_SKIP', ?, 0, 'ROW_SKIPPED', ?)
            """,
            [
                str(uuid.uuid4()),
                source_file,
                statement_id,
                datetime.now(timezone.utc).isoformat(),
                message,
            ]
        )
    except Exception as e:
        print(f"  Warning: failed to log row skip to ai_audit_log ({e})")


def write_skip_exception(statement_id: str, vendor_id: str, source_file: str,
                          statement_period: str, invoice: dict, message: str):
    """
    Raise a skipped row as an EXTRACTION_INCOMPLETE exception in
    gold_exceptions, so AP reviewers see and can action it on the
    exceptions page — the same table matching writes to, but raised here
    at intake instead, since a skipped row never reaches Silver for the
    matching engine to see at all (see src/matching/engine.py's
    EXTRACTION_INCOMPLETE-exempt DELETE, which keeps this row alive across
    matching re-runs for the same statement_id).

    Never raises — a logging failure must never block intake.
    """
    statement_amount = (
        invoice.get("outstanding_amount")
        if invoice.get("outstanding_amount") is not None
        else invoice.get("amount") if invoice.get("amount") is not None
        else invoice.get("credit")
    )
    now = datetime.now(timezone.utc).isoformat()
    try:
        execute_sql(
            """
            INSERT INTO gold_exceptions (
                exception_id, vendor_id, invoice_number, statement_amount,
                erp_amount, match_status, exception_reason, exception_status,
                source_file, statement_id, date_raised, statement_period,
                ai_explanation
            ) VALUES (?, ?, ?, ?, NULL, 'EXCEPTION', 'EXTRACTION_INCOMPLETE',
                      'OPEN', ?, ?, ?, ?, ?)
            """,
            [
                str(uuid.uuid4()),
                vendor_id,
                invoice.get("invoice_number"),
                statement_amount,
                source_file,
                statement_id,
                now,
                statement_period,
                f"{message}. Please check the original PDF manually.",
            ]
        )
    except Exception as e:
        print(f"  Warning: failed to write EXTRACTION_INCOMPLETE exception to gold_exceptions ({e})")


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


def update_intake_log_blob_path(statement_id: str, blob_storage_path: str):
    """Back-fill blob_storage_path (+ uploaded_at) on the document_intake_log
    row already written for this statement_id — see write_intake_log(),
    which runs first and doesn't yet know the blob location."""
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        "UPDATE document_intake_log SET blob_storage_path = ?, uploaded_at = ? WHERE statement_id = ?",
        [blob_storage_path, now, statement_id]
    )


def derive_vendor_slug_from_filename(pdf_path: str):
    """
    Best-effort vendor slug guessed from the PDF filename, used only when
    extraction didn't yield a vendor_name. Vendor statement filenames are
    typically `<Vendor>[_<Shop/Location>]_<date-digits>.pdf` — split on
    non-alphanumeric separators, drop any token that's purely digits (or
    strip a trailing digit run off an alphanumeric token, e.g.
    "ASTCollex0526" -> "ASTCollex"), and keep at most the first two
    remaining tokens (the vendor name is at the front; shop/location and
    date noise trail after it). Returns None if nothing usable remains.

    Examples: ASTCollex0526.pdf -> astcollex,
    Fred_Beans_MidNJ_053126.pdf -> fred_beans,
    KSI_Noakers_053126.pdf -> ksi_noakers.
    """
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    raw_tokens = re.split(r"[^A-Za-z0-9]+", stem)

    tokens = []
    for tok in raw_tokens:
        stripped = re.sub(r"\d+$", "", tok)
        if stripped:
            tokens.append(stripped)

    if not tokens:
        return None

    return "_".join(t.lower() for t in tokens[:2])


def derive_vendor_name_from_filename(pdf_path: str) -> str:
    """
    Fallback vendor_name used when extraction returns None/empty — unlike
    derive_vendor_slug_from_filename() above (a lowercase, truncated slug
    for Blob Storage paths), this is meant to be stored and displayed as
    the actual vendor_name, so it keeps every token and reads like a name:
    strip the extension, turn separators into spaces, title-case it.

    Examples: Synthetic_Reconciliation_Test_Document.pdf ->
    "Synthetic Reconciliation Test Document"; Unknown_Vendor_May2026.pdf ->
    "Unknown Vendor May2026".
    """
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    return stem.replace("_", " ").replace("-", " ").title()


def upload_pdf_to_blob_storage(pdf_path: str, vendor_name: str, statement_period: str,
                                document_hash: str) -> str:
    """
    Uploads pdf_path to Azure Blob Storage and returns the blob URL, or None
    on any failure. Never raises — BlobStorageClient.upload_pdf() already
    swallows its own errors, but this also guards against anything
    unexpected (e.g. a malformed statement_period) so a Blob Storage issue
    can never crash document intake (see docs/VIVE_Implementation_Context.md
    Section 4, Phase 2, "Object storage (Blob)").

    Vendor slug precedence: (1) vendor_name extracted from the document
    itself (already in document_intake_log by the time this runs), (2) a
    best-effort guess from the PDF filename, (3) BlobStorageClient's own
    "unknown_vendor" fallback if neither is usable.
    """
    try:
        if not vendor_name:
            vendor_name = derive_vendor_slug_from_filename(pdf_path)

        if statement_period and len(statement_period) >= 7:
            year, month = statement_period[:4], statement_period[5:7]
        else:
            now = datetime.now(timezone.utc)
            year, month = f"{now.year:04d}", f"{now.month:02d}"

        return BlobStorageClient().upload_pdf(
            pdf_path, vendor_name, year, month, document_hash,
            original_filename=os.path.basename(pdf_path),
        )
    except Exception as e:
        print(f"  Warning: PDF upload to Blob Storage failed unexpectedly ({e}) — continuing without it.")
        return None


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

    # Update vendor_id from AI-detected vendor name if available. If
    # extraction couldn't determine a vendor name at all, fall back to one
    # derived from the PDF filename — otherwise vendor_name is stored as
    # NULL and the run is hidden from the dashboard (see web/queries.py).
    # Mutating schema_result here (rather than threading a corrected value
    # through every call site) means write_to_bronze() and write_intake_log()
    # below — which both read vendor_metadata.vendor_name straight from
    # schema_result — pick up the same fallback automatically, and so does
    # everything silver/gold inherits from bronze downstream.
    vendor_meta = schema_result.setdefault("vendor_metadata", {})
    vendor_name = vendor_meta.get("vendor_name")
    if not vendor_name or not str(vendor_name).strip():
        vendor_name = derive_vendor_name_from_filename(pdf_path)
        vendor_meta["vendor_name"] = vendor_name
        print(f"  No vendor name extracted — using filename-derived vendor: {vendor_name}")
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
    skipped_count = 0

    seen_keys = set()
    dup_fields = validation_rules.get("duplicate_key_fields", ["invoice_number", "outstanding_amount"])

    for row_num, inv in enumerate(invoices, start=1):
        # Genuinely-unusable rows (no invoice identifier at all, or no
        # amount at all) are skipped outright — they aren't worth a human
        # review queue entry, unlike a row that's merely missing one field
        # or has low confidence (still handled by validate_invoice below).
        skip_reason = get_skip_reason(inv)
        if skip_reason:
            skipped_count += 1
            message = f"Row {row_num} skipped — {skip_reason}"
            print(f"  {message}")
            log_row_skip(statement_id, os.path.basename(pdf_path), message)
            write_skip_exception(statement_id, vendor_id, os.path.basename(pdf_path),
                                  statement_period, inv, message)
            continue

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

    print(f"  Valid: {len(valid_invoices)} | Invalid/queued: {len(invalid_invoices)} | Skipped: {skipped_count}")

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

    # Step 8: Upload PDF to Blob Storage for permanent archival. Silent by
    # design — a failed upload logs a warning but never blocks the pipeline.
    print(f"\n[Step 8] Uploading PDF to Blob Storage...")
    blob_storage_path = upload_pdf_to_blob_storage(
        pdf_path, vendor_name, statement_period, document_hash
    )
    if blob_storage_path:
        update_intake_log_blob_path(statement_id, blob_storage_path)
        print(f"  Uploaded to: {blob_storage_path}")
    else:
        print(f"  Warning: PDF was not archived to Blob Storage — continuing without it.")

    # Step 9: Update cache
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
    print(f"{'='*60}")
    print(f"  {skipped_count} rows skipped (missing required fields)")
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
        "skipped_count": skipped_count,
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
