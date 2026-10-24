"""
src/rerun/revalidate.py

Re-validation of stored statements whose rows stay as they are (2026-10-12;
the same pattern as the 2026-10-06 "Option A", scratchpad/
oct1_revalidation_*_20261006.*): recomputes ONLY the seven
document_intake_log validation columns with the current gate, from the
statement's stored extraction rows and its hash-checked local PDF. Nothing
else is read for writing and nothing else is written. Driven by
scripts/revalidate_intake.py.

  plan()    reads, recomputes, writes nothing; the plan carries every row's
            old and new values and a fingerprint of the old values.
  backup()  backup .json + undo .sql + undo .py, written and read back
            before anything is written.
  apply()   re-reads the rows, refuses unless the fingerprint still matches,
            then UPDATEs every row in ONE transaction -- each UPDATE guarded
            on the old values and required to hit exactly 1 row, rolled back
            otherwise -- and re-reads to verify.

The stored rows are the statement's full extraction output -- the
Lakehouse bronze.raw_statement payload, i.e. exactly what the intake's own
validation saw (Azure SQL Bronze can lack skipped rows). A statement with
no stored rows becomes "not_a_statement" only when its own job output shows
the model returned no table at all ("Columns found: []" on a successful
call -- the rule ClaudeSonnetClient applies since 2026-10-06); otherwise it
is left unchanged and the plan says why.
"""

import datetime as dt
import hashlib
import json
import os
import re
from typing import Optional

COLUMNS = ("validation_status", "validation_difference", "validation_method", "validation_detail",
           "previous_balance", "previous_balance_source", "section_totals")
_NO_TABLE_RE = re.compile(r"\[ClaudeSonnetClient\] Columns found: \[\]")
_SUCCESS_ZERO_RE = re.compile(r"ClaudeSonnetClient success \S+ 0 invoices extracted")


class RefusedError(Exception):
    """Nothing was written."""


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _unwrap(element):
    """One raw_payload element -> the extracted row. src/lakehouse/bronze_raw.py
    stores each row wrapped as {"_raw_row": <the model's row>,
    "_extraction_confidence", "_shop_name"}; a plain row is accepted as is."""
    if isinstance(element, dict) and "_raw_row" in element:
        return element["_raw_row"]
    return element


def load_target(io, statement_id: str) -> dict:
    """The intake row (exactly one), the stored extraction rows and the job
    output for one statement -- reads only."""
    intake = io.az_query("SELECT * FROM document_intake_log WHERE statement_id = ?", [statement_id])
    if len(intake) != 1:
        raise RefusedError(f"{statement_id}: {len(intake)} document_intake_log rows (expected exactly 1)")
    raw, _ = io.delta_read("raw_statement", statement_id)
    rows = []
    for r in raw:
        payload = r.get("raw_payload")
        rows += [_unwrap(e) for e in (json.loads(payload) if isinstance(payload, str) else (payload or []))]
    jobs = io.az_query("SELECT job_id, status, error_message FROM jobs WHERE statement_id = ?", [statement_id])
    return {"statement_id": statement_id, "intake": intake[0], "rows": [r for r in rows if r is not None],
            "raw_statement_rows": len(raw), "jobs": jobs}


def _invoices(target: dict) -> list:
    row = target["intake"]
    if not target["rows"]:
        return []
    if (row.get("extraction_method") or "") != "claude_sonnet":
        raise RefusedError(f"{target['statement_id']}: extraction_method {row.get('extraction_method')!r} -- only "
                           f"AI-extracted rows are rebuilt by this tool")
    from src.ai.claude_sonnet_client import ClaudeSonnetClient
    columns = [k for k in target["rows"][0] if k != "confidence"]
    for r in target["rows"][1:]:
        columns += [k for k in r if k != "confidence" and k not in columns]
    client = ClaudeSonnetClient.__new__(ClaudeSonnetClient)
    return client._rows_to_invoices([dict(r) for r in target["rows"]], columns)[0]


def no_table_evidence(target: dict) -> Optional[str]:
    """The job output line that shows the model found no table, or None."""
    for job in target["jobs"]:
        out = job.get("error_message") or ""
        if _NO_TABLE_RE.search(out) and _SUCCESS_ZERO_RE.search(out):
            return f"job {job['job_id']}: '[ClaudeSonnetClient] Columns found: []' + 'success -- 0 invoices extracted'"
    return None


