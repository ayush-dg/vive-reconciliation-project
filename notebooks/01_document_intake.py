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
    3. Calls Document Understanding Engine (Azure Claude Sonnet 4.6 → pdfplumber/OCR)
       -- except text-embedded PDFs matching a known Python-library vendor
       signature, routed to a deterministic pdfplumber extractor instead
       (see _determine_extraction_route()).
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

from src.ai.document_understanding_engine import (
    CorruptedPDFError, DocumentUnderstandingEngine, extract_pdf_text,
)
# A deterministic pdfplumber extractor, used in place of
# DocumentUnderstandingEngine for text-embedded PDFs matching the known
# vendors listed in src/extraction/python_library/adapter.py's _FIELD_MAP
# (see _determine_extraction_route() below). Any scanned PDF, any vendor
# not in that map, or a detection failure all take the existing
# DocumentUnderstandingEngine path.
from src.extraction.python_library.adapter import (
    PythonLibraryExtractionEngine, ROUTABLE_VENDOR_SIGNATURES,
)
from src.lakehouse.connection import execute_sql, execute_query, execute_sql_fabric, execute_query_fabric
from src.lakehouse.fabric_bronze import write_bronze_fabric
from src.matching.engine import score_exception_confidence
from src.normalization import normalize_invoice_number
from src.shop_owners import get_shop_owner
from src.vendor_identity import resolve_vendor_id
from src.storage.blob_client import BlobStorageClient


