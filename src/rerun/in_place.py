"""
src/rerun/in_place.py

Re-runs ONE stored statement in place with a deterministic (python-library)
extractor -- no AI -- keeping its statement_id (2026-10-07). For stored
statements whose extraction was wrong but whose PDF a deterministic
extractor now reads correctly (e.g. Autoly rows without Due/Unalloc.,
Wilbert's 0-row statements). Driven by scripts/rerun_in_place.py.

Unlike a normal upload (notebooks/01_document_intake.py run_intake()):
  - no duplicate check and no extraction-cache lookup -- the PDF is the
    statement's own archived copy, re-read on purpose;
  - REFUSES an AI route, and an extractor that returns no rows (the intake
    would silently fall back to AI there);
  - the statement's existing version fields are kept; resolve_version_info()
    is never called (it supersedes other statements' rows);
  - the Lakehouse Bronze rows (bronze.raw_statement, unnested lines/fields
    -- append-only tables) are DELETED for this statement before the new
    ones are written, so old and new lines never mix in Silver;
  - document_intake_log is UPDATEd in place, never deleted/re-inserted; its
    document_id, hash, source file and ingestion_timestamp are kept, so the
    statement stays in the same sync on Home/Validation;
  - the PDF is not uploaded again; extraction_cache is only UPDATEd when
    this statement already has a row there;
  - Silver + NetSuite matching run only when the vendor has a field mapping
    in Fabric for the extracted fields, and -- when the same PDF is stored
    under several statements -- only for the copy that already has a
    recon_summary row (or the earliest copy if none has one);
  - REFUSES a statement with any exception that isn't OPEN (resolved or
    escalated decisions would be reset by re-matching), with more than one
    intake row, or while any job is in flight.

Every run is per statement: plan() (dry run, no writes) -> backup()
(every row of every table touched, read back) -> apply(); undo() restores
the backup. All reads/writes go through an IO object (LiveIO in
production), which the tests replace.
"""

import datetime as dt
import decimal
import hashlib
import importlib.util
import json
import os
import time
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Azure SQL tables holding this statement's rows (all have an IDENTITY id).
# Bronze and the legacy Silver copy are replaced; the others only ever get
# rows added (skipped/invalid rows), which undo removes again by id.
AZ_REPLACED = {
    "bronze_vendor_statement_raw": "statement_id = ?",
    "silver_reconciliation_standard": "statement_id = ? AND record_source = 'VENDOR_STATEMENT'",
}
AZ_APPENDED = {
    "gold_exceptions": "statement_id = ?",
    "validation_document_review_queue": "statement_id = ?",
    "ai_audit_log": "statement_id = ?",
}
# raw_statement_staging normally has no row for a statement (promote moves
# it); a leftover one from an earlier failed run would be promoted along with
# the new row, so it is cleared too.
LAKEHOUSE_TABLES = ("raw_statement", "raw_statement_staging", "unnested_statement_lines", "unnested_statement_fields")
SILVER_TABLES = ("silver.statement", "silver.statement_line")
RECON_TABLES = ("silver.recon_matched_invoices", "silver.recon_exceptions", "silver.recon_summary")
# document_intake_log columns a re-run never changes.
INTAKE_KEPT = ("document_id", "document_hash", "source_file", "ingestion_timestamp", "statement_id")
CACHE_COLUMNS = ("source_file", "extraction_method", "row_count", "ingestion_timestamp")
AMOUNT_FIELDS = ("charge_amount", "amount_remaining", "credit_amount", "line_amount")


class RefusedError(Exception):
    """The statement can't be re-run in place; nothing was written."""


# ---------------------------------------------------------------------------
# IO -- every read and write the tool makes
# ---------------------------------------------------------------------------