def recompute(intake_module, target: dict, pdf_path: str) -> dict:
    """New values of the seven columns (same serialisation as
    intake_log_values()), or {"unchanged": reason}."""
    from src.validation.arithmetic_gate import compute_statement_total_from_invoices
    row = target["intake"]
    if _sha256(pdf_path) != row["document_hash"]:
        raise RefusedError(f"{target['statement_id']}: the PDF's SHA-256 doesn't match document_hash")
    invoices = _invoices(target)
    if not invoices:
        evidence = no_table_evidence(target)
        if not evidence:
            return {"unchanged": "no stored rows and no job output showing the model found no table"}
        return {"validation_status": "not_a_statement", "validation_difference": None, "validation_method": None,
                "validation_detail": json.dumps({"not_a_statement_evidence": evidence}),
                "previous_balance": row.get("previous_balance"), "previous_balance_source": row.get("previous_balance_source"),
                "section_totals": row.get("section_totals")}
    schema_result = {
        "document_metadata": {"document_type": row.get("document_type") or "VENDOR_STATEMENT"},
        "vendor_metadata": {"vendor_name": row.get("vendor_name")},
        "statement_metadata": {"statement_total_as_printed": row.get("statement_total_as_printed"),
                               "statement_total_computed": compute_statement_total_from_invoices(invoices)},
        "invoices": invoices,
    }
    pdf_text, _ = intake_module.extract_pdf_text(pdf_path)
    v = intake_module.apply_arithmetic_validation(schema_result, pdf_text, pdf_path)
    stmt = schema_result["statement_metadata"]
    return {"validation_status": v.get("status"), "validation_difference": v.get("difference"),
            "validation_method": v.get("method"),
            "validation_detail": json.dumps(v["detail"]) if v.get("detail") is not None else None,
            "previous_balance": stmt.get("previous_balance"), "previous_balance_source": stmt.get("previous_balance_source"),
            "section_totals": json.dumps(stmt["section_totals"]) if stmt.get("section_totals") else None}


def _old(row: dict) -> dict:
    return {c: row.get(c) for c in COLUMNS}


