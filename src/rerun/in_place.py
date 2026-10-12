"""
src/rerun/in_place.py

Re-runs ONE stored statement in place with a deterministic (python-library)
extractor -- no AI -- keeping its statement_id (2026-10-07). An explicit AI
mode (--allow-ai, one statement at a time, extract-only -> dry run from the
saved file -> apply; see "AI mode" at the end) was added 2026-10-12. For stored
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


# Lakehouse Delta reads/writes go to OneLake, which fails transiently now and
# then (2026-10-07: "Generic MicrosoftAzure error: Error performing GET
# .../_delta_log/...checkpoint" stopped a batch). Those are retried; a
# refusal, a schema/protocol problem or a programming error never is. A
# retried append that had in fact committed would leave a duplicate -- the
# post-write count check (_lakehouse_problems) then stops before Azure SQL.
DELTA_ATTEMPTS = 3
DELTA_RETRY_WAITS = (5, 15)


def _transient(e: Exception) -> bool:
    """OneLake/Delta I/O failures only -- so never a RefusedError or a programming error."""
    try:
        from deltalake.exceptions import DeltaError, DeltaProtocolError, SchemaMismatchError, TableNotFoundError
    except ImportError:  # pragma: no cover
        return isinstance(e, (OSError, TimeoutError, ConnectionError))
    if isinstance(e, (DeltaProtocolError, SchemaMismatchError, TableNotFoundError)):
        return False
    return isinstance(e, (DeltaError, OSError, TimeoutError, ConnectionError))


def _retried(fn):
    """Retries fn on transient OneLake/Delta errors (see _transient)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(1, DELTA_ATTEMPTS + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                if attempt == DELTA_ATTEMPTS or not _transient(e):
                    raise
                print(f"    {fn.__name__}: transient {type(e).__name__} (attempt {attempt}/{DELTA_ATTEMPTS}) "
                      f"-- retrying in {DELTA_RETRY_WAITS[attempt - 1]}s: {str(e)[:160]}", flush=True)
                time.sleep(DELTA_RETRY_WAITS[attempt - 1])
    return wrapper


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

    @_retried
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

    @_retried
    def delta_delete(self, table, statement_id):
        from src.lakehouse.fabric_dbt_runner import fabric_pipeline_lock
        escaped = statement_id.replace("'", "''")
        with fabric_pipeline_lock():
            self._delta(table).delete(predicate=f"statement_id = '{escaped}'")

    @_retried
    def delta_columns(self, table):
        return [f.name for f in self._delta(table).schema().to_arrow()]

    @_retried
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
    if not (schema_result.get("invoices") or []):
        raise RefusedError("the deterministic extractor returned 0 rows (the intake would fall back to AI)")
    return new_from_schema(io, intake, state, pdf_path, pdf_text, schema_result, route)


def new_from_schema(io, intake, state: dict, pdf_path: str, pdf_text: str, schema_result: dict, route: dict) -> dict:
    """Everything the intake does between extraction and the writes --
    validation (the current gate), billing location, vendor, period, the
    skip/valid/invalid split -- for a schema_result from either route (the
    deterministic extractor, or an AI extraction saved by extract_only())."""
    statement_id = state["statement_id"]
    row = state["intake"][0]
    invoices = schema_result.get("invoices") or []
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
        "fingerprint": (ai_fingerprint(state, new["ai_extraction"]["sha256"]) if new.get("ai_extraction")
                        else fingerprint(state)),
        "ai_extraction": new.get("ai_extraction"),
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
    ai = new.get("ai_extraction")
    current = ai_fingerprint(fresh, ai["sha256"]) if ai else fingerprint(fresh)
    if current != expected_fingerprint:
        raise RefusedError("the stored state (or the saved AI extraction) changed since the dry run -- "
                           "run the dry run again")
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
    if ai:
        write_ai_audit(sid, new)
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


# ---------------------------------------------------------------------------
# AI mode (2026-10-12): --allow-ai, one statement at a time, in three steps
# ---------------------------------------------------------------------------
#
#   1. extract_only(): the normal intake extraction route (the Document
#      Understanding Engine with the upload planner) on the statement's
#      hash-checked PDF. Writes NOTHING to any database -- every DB entry
#      point raises while it runs, and the engine's ai_audit_log row is
#      captured instead (written on apply). Saves the full schema_result, the
#      upload plan, the token usage of every API response and its cost to a
#      local JSON file, and adds the cost to the task's ledger.
#   2. the dry run reads that file (never calls the AI again), runs the
#      current gate and skip rules via new_from_schema(), and prints the usual
#      plan; the fingerprint includes the file's SHA-256.
#   3. apply uses the same file and the existing backup/undo machinery.

AI_INPUT_USD_PER_MTOK = 3.00     # Claude Sonnet 4.6 (Foundry bills at the standard API rates)
AI_OUTPUT_USD_PER_MTOK = 15.00
AI_TASK_COST_CAP_USD = 3.00
# Pre-run estimate only (refuses before spending). The real usage comes from
# each API response and is what the ledger records.
AI_EST_INPUT_TOKENS_PER_PAGE = 1600
AI_EST_OUTPUT_TOKENS_PER_PAGE = 2500
AI_EST_PROMPT_TOKENS = 3900      # EXTRACTION_PROMPT, ~15.6k characters, sent once per request part
AI_LEDGER_NAME = "ai_cost_ledger.json"


def ai_cost_usd(usage: list) -> float:
    """Cost of a list of API usage dicts (input_tokens / output_tokens)."""
    tokens_in = sum(int(u.get("input_tokens") or 0) for u in usage)
    tokens_out = sum(int(u.get("output_tokens") or 0) for u in usage)
    return round(tokens_in / 1e6 * AI_INPUT_USD_PER_MTOK + tokens_out / 1e6 * AI_OUTPUT_USD_PER_MTOK, 4)


def estimate_ai_cost(plan) -> dict:
    pages = plan.pages
    tokens_in = pages * AI_EST_INPUT_TOKENS_PER_PAGE + len(plan.parts) * AI_EST_PROMPT_TOKENS
    tokens_out = pages * AI_EST_OUTPUT_TOKENS_PER_PAGE
    usd = round(tokens_in / 1e6 * AI_INPUT_USD_PER_MTOK + tokens_out / 1e6 * AI_OUTPUT_USD_PER_MTOK, 4)
    return {"pages": pages, "requests": len(plan.parts), "input_tokens": tokens_in, "output_tokens": tokens_out,
            "usd": usd}


def read_ledger(path: str) -> dict:
    if not os.path.exists(path):
        return {"cap_usd": AI_TASK_COST_CAP_USD, "runs": [], "total_usd": 0.0}
    return json.load(open(path, encoding="utf-8"))


def _write_ledger(path: str, ledger: dict) -> None:
    ledger["total_usd"] = round(sum(r["usd"] for r in ledger["runs"]), 4)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=1)