class LiveIO:
    """Azure SQL (src/lakehouse/connection.py), Fabric Warehouse and
    Lakehouse SQL endpoint (src/lakehouse/fabric_sql.py), Lakehouse Delta
    files (deltalake) and the PDF archive (Blob Storage)."""

    def az_query(self, sql, params=()):
        from src.lakehouse.connection import execute_query
        return [dict(r) for r in execute_query(sql, list(params))]

    def az_exec(self, sql, params=()):
        from src.lakehouse.connection import execute_sql
        execute_sql(sql, list(params))

    def wh_query(self, sql, params=()):
        from src.lakehouse.fabric_sql import execute_warehouse_query
        return execute_warehouse_query(sql, list(params))

    def wh_restore(self, table, statement_id, rows):
        """One Warehouse transaction: delete the statement's rows, insert `rows`."""
        from src.lakehouse.fabric_sql import get_warehouse_connection, insert_rows
        conn = get_warehouse_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM {table} WHERE statement_id = ?", [statement_id])
            if rows:
                cols = list(rows[0])
                insert_rows(cur, table, cols, [[r[c] for c in cols] for r in rows])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def lh_query(self, sql, params=()):
        from src.lakehouse.fabric_sql import execute_lakehouse_query
        return execute_lakehouse_query(sql, list(params))

    def _delta(self, table):
        from deltalake import DeltaTable
        from src.lakehouse import bronze_unnest
        return DeltaTable(bronze_unnest._table_uri(table), storage_options=bronze_unnest._storage_options())

    def delta_read(self, table, statement_id):
        """(rows, table version) read straight from the Delta files -- the SQL
        endpoint truncates raw_payload at 8000 characters."""
        import pyarrow as pa
        from deltalake import QueryBuilder
        dt_ = self._delta(table)
        # DataFusion filters inside the engine; pyarrow's dataset-based
        # filters need a DLL some Windows policies block (_acero).
        escaped = statement_id.replace("'", "''")
        result = QueryBuilder().register("t", dt_).execute(f"SELECT * FROM t WHERE statement_id = '{escaped}'").read_all()
        return pa.table(result).to_pylist(), dt_.version()

    def delta_delete(self, table, statement_id):
        from src.lakehouse.fabric_dbt_runner import fabric_pipeline_lock
        escaped = statement_id.replace("'", "''")
        with fabric_pipeline_lock():
            self._delta(table).delete(predicate=f"statement_id = '{escaped}'")

    def delta_columns(self, table):
        return [f.name for f in self._delta(table).schema().to_arrow()]

    def delta_append(self, table, rows):
        import pyarrow as pa
        from deltalake import write_deltalake
        from src.lakehouse import bronze_unnest
        from src.lakehouse.fabric_dbt_runner import fabric_pipeline_lock
        if not rows:
            return
        schema = self._delta(table).schema().to_arrow()
        data = pa.Table.from_pylist(rows, schema=pa.schema(schema))
        with fabric_pipeline_lock():
            write_deltalake(bronze_unnest._table_uri(table), data, mode="append",
                            storage_options=bronze_unnest._storage_options())

    def download_pdf(self, blob_url, dest_dir):
        from urllib.parse import unquote, urlsplit
        from azure.storage.blob import BlobServiceClient
        u = urlsplit(blob_url)
        container, _, name = u.path.lstrip("/").partition("/")
        service = BlobServiceClient.from_connection_string(os.environ["AZURE_BLOB_CONNECTION_STRING"])
        data = service.get_container_client(container).download_blob(unquote(name)).readall()
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, os.path.basename(unquote(name)))
        with open(path, "wb") as f:
            f.write(data)
        return path