def compute_file_hash(pdf_path: str) -> str:
    """SHA-256 hash of the PDF file — used for cache lookup."""
    with open(pdf_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# Same near-zero-extractable-text heuristic tested against every real PDF
# available in this project (43/44 correct, the one miss being a corrupt
# test file that couldn't be opened as a PDF at all) -- see
# _classify_pdf()'s docstring.
PDF_TYPE_CHECK_PAGES = 3
PDF_TYPE_CHAR_THRESHOLD = 20


def _classify_pdf(pdf_path: str):
    """
    Classifies pdf_path as "text_embedded" or "scanned" -- near-zero
    extractable text (avg < PDF_TYPE_CHAR_THRESHOLD chars/page) across the
    first PDF_TYPE_CHECK_PAGES pages means scanned -- and separately scans
    ALL pages for a known python-library vendor signature (adapter.py's
    ROUTABLE_VENDOR_SIGNATURES), in the same single pdfplumber pass (no
    second file open, no OCR either way).

    Returns (pdf_type, matched_vendor_signature_or_None). pdf_type is
    "unknown" if the PDF couldn't even be opened (corrupt file, missing
    dependency, etc.) -- see _determine_extraction_route()'s docstring for
    why "unknown" is routed exactly like "scanned" (both go to AI): AI
    vision handles any PDF format identically, so a detection failure has
    a safe, non-blocking default, the same "any error -> fall back to AI"
    guarantee the old _is_python_library_vendor() gate made.
    """
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            total_chars = 0
            pages_checked = 0
            matched_vendor = None
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if i < PDF_TYPE_CHECK_PAGES:
                    total_chars += len(text.strip())
                    pages_checked += 1
                if matched_vendor is None:
                    for sig in ROUTABLE_VENDOR_SIGNATURES:
                        if sig in text:
                            matched_vendor = sig
                            break
            avg_chars = total_chars / max(pages_checked, 1)
            pdf_type = "scanned" if avg_chars < PDF_TYPE_CHAR_THRESHOLD else "text_embedded"
            return pdf_type, matched_vendor
    except Exception as e:
        print(f"  Warning: PDF type/vendor detection failed ({e}) — treating as unknown, routing to AI extraction.")
        return "unknown", None


def _determine_extraction_route(pdf_path: str) -> dict:
    """
    Decides which extraction engine handles pdf_path, based on BOTH
    whether it's actually text-embedded or scanned AND whether it matches
    a known python-library vendor signature -- not vendor identity alone.

    [CORRECTED from the prior _is_python_library_vendor() gate, which
    routed purely by vendor-signature match. That happened to work for
    "a known vendor's statement is sometimes scanned" (the signature check
    naturally fails against a scanned page's empty text, so it already
    fell through to AI) -- but it never explicitly classified scanned vs.
    text-embedded for its own sake, so a text-embedded PDF from a vendor
    we've never seen before and a scanned PDF from a vendor we've never
    seen before were indistinguishable: both just "not a known vendor
    signature". This function makes that classification explicit and
    general, so every future PDF -- known vendor or a vendor never seen
    before -- gets a reasoned routing decision, per direct instruction.]

    Three cases:
    1. Text-embedded AND matches a known python-library vendor signature
       -> deterministic pdfplumber (PythonLibraryExtractionEngine). Same
       outcome as the old gate's one working case -- zero regression.
    2. Text-embedded but matches NO known vendor signature -- a genuinely
       new vendor. pdfplumber has no generic column-position parser for
       an unseen layout (extract_all.py's own docstring: a generic
       pdfplumber table-strategy pass was tried and rejected -- layouts
       differ too much for one heuristic to cover safely). Routed to AI
       for now, the only engine that can currently handle an arbitrary
       layout -- but explicitly logged AND tagged into
       schema_result["warnings"] (which lands in document_intake_log, not
       just stdout), so this is visibly a NEW VENDOR case rather than
       silently looking identical to an ordinary AI-routed scanned
       document. It's a visible signal a dedicated extract_<vendor>.py
       module could be built for, not a permanent routing decision.
    3. Scanned (known vendor, new vendor, or detection failed/unknown) ->
       AI vision, which handles any PDF format identically regardless of
       what's underneath (see document_understanding_engine.py).

    Returns {"engine": "python_library"|"ai", "pdf_type": str,
    "matched_vendor": str|None, "reason": str, "new_vendor_warning": str|None}.
    """
    pdf_type, matched_vendor = _classify_pdf(pdf_path)

    if pdf_type == "text_embedded" and matched_vendor:
        return {
            "engine": "python_library", "pdf_type": pdf_type, "matched_vendor": matched_vendor,
            "reason": f"text-embedded, matches known vendor signature {matched_vendor!r}",
            "new_vendor_warning": None,
        }

    if pdf_type == "text_embedded":
        warning = (
            "NEW VENDOR: this PDF has real embedded text but does not match any "
            "known python-library vendor signature — pdfplumber has no generic "
            "parser for an unseen layout, so this was routed to AI extraction "
            "instead. Consider adding a dedicated extract_<vendor>.py module for "
            "this vendor (see extract_astech.py for the simplest template)."
        )
        print(f"  {warning}")
        return {
            "engine": "ai", "pdf_type": pdf_type, "matched_vendor": None,
            "reason": "text-embedded but no known vendor signature matched — no generic pdfplumber parser available",
            "new_vendor_warning": warning,
        }

    return {
        "engine": "ai", "pdf_type": pdf_type, "matched_vendor": matched_vendor,
        "reason": f"{pdf_type} PDF — AI vision handles any format",
        "new_vendor_warning": None,
    }


def check_cache(document_hash: str):
    """Returns the most recent successful extraction cache row for this PDF, or None.

    See RULES.md RULE-02 — row_count > 0 is required; a failed run must
    never be treated as a valid cache hit.

    extraction_cache has been cut over to Fabric Warehouse in production
    (see get_fabric_connection() in src/lakehouse/connection.py) — every
    other table here still reads/writes Azure SQL via execute_query()/
    execute_sql(). execute_query_fabric() has no SQLite/T-SQL dialect
    translation, and falls back to local SQLite in test/dev mode, so this
    query has to be valid on both dialects as written — no trailing LIMIT
    or TOP; the "most recent" row is picked in Python instead.
    """
    rows = execute_query_fabric(
        """
        SELECT * FROM extraction_cache
        WHERE document_hash = ? AND row_count > 0
        ORDER BY ingestion_timestamp DESC
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
    threshold = rules.get("confidence_threshold", 0.0)
    if confidence is not None and float(confidence) < threshold:
        return False, f"LOW_CONFIDENCE: line_confidence {confidence} < threshold {threshold}"

    return True, ""


def write_to_bronze(invoices: list, schema_result: dict, statement_id: str,
                    pdf_path: str, statement_period: str, vendor_id: str,
                    version_info: dict = None) -> int:
    """
    Write validated invoice rows to bronze_vendor_statement_raw.
    Returns count of rows written.

    version_info (see resolve_version_info()) carries
    version_number/previous_statement_id/is_latest_version -- defaults to
    a fresh version 1 when not supplied (e.g. an existing caller that
    hasn't been updated), matching migrations/011_add_version_tracking.sql's
    column defaults.
    """
    version_info = version_info or {"version_number": 1, "previous_statement_id": None, "is_latest_version": 1}
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
                extraction_confidence, extraction_model, raw_ai_response,
                raw_charges, raw_credits, raw_amount_due, raw_transaction_code,
                raw_balance_forward, raw_period_activity, raw_credit_applied, raw_payment_applied,
                version_number, previous_statement_id, is_latest_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                # This row's own raw dynamic-column dict exactly as the AI
                # returned it, before column-mapping collapsed it to this
                # fixed schema (see ClaudeSonnetClient._row_to_invoice()'s
                # "_raw_row") -- lets a future re-mapping recover from a
                # mapping gap without re-calling the AI. None for
                # python-library (pdfplumber) rows, which carry no such key.
                json.dumps(inv["_raw_row"]) if inv.get("_raw_row") is not None else None,
                # New pass-through columns (migrations/010_add_python_extraction_columns.sql)
                # -- NULL when this vendor's document has no such column at
                # all (e.g. KSI's single amount column); populated when the
                # source column genuinely exists, for both extraction paths.
                str(inv["charges"]) if inv.get("charges") is not None else None,
                str(inv["credits"]) if inv.get("credits") is not None else None,
                str(inv["amount_due"]) if inv.get("amount_due") is not None else None,
                inv.get("transaction_code"),
                # Keystone-only ledger fields (migrations/012_add_keystone_ledger_columns.sql)
                # -- NULL for every other vendor, which never populates
                # these keys at all (see adapter.py's "extract_keystone"
                # _FIELD_MAP entry's passthrough_fields).
                str(inv["balance_forward"]) if inv.get("balance_forward") is not None else None,
                str(inv["period_activity"]) if inv.get("period_activity") is not None else None,
                str(inv["credit_applied"]) if inv.get("credit_applied") is not None else None,
                str(inv["payment_applied"]) if inv.get("payment_applied") is not None else None,
                version_info["version_number"],
                version_info["previous_statement_id"],
                version_info["is_latest_version"],
            ]
        )
        count += 1

    return count


def get_skip_reason(invoice: dict) -> str:
    """
    A row is genuinely unusable — not just low-confidence — when it has
    no invoice identifier at all (neither invoice_number nor ro_number),
    since there's then no way to even reference which invoice this row
    is. Returns a skip reason string for such rows, or "" if the row
    should proceed to normal validation (validate_invoice), which may
    still route it to the review queue for other reasons (low
    confidence, bad field type, etc).

    A blank amount alone is deliberately NOT treated as unusable here —
    removed 2026-08-23 (INV-04 amendment, see docs/INVARIANTS.md). Every
    extracted row, blank amount included, must still reach Bronze/Silver;
    whether it's a real exception is now the matching engine's decision
    (src/matching/engine.py), not extraction's.
    """
    def has_value(field):
        val = invoice.get(field)
        return val is not None and str(val).strip() != ""

    if not has_value("invoice_number") and not has_value("ro_number"):
        return "no invoice identifier found"

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
                ai_explanation, match_confidence, shop_owner,
                charges, credits, amount_due, transaction_code
            ) VALUES (?, ?, ?, ?, NULL, 'EXCEPTION', 'EXTRACTION_INCOMPLETE',
                      'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                score_exception_confidence("EXTRACTION_INCOMPLETE"),
                get_shop_owner(vendor_id),
                # New pass-through columns (migrations/010_add_python_extraction_columns.sql)
                # -- NULL for AI-extraction rows, which never carry these keys.
                invoice.get("charges"),
                invoice.get("credits"),
                invoice.get("amount_due"),
                invoice.get("transaction_code"),
            ]
        )
    except Exception as e:
        print(f"  Warning: failed to write EXTRACTION_INCOMPLETE exception to gold_exceptions ({e})")


def copy_extraction_incomplete_exceptions(cached_statement_id: str, new_statement_id: str,
                                           vendor_id: str, source_file: str, statement_period: str) -> int:
    """
    On a cache HIT, run_intake() re-derives Bronze/Silver for the new
    statement_id from the cached run's Bronze rows (see normalize_to_silver()
    call site below) -- but that only ever covers the rows that reached
    Bronze in the first place. Rows write_skip_exception() raised directly
    to gold_exceptions (EXTRACTION_INCOMPLETE -- no invoice identifier at
    all, never reaching Bronze/Silver -- see get_skip_reason()) live ONLY
    under the cached run's original statement_id, and were silently absent
    from every subsequent cache-hit run's totals until now.

    A blank amount alone no longer routes here at all (removed 2026-08-23,
    INV-04 amendment) -- every row with an invoice identifier reaches
    Bronze/Silver regardless of amount, so it's already covered by the
    normal Bronze-copy path above, not this one.

    Copies those rows forward to new_statement_id (fresh exception_id,
    date_raised, statement_period/source_file matching this run -- same
    fields normalize_to_silver() refreshes for the Bronze/Silver copy),
    so a cache-hit run reports the exact same total its original extraction
    did, with no manual step. Always OPEN on the copy, matching how every
    other exception type is freshly (re)computed per statement_id -- this
    mirrors run_matching()'s classify_match() output, not a carried-over
    disposition from the original run.

    Never raises — a logging failure must never block intake.
    """
    try:
        rows = execute_query(
            "SELECT * FROM gold_exceptions WHERE statement_id = ? AND exception_reason = 'EXTRACTION_INCOMPLETE'",
            [cached_statement_id],
        )
    except Exception as e:
        print(f"  Warning: failed to read cached EXTRACTION_INCOMPLETE exceptions ({e})")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    copied = 0
    for row in rows:
        try:
            execute_sql(
                """
                INSERT INTO gold_exceptions (
                    exception_id, vendor_id, invoice_number, statement_amount,
                    erp_amount, match_status, exception_reason, exception_status,
                    source_file, statement_id, date_raised, statement_period,
                    ai_explanation, match_confidence, shop_owner,
                    charges, credits, amount_due, transaction_code
                ) VALUES (?, ?, ?, ?, NULL, 'EXCEPTION', 'EXTRACTION_INCOMPLETE',
                          'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()),
                    vendor_id,
                    row.get("invoice_number"),
                    row.get("statement_amount"),
                    source_file,
                    new_statement_id,
                    now,
                    statement_period,
                    row.get("ai_explanation"),
                    row.get("match_confidence"),
                    row.get("shop_owner"),
                    row.get("charges"),
                    row.get("credits"),
                    row.get("amount_due"),
                    row.get("transaction_code"),
                ]
            )
            copied += 1
        except Exception as e:
            print(f"  Warning: failed to copy one EXTRACTION_INCOMPLETE exception forward ({e})")

    return copied


def write_to_review_queue(invalid_invoices: list, reasons: list,
                           statement_id: str, source_file: str, stage: str):
    """Write invalid records to the review queue.

    validation_document_review_queue is cut over to Fabric Warehouse (see
    get_fabric_connection() in src/lakehouse/connection.py). Its `id`
    column has no IDENTITY there — same situation as extraction_cache,
    see update_cache()'s docstring for why — so each row gets an explicit
    id, computed once as MAX(id)+1 and incremented locally across this
    call's own batch of inserts (so multiple invalid rows from the same
    call never collide with each other). Not concurrency-safe across
    separate calls landing at the same moment — same documented caveat
    as extraction_cache's update_cache().
    """
    now = datetime.now(timezone.utc).isoformat()
    next_id = execute_query_fabric(
        "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM validation_document_review_queue"
    )[0]["next_id"]
    for inv, reason in zip(invalid_invoices, reasons):
        execute_sql_fabric(
            """
            INSERT INTO validation_document_review_queue (
                id, review_id, source_file, statement_id,
                pipeline_stage, rejection_category, rejection_details,
                raw_payload, review_status, flagged_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_REVIEW', ?)
            """,
            [
                next_id,
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
        next_id += 1


def normalize_to_silver(bronze_statement_id: str, silver_statement_id: str, vendor_id: str,
                         version_info: dict = None):
    """
    Read Bronze rows for bronze_statement_id and write normalized rows
    to silver_reconciliation_standard (record_source = VENDOR_STATEMENT),
    tagged with silver_statement_id.

    These differ on a cache hit: Bronze rows live under the previous
    successful run's statement_id, but Silver rows are written under the
    current run's statement_id.

    version_info (see resolve_version_info()) carries
    version_number/previous_statement_id/is_latest_version -- Silver is
    always freshly re-normalized under silver_statement_id even on a cache
    hit (unlike Bronze, which stays under the cached bronze_statement_id),
    which makes Silver the only reliable "always fresh" source of truth
    for version-tracking lookups elsewhere (see run_intake()).
    """
    version_info = version_info or {"version_number": 1, "previous_statement_id": None, "is_latest_version": 1}
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

        # New pass-through columns (migrations/010_add_python_extraction_columns.sql)
        # -- all NULL for AI-extraction rows, which never populate the raw_
        # Bronze columns these read from.
        charges = safe_float(row.get("raw_charges"))
        credits_ = safe_float(row.get("raw_credits"))
        amount_due = safe_float(row.get("raw_amount_due"))
        transaction_code = row.get("raw_transaction_code")

        invoice_number = row.get("raw_invoice_number")
        invoice_number_normalized = normalize_invoice_number(invoice_number)

        # Generate a stable record_id. Includes row_number (unique per Bronze
        # row within a statement) alongside invoice_number/outstanding —
        # outstanding_amount alone is not reliably distinct per row for every
        # vendor layout (e.g. a shared extraction-fallback value across
        # genuinely different lines), and invoice_number+outstanding_amount
        # colliding used to silently overwrite one row with another via
        # INSERT OR REPLACE, losing real rows with no error or log.
        record_id = hashlib.sha256(
            f"VENDOR_STATEMENT|{silver_statement_id}|{invoice_number}|{outstanding}|{row.get('row_number')}".encode()
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
                statement_period, source_file, ingestion_timestamp,
                charges, credits, amount_due, transaction_code,
                version_number, previous_statement_id, is_latest_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                charges,
                credits_,
                amount_due,
                transaction_code,
                version_info["version_number"],
                version_info["previous_statement_id"],
                version_info["is_latest_version"],
            ]
        )
        count += 1

    return count


def write_intake_log(document_id: str, pdf_path: str, document_hash: str,
                     schema_result: dict, statement_id: str, statement_period: str,
                     invoice_count: int, routing_decision: str):
    """Write one row to document_intake_log.

    document_intake_log is cut over to Fabric Warehouse (see
    get_fabric_connection() in src/lakehouse/connection.py). Its `id`
    column has no IDENTITY there either — same situation as
    extraction_cache/validation_document_review_queue — so the new row
    gets an explicit id via MAX(id)+1. Same not-concurrency-safe caveat.
    """
    now = datetime.now(timezone.utc).isoformat()
    meta = schema_result.get("document_metadata", {})
    vendor = schema_result.get("vendor_metadata", {})
    stmt = schema_result.get("statement_metadata", {})
    conf = schema_result.get("extraction_confidence", {})
    warnings = schema_result.get("warnings", [])

    execute_sql_fabric(
        "DELETE FROM document_intake_log WHERE statement_id = ?",
        [statement_id]
    )

    next_id = execute_query_fabric(
        "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM document_intake_log"
    )[0]["next_id"]
    execute_sql_fabric(
        """
        INSERT INTO document_intake_log (
            id, document_id, document_hash, source_file, ingestion_timestamp,
            document_type, document_type_confidence,
            vendor_name, shop_or_entity, statement_date, statement_period,
            currency, statement_total_as_printed,
            extraction_confidence_overall, extraction_model, extraction_method,
            routing_decision, statement_id, invoice_count, warnings, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            next_id,
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
    execute_sql_fabric(
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
    """Insert or replace a cache entry.

    extraction_cache lives on Fabric Warehouse now (see check_cache()).
    execute_sql_fabric() has no SQLite-dialect translation, so the
    INSERT OR REPLACE upsert that execute_sql() would normally rewrite
    into a T-SQL MERGE (see _translate_for_azure()/AZURE_UPSERT_KEYS in
    src/lakehouse/connection.py) is done explicitly here as a SELECT-
    then-UPDATE-or-INSERT, keyed on (document_hash, statement_id) same
    as that translation uses.

    id assignment: the Fabric table's `id` column has no IDENTITY (the
    9 migrated rows carry their original Azure SQL ids as plain
    values — Fabric Warehouse's IDENTITY, confirmed separately, only
    supports BIGINT with large non-sequential distributed values, and
    can't be retrofitted onto an already-populated column without
    recreating the table). New rows get `MAX(id) + 1` computed here.
    This is NOT atomic/concurrency-safe — two workers updating the
    cache for two different documents at the same moment could compute
    the same next id. Low practical risk today (this function only
    runs after a real extraction completes, so collisions require two
    such completions landing in the same instant), but worth a
    deliberate fix (e.g. a real sequence, or switching this column to
    BIGINT IDENTITY on a freshly recreated table) before this table
    sees heavier concurrent write volume.
    """
    now = datetime.now(timezone.utc).isoformat()
    existing = execute_query_fabric(
        "SELECT id FROM extraction_cache WHERE document_hash = ? AND statement_id = ?",
        [document_hash, statement_id]
    )
    if existing:
        execute_sql_fabric(
            """
            UPDATE extraction_cache
            SET source_file = ?, extraction_method = ?, row_count = ?, ingestion_timestamp = ?
            WHERE document_hash = ? AND statement_id = ?
            """,
            [source_file, provider_used, row_count, now, document_hash, statement_id]
        )
        return

    # COALESCE, not ISNULL — this must stay valid on both T-SQL (real
    # Fabric) and SQLite (local/test fallback — see get_fabric_connection()
    # in src/lakehouse/connection.py); ISNULL is T-SQL-only.
    next_id = execute_query_fabric(
        "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM extraction_cache"
    )[0]["next_id"]
    execute_sql_fabric(
        """
        INSERT INTO extraction_cache
            (id, document_hash, statement_id, source_file, extraction_method, row_count, ingestion_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [next_id, document_hash, statement_id, source_file, provider_used, row_count, now]
    )


def resolve_version_info(vendor_id: str, statement_period: str) -> dict:
    """
    Determines whether this intake run is a fresh version 1, or a new
    version superseding a previous one, for this vendor_id + statement_period
    (see migrations/011_add_version_tracking.sql).

    Looks this up in silver_reconciliation_standard, not Bronze — on a
    cache hit, Bronze rows stay under the previous run's statement_id
    (see check_cache()), but Silver is always freshly re-normalized under
    the new statement_id every run, cache hit or not (see
    normalize_to_silver()'s docstring). That makes Silver the only
    reliable place to find the CURRENT is_latest_version=1 row for this
    vendor+period.

    Marks that previous statement's rows across Bronze, Silver, and (if a
    matching run already produced one) gold_reconciliation_summary as
    superseded (is_latest_version = 0) before returning the new version's
    info, so no two statement_ids for the same vendor+period are ever
    both flagged current at once.

    Normally there is at most one is_latest_version=1 row per vendor+period
    -- this function is the only writer of that flag, and it always
    supersedes the old one before setting a new one. But
    migrations/011_add_version_tracking.sql's rollout defaults EVERY
    pre-existing row to is_latest_version=1 (it has no way to know, after
    the fact, which of several historical duplicate uploads for the same
    vendor+period was truly "latest") -- so a vendor+period that already
    had more than one run before this migration can start out with that
    invariant already broken. Ordered DESC and looped over every match
    (not just one) so a pre-existing violation is fully resolved the next
    time this vendor+period is uploaded, rather than only partially
    cleaned up and left broken.
    """
    existing = execute_query(
        """
        SELECT DISTINCT statement_id, version_number
        FROM silver_reconciliation_standard
        WHERE vendor_id = ? AND statement_period = ? AND is_latest_version = 1
          AND record_source = 'VENDOR_STATEMENT'
        ORDER BY version_number DESC
        """,
        [vendor_id, statement_period],
    )
    if not existing:
        return {"version_number": 1, "previous_statement_id": None, "is_latest_version": 1}

    previous_statement_id = existing[0]["statement_id"]
    previous_version = existing[0]["version_number"] or 1

    for row in existing:
        for table in ("bronze_vendor_statement_raw", "silver_reconciliation_standard", "gold_reconciliation_summary"):
            execute_sql(
                f"UPDATE {table} SET is_latest_version = 0 WHERE statement_id = ?",
                [row["statement_id"]],
            )

    return {
        "version_number": previous_version + 1,
        "previous_statement_id": previous_statement_id,
        "is_latest_version": 1,
    }


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

        # Version tracking is keyed on the cached run's actual vendor_id/
        # statement_period (not this call's filename-derived defaults,
        # which may not match if the real vendor name differs) -- see
        # resolve_version_info().
        cached_bronze_row = execute_query(
            "SELECT vendor_id, statement_period FROM bronze_vendor_statement_raw WHERE statement_id = ? LIMIT 1",
            [cached_statement_id],
        )
        cache_vendor_id = cached_bronze_row[0]["vendor_id"] if cached_bronze_row else vendor_id
        cache_statement_period = cached_bronze_row[0]["statement_period"] if cached_bronze_row else statement_period
        version_info = resolve_version_info(cache_vendor_id, cache_statement_period)
        print(f"  Version: {version_info['version_number']} (previous: {version_info['previous_statement_id'] or 'none'})")

        print(f"  Re-running Silver normalization...")
        silver_count = normalize_to_silver(cached_statement_id, statement_id, vendor_id, version_info)
        print(f"  Silver: {silver_count} rows normalized.")
        incomplete_count = copy_extraction_incomplete_exceptions(
            cached_statement_id, statement_id, vendor_id,
            os.path.basename(pdf_path), statement_period
        )
        print(f"  Copied {incomplete_count} EXTRACTION_INCOMPLETE exception(s) forward from the cached run.")
        return {
            "statement_id": statement_id,
            "cache_hit": True,
            "bronze_count": bronze_count,
            "silver_count": silver_count,
            "extraction_incomplete_count": incomplete_count,
        }

    print(f"  Cache MISS — proceeding with extraction.")

    # Step 2: Extract PDF text
    print(f"\n[Step 2] Extracting PDF text with pdfplumber...")
    pdf_text, page_count = extract_pdf_text(pdf_path)
    print(f"  Extracted text from {page_count} pages ({len(pdf_text)} characters)")

    # Step 3: Document Understanding Engine
    # Routes by BOTH text-embedded-vs-scanned classification AND known
    # vendor signature match -- see _determine_extraction_route()'s
    # docstring for the 3 cases this covers and why it replaces the old
    # signature-only gate.
    route = _determine_extraction_route(pdf_path)
    print(f"\n[Step 3] PDF type: {route['pdf_type']} — {route['reason']}")
    if route["engine"] == "python_library":
        print(f"  Running deterministic pdfplumber extraction engine...")
        engine = PythonLibraryExtractionEngine()
    else:
        print(f"  Running Document Understanding Engine...")
        engine = DocumentUnderstandingEngine()
    schema_result = engine.understand(pdf_text, pdf_path, statement_id=statement_id)

    if route["new_vendor_warning"]:
        schema_result.setdefault("warnings", []).append(
            {"code": "NEW_VENDOR_TEXT_EMBEDDED", "message": route["new_vendor_warning"], "severity": "MEDIUM"}
        )

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
    vendor_id = resolve_vendor_id(vendor_name) or vendor_name.upper().replace(" ", "_").replace(",", "")[:50]

    # Update statement_period from AI-detected dates if available
    stmt_meta = schema_result.get("statement_metadata", {})
    if stmt_meta.get("statement_period_end"):
        # Derive YYYY-MM from the end date
        end_date = stmt_meta["statement_period_end"]
        if len(end_date) >= 7:
            statement_period = end_date[:7]  # "2026-05"

    # Version tracking (see resolve_version_info()) -- resolved here, once
    # vendor_id/statement_period reflect the AI-detected values, and before
    # either Bronze or Silver is written below.
    version_info = resolve_version_info(vendor_id, statement_period)
    print(f"  Version: {version_info['version_number']} (previous: {version_info['previous_statement_id'] or 'none'})")

    # Step 4: Validate invoices
    print(f"\n[Step 4] Validating extracted invoices...")
    with open("config/validation/extraction_rules.json", "r") as f:
        validation_rules = json.load(f)

    valid_invoices = []
    invalid_invoices = []
    invalid_reasons = []
    skipped_count = 0

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

        valid_invoices.append(inv)

    print(f"  Valid: {len(valid_invoices)} | Invalid/queued: {len(invalid_invoices)} | Skipped: {skipped_count}")

    # Step 5: Write to Bronze
    print(f"\n[Step 5] Writing to Bronze...")
    bronze_count = write_to_bronze(
        valid_invoices, schema_result, statement_id,
        pdf_path, statement_period, vendor_id, version_info
    )
    print(f"  Bronze rows written: {bronze_count}")

    # Additive Fabric Lakehouse write (new Bronze/Silver dbt pipeline,
    # dbt/) -- never instead of the write above. Same inputs, one more
    # place a copy of the data lands: bronze.bronze_<vendor_id>_raw,
    # written generically for any vendor_id (extraction already normalizes
    # every vendor into this shape -- see fabric_bronze.py's docstring).
    # Silently a no-op when Fabric isn't configured (FABRIC_CLIENT_ID/etc
    # unset in .env) -- the common case for local dev/tests -- and never
    # raises, so a Fabric-side failure can't break this pipeline.
    write_bronze_fabric(
        valid_invoices, schema_result, statement_id,
        pdf_path, statement_period, vendor_id, version_info
    )

    # Write invalid to review queue
    if invalid_invoices:
        write_to_review_queue(
            invalid_invoices, invalid_reasons,
            statement_id, os.path.basename(pdf_path), "AI_EXTRACTION"
        )
        print(f"  Review queue entries: {len(invalid_invoices)}")

    # Step 6: Silver normalization
    print(f"\n[Step 6] Normalizing to Silver...")
    silver_count = normalize_to_silver(statement_id, statement_id, vendor_id, version_info)
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

    try:
        result = run_intake(
            pdf_path=args.pdf,
            statement_id=args.statement_id,
            statement_period=args.period,
        )
    except CorruptedPDFError as e:
        print(f"\nIntake failed — {e}")
        sys.exit(1)

    print(f"Done. Statement ID for next steps: {result['statement_id']}")