def fingerprint(rows: list) -> str:
    """Of the old values (and identity) of every row in the plan."""
    blob = json.dumps([[r["statement_id"], str(r["ingestion_timestamp"]), r["document_hash"], r["old"]] for r in rows],
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def plan(io, intake_module, statement_ids: list, pdfs: dict) -> dict:
    """Dry run: reads only."""
    rows, unchanged = [], []
    for sid in statement_ids:
        if sid not in pdfs:
            raise RefusedError(f"{sid}: no local PDF given")
        target = load_target(io, sid)
        new = recompute(intake_module, target, pdfs[sid])
        if "unchanged" in new:
            unchanged.append({"statement_id": sid, "reason": new["unchanged"]})
            continue
        old = _old(target["intake"])
        changed = [c for c in COLUMNS if str(old[c]) != str(new[c])]
        if not changed:
            unchanged.append({"statement_id": sid, "reason": "the current gate gives the stored values"})
            continue
        rows.append({"statement_id": sid, "ingestion_timestamp": str(target["intake"]["ingestion_timestamp"]),
                     "document_hash": target["intake"]["document_hash"], "stored_rows": len(target["rows"]),
                     "old": old, "new": new, "changed": changed})
    return {"what": "re-validation of document_intake_log validation columns (stored rows unchanged)",
            "taken_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "columns": list(COLUMNS), "rows": rows, "unchanged": unchanged, "fingerprint": fingerprint(rows)}


def _guard(prefix_values: dict):
    """WHERE clause + params matching a row's exact current values of the
    status, method and difference (NULL-safe)."""
    clause, params = [], []
    for c in ("validation_status", "validation_method", "validation_difference"):
        if prefix_values[c] is None:
            clause.append(f"{c} IS NULL")
        else:
            clause.append(f"{c} = ?")
            params.append(prefix_values[c])
    return " AND ".join(clause), params


def _update(values: dict, statement_id: str, ingestion_timestamp, guard_values: dict):
    where, guard_params = _guard(guard_values)
    sql = (f"UPDATE document_intake_log SET {', '.join(c + ' = ?' for c in COLUMNS)} "
           f"WHERE statement_id = ? AND ingestion_timestamp = ? AND {where}")
    return sql, [values[c] for c in COLUMNS] + [statement_id, ingestion_timestamp] + guard_params


def _sql_literal(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "N'" + str(v).replace("'", "''") + "'"


def backup(the_plan: dict, dirs: list, stamp: Optional[str] = None) -> list:
    """backup .json + undo .sql + undo .py in every dir, each read back."""
    stamp = stamp or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    doc = {**the_plan, "what": "BACKUP for the re-validation: old values of the 7 validation columns per row"}
    undo_sql = ["-- UNDO for the re-validation: restores the 7 validation columns, only on rows that still",
                "-- hold the values the update wrote (status + method + difference guard). One transaction.",
                "SET XACT_ABORT ON;", "BEGIN TRANSACTION;"]
    for r in the_plan["rows"]:
        where, params = _guard(r["new"])
        for p in params:
            where = where.replace("?", _sql_literal(p), 1)
        undo_sql.append(f"UPDATE document_intake_log SET {', '.join(f'{c} = {_sql_literal(r['old'][c])}' for c in COLUMNS)} "
                        f"WHERE statement_id = {_sql_literal(r['statement_id'])} AND ingestion_timestamp = "
                        f"{_sql_literal(r['ingestion_timestamp'])} AND {where};")
    undo_sql.append("COMMIT TRANSACTION;")
    paths = []
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        base = os.path.join(d, f"revalidation_{stamp}")
        with open(base + "_backup.json", "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, default=str)
        with open(base + "_undo.sql", "w", encoding="utf-8") as f:
            f.write("\n".join(undo_sql) + "\n")
        with open(base + "_undo.py", "w", encoding="utf-8") as f:
            f.write(UNDO_PY.replace("__BACKUP__", os.path.basename(base + "_backup.json")))
        back = json.load(open(base + "_backup.json", encoding="utf-8"))
        if back["fingerprint"] != the_plan["fingerprint"] or len(back["rows"]) != len(the_plan["rows"]):
            raise RuntimeError(f"backup read-back mismatch: {base}_backup.json")
        paths.append(base + "_backup.json")
    return paths


UNDO_PY = '''"""UNDO runner for a document_intake_log re-validation (src/rerun/revalidate.py).
Restores the 7 validation columns from __BACKUP__ (same folder), only on rows that still hold
the values the update wrote; every UPDATE must hit exactly 1 row, all in ONE transaction.
Dry run unless --apply. Uses src/lakehouse/connection.py (AZURE_SQL_* env)."""
import json, os, sys
sys.path.insert(0, os.environ.get("VIVE_ROOT", "."))
from src.rerun import revalidate
doc = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "__BACKUP__"), encoding="utf-8"))
print(revalidate.undo(doc, apply_changes="--apply" in sys.argv))
'''


def _transaction(statements: list) -> None:
    """Runs (sql, params) pairs in ONE transaction; each must hit exactly 1
    row, otherwise everything is rolled back."""
    from src.lakehouse import connection
    conn = connection.get_connection()
    azure = connection._using_azure_sql()
    try:
        cur = conn.cursor()
        for sql, params in statements:
            cur.execute(connection._translate_for_azure(sql) if azure else sql, params)
            if cur.rowcount != 1:
                raise RefusedError(f"an UPDATE hit {cur.rowcount} rows (expected 1) -- rolled back, nothing written")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply(io, the_plan: dict, expected_fingerprint: str, backup_paths: list) -> dict:
    """Writes the plan: refuses on a changed fingerprint or a missing backup;
    ONE transaction; then re-reads every row and verifies the new values."""
    if not backup_paths or not all(os.path.exists(p) for p in backup_paths):
        raise RefusedError("no backup on disk -- refusing to write")
    fresh = []
    for r in the_plan["rows"]:
        rows = io.az_query("SELECT * FROM document_intake_log WHERE statement_id = ?", [r["statement_id"]])
        if len(rows) != 1:
            raise RefusedError(f"{r['statement_id']}: {len(rows)} intake rows now")
        fresh.append({**r, "old": _old(rows[0]), "ingestion_timestamp": str(rows[0]["ingestion_timestamp"]),
                      "document_hash": rows[0]["document_hash"]})
    if fingerprint(fresh) != expected_fingerprint or the_plan["fingerprint"] != expected_fingerprint:
        raise RefusedError("the stored rows changed since the dry run -- run the dry run again")
    _transaction([_update(r["new"], r["statement_id"], r["ingestion_timestamp"], r["old"]) for r in the_plan["rows"]])
    problems = []
    for r in the_plan["rows"]:
        now = _old(io.az_query("SELECT * FROM document_intake_log WHERE statement_id = ?", [r["statement_id"]])[0])
        bad = [c for c in COLUMNS if str(now[c]) != str(r["new"][c])]
        if bad:
            problems.append(f"{r['statement_id']}: {bad}")
    return {"written": len(the_plan["rows"]), "verified": not problems, "problems": problems}


def undo(backup_doc: dict, apply_changes: bool = False) -> dict:
    """Restores the old values on rows that still hold the new ones (one transaction)."""
    statements = [_update(r["old"], r["statement_id"], r["ingestion_timestamp"], r["new"]) for r in backup_doc["rows"]]
    if not apply_changes:
        return {"dry_run": True, "rows": len(statements)}
    _transaction(statements)
    return {"dry_run": False, "restored": len(statements)}