def load_intake():
    """notebooks/01_document_intake.py as a module (same as run_full_pipeline.py)."""
    path = os.path.join(PROJECT_ROOT, "notebooks", "01_document_intake.py")
    spec = importlib.util.spec_from_file_location("document_intake", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# State: every row this statement has in every table the re-run touches
# ---------------------------------------------------------------------------

def load_state(io, statement_id: str) -> dict:
    intake = io.az_query("SELECT * FROM document_intake_log WHERE statement_id = ?", [statement_id])
    doc_hash = intake[0].get("document_hash") if len(intake) == 1 else None
    state = {
        "statement_id": statement_id,
        "intake": intake,
        "azure": {t: io.az_query(f"SELECT * FROM {t} WHERE {w}", [statement_id])
                  for t, w in {**AZ_REPLACED, **AZ_APPENDED}.items()},
        "cache": io.az_query("SELECT * FROM extraction_cache WHERE document_hash = ? AND statement_id = ?",
                             [doc_hash, statement_id]) if doc_hash else [],
        "same_pdf": io.az_query("SELECT statement_id, ingestion_timestamp FROM document_intake_log "
                                "WHERE document_hash = ? AND statement_id <> ?", [doc_hash, statement_id]) if doc_hash else [],
        "jobs_in_flight": io.az_query("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('PENDING', 'PROCESSING')")[0]["n"],
        "lakehouse": {}, "lakehouse_versions": {},
        "warehouse": {t: io.wh_query(f"SELECT * FROM {t} WHERE statement_id = ?", [statement_id])
                      for t in SILVER_TABLES + RECON_TABLES},
    }
    for t in LAKEHOUSE_TABLES:
        state["lakehouse"][t], state["lakehouse_versions"][t] = io.delta_read(t, statement_id)
    ids = [r["statement_id"] for r in state["same_pdf"]]
    state["same_pdf_with_summary"] = sorted({r["statement_id"] for r in io.wh_query(
        f"SELECT statement_id FROM silver.recon_summary WHERE statement_id IN ({','.join('?' * len(ids))})", ids)}) if ids else []
    return state


def refusals(state: dict, *, dry_run: bool = False) -> list:
    """Reasons this statement must not be re-run now (empty list = OK).
    Jobs in flight refuse an apply; a dry run (reads only) reports them as a
    warning instead (warnings())."""
    out = []
    if len(state["intake"]) != 1:
        out.append(f"{len(state['intake'])} document_intake_log rows for this statement (expected exactly 1)")
    if state["jobs_in_flight"] and not dry_run:
        out.append(f"{state['jobs_in_flight']} job(s) in flight -- wait until none is PENDING/PROCESSING")
    closed = [e for e in state["warehouse"]["silver.recon_exceptions"]
              if (e.get("exception_status") or "OPEN") != "OPEN" or e.get("escalation_status")]
    if closed:
        out.append(f"{len(closed)} exception(s) not OPEN (resolved/escalated) -- re-matching would reset them")
    return out


def warnings(state: dict) -> list:
    """What a dry run reports but doesn't stop for."""
    if state["jobs_in_flight"]:
        return [f"{state['jobs_in_flight']} job(s) in flight -- --apply will refuse until none is PENDING/PROCESSING"]
    return []


# ---------------------------------------------------------------------------
# Re-extraction (offline -- no writes)
# ---------------------------------------------------------------------------

def _version_info(io, state, vendor_id, statement_period):
    """The statement's own stored version fields; for a statement with no
    Bronze rows yet, a read-only lookup -- never superseding another one."""
    rows = state["azure"]["bronze_vendor_statement_raw"]
    if rows:
        r = rows[0]
        return {"version_number": r.get("version_number") or 1,
                "previous_statement_id": r.get("previous_statement_id"),
                "is_latest_version": 1 if r.get("is_latest_version") in (None, 1, True) else 0}
    other = io.az_query(
        "SELECT statement_id FROM silver_reconciliation_standard WHERE vendor_id = ? AND statement_period = ? "
        "AND is_latest_version = 1 AND record_source = 'VENDOR_STATEMENT' AND statement_id <> ?",
        [vendor_id, statement_period, state["statement_id"]])
    return {"version_number": 1, "previous_statement_id": None, "is_latest_version": 0 if other else 1}


def _same_place(a, b) -> bool:
    """True when two billing locations differ only in case, punctuation or spacing."""
    def squash(s):
        return "".join(ch for ch in str(s or "").lower() if ch.isalnum())
    return bool(squash(a)) and squash(a) == squash(b)


def reextract(io, intake, state: dict, pdf_path: str) -> dict:
    """Runs the deterministic extractor and the intake's own validation on
    the archived PDF. Raises RefusedError for an AI route or 0 rows."""
    statement_id = state["statement_id"]
    row = state["intake"][0]
    if intake.compute_file_hash(pdf_path) != row["document_hash"]:
        raise RefusedError("the PDF's SHA-256 doesn't match document_intake_log.document_hash")
    route = intake._determine_extraction_route(pdf_path)
    if route["engine"] != "python_library":
        raise RefusedError(f"route is {route['engine']!r}, not a deterministic extractor -- this tool never calls AI")
    pdf_text, _ = intake.extract_pdf_text(pdf_path)
    schema_result = intake.PythonLibraryExtractionEngine().understand(pdf_text, pdf_path, statement_id=statement_id)
    invoices = schema_result.get("invoices") or []
    if not invoices:
        raise RefusedError("the deterministic extractor returned 0 rows (the intake would fall back to AI)")
    intake.apply_arithmetic_validation(schema_result, pdf_text, pdf_path)
    vendor_meta = schema_result.setdefault("vendor_metadata", {})
    vendor_meta["billing_location"], vendor_meta["billing_location_source"] = intake.resolve_billing_location(
        vendor_meta.get("billing_location"), vendor_meta.get("shop_or_entity"))
    if route.get("new_vendor_warning"):
        schema_result.setdefault("warnings", []).append(
            {"code": "NEW_VENDOR_TEXT_EMBEDDED", "message": route["new_vendor_warning"], "severity": "MEDIUM"})
    vendor_name = vendor_meta.get("vendor_name") or intake.derive_vendor_name_from_filename(pdf_path)
    vendor_meta["vendor_name"] = vendor_name
    vendor_id = intake.resolve_vendor_id(vendor_name) or vendor_name.upper().replace(" ", "_").replace(",", "")[:50]
    end = (schema_result.get("statement_metadata") or {}).get("statement_period_end") or ""
    statement_period = end[:7] if len(end) >= 7 else row.get("statement_period")
    with open(os.path.join(PROJECT_ROOT, "config", "validation", "extraction_rules.json")) as f:
        rules = json.load(f)
    valid, invalid, reasons, skipped = [], [], [], []
    for n, inv in enumerate(invoices, start=1):
        skip = intake.get_skip_reason(inv)
        if skip:
            skipped.append((inv, f"Row {n} skipped — {skip}"))
            continue
        ok, reason = intake.validate_invoice(inv, rules)
        if ok:
            valid.append(inv)
        else:
            invalid.append(inv)
            reasons.append(reason)
    doc_type = schema_result.get("document_metadata", {}).get("document_type", "UNKNOWN")
    values = intake.intake_log_values(row.get("document_id"), pdf_path, row["document_hash"], schema_result,
                                      statement_id, statement_period, len(valid),
                                      "RECONCILIATION" if doc_type == "VENDOR_STATEMENT" else "PARKED")
    # Same place, different formatting ("Mechanic Falls, ME" vs "MECHANIC
    # FALLS ME"): keep the stored value and its source, so the statement
    # still groups with the others; a genuinely different place updates.
    if row.get("billing_location") and _same_place(row["billing_location"], values["billing_location"]):
        values["billing_location"] = row["billing_location"]
        values["billing_location_source"] = row.get("billing_location_source")
    raw_fields = sorted({k for inv in invoices for k in (inv.get("_raw_row") or {})})
    return {
        "module": route.get("matched_vendor") or route.get("reason"),
        "pdf_text": pdf_text, "schema_result": schema_result, "invoices": invoices,
        "valid": valid, "invalid": invalid, "invalid_reasons": reasons, "skipped": skipped,
        "vendor_name": vendor_name, "vendor_id": vendor_id, "statement_period": statement_period,
        "version_info": _version_info(io, state, vendor_id, statement_period),
        "provider": schema_result.get("_provider_used", "unknown"),
        "intake_update": {k: v for k, v in values.items() if k not in INTAKE_KEPT},
        "raw_fields": raw_fields,
        "validation": schema_result.get("validation") or {},
    }


def silver_matching_decision(io, state: dict, new: dict) -> dict:
    """Whether Silver + matching run for this statement, and why."""
    mapped = io.wh_query(
        f"SELECT raw_field_name, canonical_field_name FROM silver.vendor_field_mapping WHERE vendor_id = ? "
        f"AND raw_field_name IN ({','.join('?' * len(new['raw_fields']))})", [new["vendor_id"], *new["raw_fields"]])
    if not any(m["canonical_field_name"] in AMOUNT_FIELDS for m in mapped):
        return {"run": False, "reason": f"no Fabric field mapping for vendor_id {new['vendor_id']!r} covers an amount field "
                                        f"of the extracted columns -- Silver + matching skipped"}
    if state["same_pdf"]:
        has_summary = bool(state["warehouse"]["silver.recon_summary"])
        others = state["same_pdf_with_summary"]
        if not has_summary and others:
            return {"run": False, "reason": f"the same PDF is stored as {', '.join(others)}, which is already matched -- "
                                            f"Silver + matching skipped for this copy"}
        if not has_summary:
            mine = str(state["intake"][0]["ingestion_timestamp"])
            earlier = [r["statement_id"] for r in state["same_pdf"] if str(r["ingestion_timestamp"]) < mine]
            if earlier:
                return {"run": False, "reason": f"no copy of this PDF is matched yet and {', '.join(earlier)} is the "
                                                f"earlier copy -- only that one gets Silver + matching"}
    return {"run": True, "reason": f"vendor {new['vendor_id']!r} has field mappings ({len(mapped)} of "
                                   f"{len(new['raw_fields'])} extracted columns)"}


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def _enc(v):
    if isinstance(v, decimal.Decimal):
        return {"__decimal__": str(v)}
    if isinstance(v, dt.datetime):
        return {"__datetime__": v.isoformat()}
    if isinstance(v, dt.date):
        return {"__date__": v.isoformat()}
    if isinstance(v, bytes):
        return {"__bytes__": v.hex()}
    return v


def _dec(v):
    if isinstance(v, dict) and len(v) == 1:
        (k, x), = v.items()
        if k == "__decimal__":
            return decimal.Decimal(x)
        if k == "__datetime__":
            return dt.datetime.fromisoformat(x)
        if k == "__date__":
            return dt.date.fromisoformat(x)
        if k == "__bytes__":
            return bytes.fromhex(x)
    return v


def _encode_rows(rows):
    return [{k: _enc(v) for k, v in r.items()} for r in rows]


def _decode_rows(rows):
    return [{k: _dec(v) for k, v in r.items()} for r in rows]


def fingerprint(state: dict) -> str:
    """Identifies the exact stored state a dry run was made from; apply()
    refuses if it changed since. The Delta table versions are left out --
    they move with every other statement's write -- the rows themselves
    are in."""
    snapshot = {k: v for k, v in state.items() if k not in ("jobs_in_flight", "lakehouse_versions")}
    blob = json.dumps(snapshot, default=lambda v: _enc(v) if _enc(v) is not v else str(v), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _same(a, b):
    if isinstance(a, (int, float, decimal.Decimal)) and isinstance(b, (int, float, decimal.Decimal)):
        return abs(float(a) - float(b)) < 1e-9
    return (None if a in ("", None) else str(a)) == (None if b in ("", None) else str(b))


def plan(state: dict, new: dict, decision: dict) -> dict:
    """From -> to for every table, without writing anything."""
    row = state["intake"][0]
    old_fields = sorted({(r["line_number"], r["raw_field_name"]) for r in state["lakehouse"]["unnested_statement_fields"]})
    new_field_count = sum(len(inv.get("_raw_row") or {}) for inv in new["invoices"])
    return {
        "statement_id": state["statement_id"],
        "fingerprint": fingerprint(state),
        "warnings": warnings(state),
        "jobs_in_flight": state["jobs_in_flight"],
        "validation": {"from": {k: row.get(f"validation_{k}") for k in ("status", "method", "difference")},
                       "to": {k: new["validation"].get(k) for k in ("status", "method", "difference")}},
        "document_intake_log (UPDATE, 1 row)": {k: {"from": row.get(k), "to": v} for k, v in new["intake_update"].items()
                                                if not _same(row.get(k), v)},
        "bronze_vendor_statement_raw (delete + insert)": {"from": len(state["azure"]["bronze_vendor_statement_raw"]),
                                                          "to": len(new["valid"])},
        "silver_reconciliation_standard (legacy; delete + insert)": {
            "from": len(state["azure"]["silver_reconciliation_standard"]), "to": len(new["valid"])},
        "validation_document_review_queue (insert)": {"existing": len(state["azure"]["validation_document_review_queue"]),
                                                      "added": len(new["invalid"])},
        "gold_exceptions + ai_audit_log (skipped rows; insert)": {"added": len(new["skipped"])},
        "extraction_cache (UPDATE own row)": (
            {"from": {c: state["cache"][0].get(c) for c in ("extraction_method", "row_count")},
             "to": {"extraction_method": new["provider"], "row_count": len(new["valid"])}}
            if state["cache"] else "no row for this statement -- untouched"),
        "bronze.raw_statement (Lakehouse; delete + write)": {"from": len(state["lakehouse"]["raw_statement"]), "to": 1},
        "bronze.raw_statement_staging (Lakehouse; leftovers deleted)": {
            "from": len(state["lakehouse"]["raw_statement_staging"]), "to": 0},
        "bronze.unnested_statement_lines (Lakehouse; delete + write)": {
            "from": len(state["lakehouse"]["unnested_statement_lines"]), "to": len(new["invoices"])},
        "bronze.unnested_statement_fields (Lakehouse; delete + write)": {
            "from": len(state["lakehouse"]["unnested_statement_fields"]), "to": new_field_count,
            "field names from": sorted({f for _, f in old_fields}), "field names to": new["raw_fields"]},
        "silver.statement + silver.statement_line (Warehouse)": (
            {"from": {t: len(state["warehouse"][t]) for t in SILVER_TABLES}, "to": "rebuilt from the new Bronze rows"}
            if decision["run"] else f"untouched -- {decision['reason']}"),
        "silver.recon_* (Warehouse; NetSuite matching)": (
            {"from": {t: len(state["warehouse"][t]) for t in RECON_TABLES},
             "to": "re-matched (deletes and re-inserts this statement's rows; all its exceptions are OPEN)"}
            if decision["run"] else f"untouched -- {decision['reason']}"),
        "version fields": new["version_info"],
        "silver_and_matching": decision,
        "vendor": {"from": row.get("vendor_name"), "to": new["vendor_name"], "vendor_id": new["vendor_id"]},
        "statement_period": {"from": row.get("statement_period"), "to": new["statement_period"]},
    }


# ---------------------------------------------------------------------------
# Backup, apply, undo
# ---------------------------------------------------------------------------

def backup(state: dict, dirs: list, the_plan: dict) -> list:
    """Writes the backup to every dir and reads each one back."""
    doc = {
        "what": "re-run in place backup -- every row of this statement in every table the re-run touches",
        "statement_id": state["statement_id"], "fingerprint": the_plan["fingerprint"],
        "taken_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "intake": _encode_rows(state["intake"]), "cache": _encode_rows(state["cache"]),
        "azure": {t: _encode_rows(r) for t, r in state["azure"].items()},
        "lakehouse": {t: _encode_rows(r) for t, r in state["lakehouse"].items()},
        "lakehouse_versions": state["lakehouse_versions"],
        "warehouse": {t: _encode_rows(r) for t, r in state["warehouse"].items()},
        "plan": json.loads(json.dumps(the_plan, default=str)),
    }
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    paths = []
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"rerun_backup_{state['statement_id']}_{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
        back = json.load(open(path, encoding="utf-8"))
        if back["fingerprint"] != doc["fingerprint"] or back["intake"] != doc["intake"] or \
                {t: len(r) for t, r in back["lakehouse"].items()} != {t: len(r) for t, r in state["lakehouse"].items()}:
            raise RuntimeError(f"backup read-back mismatch: {path}")
        paths.append(path)
    return paths


def _wait_exact_visibility(io, statement_id, expected_fields, timeout_seconds=300, poll=5.0) -> bool:
    """Until the Lakehouse SQL endpoint shows exactly the new field rows (not
    merely the same count -- the old rows could match that) and one raw row."""
    want = sorted((int(f["line_number"]), f["raw_field_name"], f["raw_field_value"]) for f in expected_fields)
    deadline = time.time() + timeout_seconds
    while True:
        try:
            got = sorted((int(r["line_number"]), r["raw_field_name"], r["raw_field_value"]) for r in io.lh_query(
                "SELECT line_number, raw_field_name, raw_field_value FROM bronze.unnested_statement_fields "
                "WHERE statement_id = ?", [statement_id]))
            raw = io.lh_query("SELECT COUNT(*) AS n FROM bronze.raw_statement WHERE statement_id = ?", [statement_id])[0]["n"]
            if got == want and raw == 1:
                return True
        except Exception:
            pass
        if time.time() >= deadline:
            return False
        time.sleep(poll)


def promote_raw(io, statement_id: str) -> int:
    """Moves this statement's staged raw row into bronze.raw_statement --
    the tool's own version of bronze_raw.promote_staged_raw_statement(),
    which reads the staging table through pyarrow.dataset (blocked by some
    Windows policies). Reads through io.delta_read() instead, refuses a
    staged row carrying a column bronze.raw_statement doesn't have (the
    shared code would schema-merge it), appends, then clears staging."""
    staged, _ = io.delta_read("raw_statement_staging", statement_id)
    if not staged:
        raise RefusedError("no staged raw_statement row to promote")
    extra = sorted({k for r in staged for k in r} - set(io.delta_columns("raw_statement")))
    if extra:
        raise RefusedError(f"the staged raw row has columns bronze.raw_statement doesn't: {extra}")
    io.delta_append("raw_statement", staged)
    io.delta_delete("raw_statement_staging", statement_id)
    return len(staged)


def _lakehouse_problems(io, statement_id, expected_lines: int, expected_fields: int) -> list:
    """What's wrong with the statement's Lakehouse Bronze rows (empty = landed)."""
    counts = {t: len(io.delta_read(t, statement_id)[0]) for t in LAKEHOUSE_TABLES}
    want = {"raw_statement": 1, "raw_statement_staging": 0,
            "unnested_statement_lines": expected_lines, "unnested_statement_fields": expected_fields}
    return [f"bronze.{t}: {counts[t]} row(s), expected {n}" for t, n in want.items() if counts[t] != n]


def apply(io, intake, state: dict, new: dict, decision: dict, *, expected_fingerprint: str,
          backup_paths: list, fresh_state: Optional[dict] = None) -> dict:
    """Writes the re-run. Refuses unless the state still has the dry run's
    fingerprint, nothing is refused, and a backup was written."""
    fresh = fresh_state if fresh_state is not None else load_state(io, state["statement_id"])
    if fingerprint(fresh) != expected_fingerprint:
        raise RefusedError("the stored state changed since the dry run -- run the dry run again")
    problems = refusals(fresh)
    if problems:
        raise RefusedError("; ".join(problems))
    if not backup_paths or not all(os.path.exists(p) for p in backup_paths):
        raise RefusedError("no backup on disk -- refusing to write")
    sid = state["statement_id"]
    source_file = os.path.basename(state["intake"][0]["source_file"] or f"{sid}.pdf")
    from src.lakehouse.bronze_raw import write_raw_statement
    from src.lakehouse.bronze_unnest import _explode, write_unnested_from_invoices
    result = {"statement_id": sid}

    # 1. Lakehouse Bronze: delete the old rows first, then write the new ones.
    #    If they don't all land, stop HERE -- before any Azure SQL write
    #    (undo restores the Lakehouse from the backup).
    stop = "-- stopped before any Azure SQL write; restore with --undo <backup>"
    for t in LAKEHOUSE_TABLES:
        io.delta_delete(t, sid)
    write_raw_statement(new["invoices"], new["vendor_id"], sid, source_file, new["provider"],
                        vendor_display_name=intake.display_name(new["vendor_name"]),
                        version_number=new["version_info"]["version_number"])
    try:
        result["raw_promoted"] = promote_raw(io, sid)
    except Exception as e:
        raise RefusedError(f"promoting the raw row failed ({type(e).__name__}: {str(e)[:200]}) {stop}") from e
    result["lines_written"], result["fields_written"] = write_unnested_from_invoices(new["invoices"], sid)
    expected_lines, expected_fields = _explode([{"_raw_row": inv.get("_raw_row")} for inv in new["invoices"]], sid)
    problems = _lakehouse_problems(io, sid, len(expected_lines), len(expected_fields))
    if problems:
        raise RefusedError(f"Lakehouse Bronze didn't land ({'; '.join(problems)}) {stop}")
    from src.lakehouse.bronze_raw import _refresh_sql_endpoint_metadata
    _refresh_sql_endpoint_metadata()

    # 2. Azure SQL, exactly as the intake writes it -- except the intake row
    #    (UPDATE) and the cache (UPDATE of an existing row only).
    for inv, message in new["skipped"]:
        intake.log_row_skip(sid, source_file, message)
        intake.write_skip_exception(sid, new["vendor_id"], source_file, new["statement_period"], inv, message)
    result["bronze_count"] = intake.write_to_bronze(new["valid"], new["schema_result"], sid, source_file,
                                                    new["statement_period"], new["vendor_id"], new["version_info"])
    if new["invalid"]:
        intake.write_to_review_queue(new["invalid"], new["invalid_reasons"], sid, source_file, "AI_EXTRACTION")
    result["legacy_silver_count"] = intake.normalize_to_silver(sid, sid, new["vendor_id"], new["version_info"])
    cols = list(new["intake_update"])
    io.az_exec(f"UPDATE document_intake_log SET {', '.join(c + ' = ?' for c in cols)} WHERE statement_id = ?",
               [new["intake_update"][c] for c in cols] + [sid])
    if state["cache"]:
        intake.update_cache(state["intake"][0]["document_hash"], sid, source_file, new["provider"], result["bronze_count"])

    # 3. Silver + NetSuite matching, when decided.
    result["silver_and_matching"] = decision["reason"]
    if decision["run"]:
        _silver_and_matching(io, sid, expected_fields, result)
    return result


def _silver_and_matching(io, sid, expected_fields, result: dict) -> dict:
    """Waits until the SQL endpoint shows exactly expected_fields, re-checks
    that every exception is still OPEN, then builds Silver and re-matches."""
    if not _wait_exact_visibility(io, sid, expected_fields):
        result["silver_built"] = False
        result["silver_and_matching"] = "NOT RUN: the new Bronze rows weren't visible in the SQL endpoint in time"
        return result
    if refusals(load_state(io, sid)):
        raise RefusedError("an exception changed status (or a job started) during the re-run -- matching not run")
    from src.lakehouse.silver_build import build_silver_direct
    from src.matching.fabric_matching import run_fabric_matching
    result["silver_built"] = build_silver_direct(sid)
    if result["silver_built"]:
        result["matching"] = run_fabric_matching(sid)
    return result


def _rows_key(rows):
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)


def resume_problems(state: dict, backup_doc: dict) -> list:
    """Why a half-applied statement (Azure SQL written, raw row stuck in
    staging, Silver/matching not run) can NOT be resumed from backup_doc."""
    the_plan, out = backup_doc["plan"], []
    if state["statement_id"] != backup_doc["statement_id"]:
        return [f"backup is for {backup_doc['statement_id']}, not {state['statement_id']}"]
    if not the_plan["silver_and_matching"]["run"]:
        out.append("the plan never ran Silver + matching for this statement -- nothing to resume")
    if len(state["intake"]) != 1:
        return out + [f"{len(state['intake'])} document_intake_log rows (expected 1)"]
    row = state["intake"][0]
    for col, change in the_plan["document_intake_log (UPDATE, 1 row)"].items():
        if not _same(row.get(col), change["to"]):
            out.append(f"document_intake_log.{col} is {row.get(col)!r}, not the planned {change['to']!r}")
    for table, key in (("bronze_vendor_statement_raw", "bronze_vendor_statement_raw (delete + insert)"),
                       ("silver_reconciliation_standard", "silver_reconciliation_standard (legacy; delete + insert)")):
        if len(state["azure"][table]) != the_plan[key]["to"]:
            out.append(f"{table}: {len(state['azure'][table])} rows, planned {the_plan[key]['to']}")
    lake = state["lakehouse"]
    if len(lake["raw_statement_staging"]) != 1 or lake["raw_statement"]:
        out.append(f"expected the new raw row in staging only: raw_statement {len(lake['raw_statement'])}, "
                   f"staging {len(lake['raw_statement_staging'])}")
    lines_plan = the_plan["bronze.unnested_statement_lines (Lakehouse; delete + write)"]["to"]
    fields_plan = the_plan["bronze.unnested_statement_fields (Lakehouse; delete + write)"]
    if len(lake["unnested_statement_lines"]) != lines_plan:
        out.append(f"bronze.unnested_statement_lines: {len(lake['unnested_statement_lines'])} rows, planned {lines_plan}")
    if len(lake["unnested_statement_fields"]) != fields_plan["to"] or \
            sorted({r["raw_field_name"] for r in lake["unnested_statement_fields"]}) != fields_plan["field names to"]:
        out.append("bronze.unnested_statement_fields aren't the planned new rows")
    for t in SILVER_TABLES + RECON_TABLES:
        if _rows_key(_encode_rows(state["warehouse"][t])) != _rows_key(backup_doc["warehouse"][t]):
            out.append(f"{t} changed since the backup")
    return out


def resume(io, backup_doc: dict, *, apply_changes: bool = False, expected_fingerprint: str = None) -> dict:
    """Finishes a half-applied statement: promote its staged raw row, wait
    for exact visibility, build Silver, re-match. Dry run unless
    apply_changes; refuses unless every resume_problems() check passes."""
    sid = backup_doc["statement_id"]
    state = load_state(io, sid)
    problems = refusals(state, dry_run=not apply_changes) + resume_problems(state, backup_doc)
    if problems:
        raise RefusedError("; ".join(problems))
    fp = fingerprint(state)
    steps = ["promote the staged raw row into bronze.raw_statement", "wait until the SQL endpoint shows exactly the new fields",
             "build Silver (silver.statement + statement_line)", "re-run NetSuite matching (silver.recon_*)"]
    if not apply_changes:
        return {"dry_run": True, "statement_id": sid, "fingerprint": fp, "checks": "all passed", "steps": steps,
                "warnings": warnings(state), "jobs_in_flight": state["jobs_in_flight"],
                "now": {"raw_statement": len(state["lakehouse"]["raw_statement"]),
                        "raw_statement_staging": len(state["lakehouse"]["raw_statement_staging"]),
                        **{t: len(state["warehouse"][t]) for t in SILVER_TABLES + RECON_TABLES}}}
    if fp != expected_fingerprint:
        raise RefusedError("the stored state changed since the resume dry run -- run it again")
    result = {"statement_id": sid, "resumed": True, "raw_promoted": promote_raw(io, sid)}
    expected_fields = state["lakehouse"]["unnested_statement_fields"]
    lines = len(state["lakehouse"]["unnested_statement_lines"])
    problems = _lakehouse_problems(io, sid, lines, len(expected_fields))
    if problems:
        raise RefusedError(f"the raw row didn't land ({'; '.join(problems)}) -- Silver + matching not run")
    from src.lakehouse.bronze_raw import _refresh_sql_endpoint_metadata
    _refresh_sql_endpoint_metadata()
    result["silver_and_matching"] = backup_doc["plan"]["silver_and_matching"]["reason"]
    return _silver_and_matching(io, sid, expected_fields, result)


def undo(io, backup_doc: dict, *, apply_changes: bool = False) -> dict:
    """Restores every table to the backup. Dry run unless apply_changes."""
    sid = backup_doc["statement_id"]
    now = load_state(io, sid)
    steps = {}
    for t in SILVER_TABLES + RECON_TABLES:
        steps[t] = {"now": len(now["warehouse"][t]), "restore": len(backup_doc["warehouse"][t])}
    for t in LAKEHOUSE_TABLES:
        steps[f"bronze.{t}"] = {"now": len(now["lakehouse"][t]), "restore": len(backup_doc["lakehouse"][t])}
    for t in AZ_REPLACED:
        steps[t] = {"now": len(now["azure"][t]), "restore": len(backup_doc["azure"][t])}
    for t in AZ_APPENDED:
        kept = {r["id"] for r in backup_doc["azure"][t]}
        steps[t] = {"remove_added": len([r for r in now["azure"][t] if r["id"] not in kept])}
    steps["document_intake_log"] = "UPDATE back to the backed-up values (1 row)"
    steps["extraction_cache"] = "UPDATE back" if backup_doc["cache"] else "untouched"
    if not apply_changes:
        return {"dry_run": True, "steps": steps}
    for t in SILVER_TABLES + RECON_TABLES:
        io.wh_restore(t, sid, _decode_rows(backup_doc["warehouse"][t]))
    for t in LAKEHOUSE_TABLES:
        io.delta_delete(t, sid)
        io.delta_append(t, _decode_rows(backup_doc["lakehouse"][t]))
    for t, where in AZ_REPLACED.items():
        io.az_exec(f"DELETE FROM {t} WHERE {where}", [sid])
        for r in _decode_rows(backup_doc["azure"][t]):
            cols = [c for c in r if c != "id"]
            io.az_exec(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [r[c] for c in cols])
    for t in AZ_APPENDED:
        kept = {r["id"] for r in backup_doc["azure"][t]}
        for r in now["azure"][t]:
            if r["id"] not in kept:
                io.az_exec(f"DELETE FROM {t} WHERE id = ?", [r["id"]])
    old = _decode_rows(backup_doc["intake"])[0]
    cols = [c for c in old if c not in ("id",) + INTAKE_KEPT]
    io.az_exec(f"UPDATE document_intake_log SET {', '.join(c + ' = ?' for c in cols)} WHERE statement_id = ?",
               [old[c] for c in cols] + [sid])
    for c in _decode_rows(backup_doc["cache"]):
        io.az_exec(f"UPDATE extraction_cache SET {', '.join(x + ' = ?' for x in CACHE_COLUMNS)} WHERE id = ?",
                   [c[x] for x in CACHE_COLUMNS] + [c["id"]])
    return {"dry_run": False, "steps": steps}