class _NoDatabase:
    """While active, every database entry point raises: execute_sql /
    execute_query / execute_query_fabric / recon_query in every loaded module,
    pyodbc.connect and sqlite3.connect. The engine's log_ai_call is replaced
    by a recorder (its row is written on apply)."""

    NAMES = ("execute_sql", "execute_query", "execute_query_fabric", "recon_query")

    def __init__(self):
        self.audit = []
        self._undo = []

    @staticmethod
    def _blocked(*_a, **_k):
        raise RuntimeError("database access blocked during --extract-only")

    def _patch(self, owner, name, value):
        self._undo.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def __enter__(self):
        import sqlite3
        import sys
        for module in list(sys.modules.values()):
            for name in self.NAMES:
                if module is not None and callable(getattr(module, name, None)):
                    self._patch(module, name, self._blocked)
        try:
            import pyodbc
            self._patch(pyodbc, "connect", self._blocked)
        except ImportError:
            pass
        self._patch(sqlite3, "connect", self._blocked)
        from src.ai import document_understanding_engine as engine

        def record(response, **kwargs):
            self.audit.append({"response": response, "kwargs": kwargs})
            return "not-written"
        self._patch(engine, "log_ai_call", record)
        return self

    def __exit__(self, *exc):
        for owner, name, value in reversed(self._undo):
            setattr(owner, name, value)
        return False


def extract_only(intake, statement_id: str, pdf_path: str, expected_sha256: str, out_dir: str,
                 ledger_path: Optional[str] = None, cap_usd: float = AI_TASK_COST_CAP_USD) -> dict:
    """Step 1 of AI mode (see above). Returns {"path", "sha256", "cost_usd",
    "ledger_total_usd", ...}. Refuses (RefusedError) on a hash mismatch, a
    deterministic route, a cost estimate that would take the ledger over the
    cap, or an AI failure (a pdfplumber fallback is never saved)."""
    from src.ai import upload_preprocess
    if not statement_id:
        raise RefusedError("--allow-ai needs an explicit --statement-id (one statement at a time)")
    if intake.compute_file_hash(pdf_path) != expected_sha256:
        raise RefusedError("the PDF's SHA-256 doesn't match the statement's document_hash")
    ledger_path = ledger_path or os.path.join(out_dir, AI_LEDGER_NAME)
    ledger = read_ledger(ledger_path)
    plan = upload_preprocess.plan_upload(pdf_path)
    estimate = estimate_ai_cost(plan)
    if ledger["total_usd"] + estimate["usd"] > cap_usd:
        raise RefusedError(f"cost cap: ${ledger['total_usd']:.2f} spent + ${estimate['usd']:.2f} estimated "
                           f"> ${cap_usd:.2f} for this task")
    started = dt.datetime.now(dt.timezone.utc)
    with _NoDatabase() as guard:
        pdf_text, _ = intake.extract_pdf_text(pdf_path)
        route = intake._determine_extraction_route(pdf_path)
        if route["engine"] == "python_library":
            raise RefusedError("this PDF routes to a deterministic extractor -- use the normal (no-AI) re-run")
        schema_result = intake.DocumentUnderstandingEngine().understand(pdf_text, pdf_path, statement_id=statement_id)
    responses = [a["response"] for a in guard.audit]
    usage = [u for r in responses for u in ((r.raw_response or {}).get("usage") or [])] if responses else []
    cost = ai_cost_usd(usage)
    ledger["runs"].append({"statement_id": statement_id, "at_utc": started.isoformat(timespec="seconds"),
                           "usd": cost, "requests": len(usage), "estimate_usd": estimate["usd"]})
    _write_ledger(ledger_path, ledger)
    if schema_result.get("_provider_used") != "claude_sonnet":
        raise RefusedError(f"the AI extraction failed ({responses[-1].error if responses else 'no response'}) -- "
                           f"the engine fell back to {schema_result.get('_provider_used')}; nothing saved "
                           f"(cost ${cost:.4f} recorded)")
    last = responses[-1]
    doc = {
        "what": "AI re-extraction saved by scripts/rerun_in_place.py --allow-ai --extract-only; no database was written",
        "statement_id": statement_id, "document_hash": expected_sha256, "pdf": os.path.basename(pdf_path),
        "extracted_at_utc": started.isoformat(timespec="seconds"),
        "route": {k: route.get(k) for k in ("engine", "pdf_type", "reason", "matched_vendor", "new_vendor_warning")},
        "upload_plan": (last.raw_response or {}).get("upload_plan") or {"path": plan.path, "describe": plan.describe()},
        "usage": usage, "cost_usd": cost, "estimate": estimate,
        "ai_audit": {"provider": last.provider, "model": last.model, "latency_ms": last.latency_ms,
                     "attempt_count": last.attempt_count, "success": last.success,
                     "kwargs": {k: v for k, v in guard.audit[-1]["kwargs"].items()}},
        "schema_result": schema_result,
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"ai_extraction_{statement_id}_{started.strftime('%Y%m%dT%H%M%SZ')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, default=str)
    return {"path": path, "sha256": file_sha256(path), "cost_usd": cost, "ledger_total_usd": read_ledger(ledger_path)["total_usd"],
            "rows": len(schema_result.get("invoices") or []), "upload_plan": doc["upload_plan"]}


def file_sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_extraction(path: str, state: dict) -> dict:
    """The saved AI extraction for this statement, checked against the stored
    state: same statement_id and the same document_hash."""
    if not path or not os.path.exists(path):
        raise RefusedError("no saved AI extraction file -- run --allow-ai --extract-only first")
    doc = json.load(open(path, encoding="utf-8"))
    if doc.get("statement_id") != state["statement_id"]:
        raise RefusedError(f"the extraction file is for {doc.get('statement_id')}, not {state['statement_id']}")
    if doc.get("document_hash") != state["intake"][0]["document_hash"]:
        raise RefusedError("the extraction file's document_hash doesn't match the statement's")
    doc["_sha256"] = file_sha256(path)
    return doc


def new_from_extraction(io, intake, state: dict, pdf_path: str, doc: dict) -> dict:
    """Step 2/3: the saved extraction through the current gate and skip rules
    (new_from_schema), never calling the AI. Works on a deep copy, so the
    plan is the same every time it is built from the same file."""
    import copy
    if intake.compute_file_hash(pdf_path) != state["intake"][0]["document_hash"]:
        raise RefusedError("the PDF's SHA-256 doesn't match document_intake_log.document_hash")
    pdf_text, _ = intake.extract_pdf_text(pdf_path)
    route = dict(doc.get("route") or {})
    new = new_from_schema(io, intake, state, pdf_path, pdf_text, copy.deepcopy(doc["schema_result"]), route)
    new["ai_extraction"] = {"sha256": doc["_sha256"], "cost_usd": doc.get("cost_usd"),
                            "upload_plan": doc.get("upload_plan"), "ai_audit": doc.get("ai_audit")}
    return new


def ai_fingerprint(state: dict, extraction_sha256: str) -> str:
    """The dry run's fingerprint for an AI re-run: the stored state AND the
    exact saved extraction file."""
    return hashlib.sha256(f"{fingerprint(state)}:{extraction_sha256}".encode()).hexdigest()[:16]


def write_ai_audit(sid: str, new: dict) -> None:
    """The ai_audit_log row extract_only() held back, written on apply."""
    from src.ai.audit_logger import log_ai_call
    from src.ai.base_client import AIResponse
    a = (new.get("ai_extraction") or {}).get("ai_audit") or {}
    response = AIResponse(success=bool(a.get("success")), provider=a.get("provider") or "claude_sonnet",
                          model=a.get("model") or "", latency_ms=float(a.get("latency_ms") or 0.0),
                          attempt_count=int(a.get("attempt_count") or 1))
    kwargs = dict(a.get("kwargs") or {})
    kwargs["statement_id"] = sid
    kwargs.setdefault("interaction_type", "DOCUMENT_UNDERSTANDING")
    log_ai_call(response, **kwargs)
