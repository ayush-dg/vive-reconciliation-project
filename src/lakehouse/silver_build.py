"""Builds silver.statement + silver.statement_line for ONE statement by
appending rows -- the dbt models' own SQL, without a dbt run per PDF.

Why (2026-09-28, measured on the dev App Service): `dbt run` per PDF was
the dominant cost left once the SQL-endpoint sync wait was fixed, and
it forced every job through fabric_pipeline_lock():
  - dbt-fabric's incremental materialization always stages through
    fixed-name temp relations (<model>__dbt_tmp / __dbt_tmp_vw) for EVERY
    strategy, merge or append -- two concurrent runs drop each other's
    temp table (seen live: "Invalid object name ...statement__dbt_tmp").
  - its MERGE into the shared Silver tables is a write-write conflict
    risk in Fabric Warehouse whenever two run at once.
  - each run re-parses the whole project (--vars changes every run) --
    56-118s per PDF on the 1-core B1 plan, 3 jobs sharing that core.
With the lock serializing all of that, 8 PDFs spent ~16 of their 18
minutes queued behind one another's dbt + matching.

Here instead: the two models are compiled ONCE per container (dbt stays
the single source of the transformation SQL -- same models, macros and
seeds), with a placeholder statement_id. Each PDF then runs that SELECT
for its own statement_id and appends the rows with batched INSERTs --
no temp tables, no MERGE, no dbt process -- so concurrent jobs don't
conflict and need no lock. A statement_id that already has Silver rows
(a re-run; every upload normally gets a fresh id) is the one case that
needs DELETE + INSERT, and that path still takes fabric_pipeline_lock().

SILVER_BUILD_MODE=dbt switches scripts/run_full_pipeline.py back to the
old run_dbt_silver_build() path under the lock.
"""
import hashlib
import json
import logging
import os
import re
import subprocess

from src.lakehouse.fabric_dbt_runner import (
    DBT_PROFILES_DIR,
    DBT_PROJECT_DIR,
    _default_dbt_executable,
    _ensure_local_profile,
    _fabric_configured,
    fabric_pipeline_lock,
)

logger = logging.getLogger(__name__)

# Order matters only for readability -- both models read Bronze directly,
# not each other.
MODELS = [
    ("statement", "silver.statement"),
    ("statement_line", "silver.statement_line"),
]
_PLACEHOLDER = "__VIVE_STATEMENT_ID_PLACEHOLDER__"
_CACHE_ROOT = os.path.join(DBT_PROFILES_DIR, ".compiled_silver")
_COMPILE_LOCK_PATH = os.path.join(DBT_PROFILES_DIR, ".silver_compile.lock")
_STATEMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def silver_build_mode() -> str:
    """'direct' (default) or 'dbt' (the pre-2026-09-28 path)."""
    return "dbt" if os.getenv("SILVER_BUILD_MODE", "").strip().lower() == "dbt" else "direct"


def _project_fingerprint() -> str:
    """Hash of everything that shapes the compiled SQL -- models, macros,
    dbt_project.yml -- so a new image with changed models never reuses a
    stale compile. Seed CONTENTS don't matter (the SQL only references
    the seed tables by name)."""
    digest = hashlib.sha256()
    for sub in ("models", "macros"):
        root = os.path.join(DBT_PROJECT_DIR, sub)
        for dirpath, _, files in sorted(os.walk(root)):
            for name in sorted(files):
                path = os.path.join(dirpath, name)
                digest.update(os.path.relpath(path, DBT_PROJECT_DIR).encode())
                with open(path, "rb") as f:
                    digest.update(f.read())
    with open(os.path.join(DBT_PROJECT_DIR, "dbt_project.yml"), "rb") as f:
        digest.update(f.read())
    return digest.hexdigest()[:16]


def _compiled_sql() -> dict:
    """{model_name: compiled SELECT with a quoted placeholder id}, compiled
    once and cached on disk. The worker pool runs each job as its own
    subprocess, so the cache is a file, guarded by a cross-process lock --
    the first job pays the one `dbt compile`, the rest just read it."""
    cache_dir = os.path.join(_CACHE_ROOT, _project_fingerprint())
    paths = {m: os.path.join(cache_dir, f"{m}.sql") for m, _ in MODELS}

    def _read():
        if all(os.path.exists(p) for p in paths.values()):
            out = {}
            for m, p in paths.items():
                with open(p, encoding="utf-8") as f:
                    out[m] = f.read()
            return out
        return None

    cached = _read()
    if cached:
        return cached

    with fabric_pipeline_lock(timeout_seconds=600, lock_path=_COMPILE_LOCK_PATH):
        cached = _read()
        if cached:
            return cached

        _ensure_local_profile()
        target_path = os.path.join(cache_dir, "target")
        dbt_executable = os.getenv("DBT_EXECUTABLE_PATH") or _default_dbt_executable()
        result = subprocess.run(
            [
                dbt_executable, "compile",
                "--project-dir", DBT_PROJECT_DIR,
                "--target-path", target_path,
                "--select", *[m for m, _ in MODELS],
                "--vars", json.dumps({"statement_id": _PLACEHOLDER}),
            ],
            cwd=DBT_PROJECT_DIR,
            env={**os.environ, "DBT_PROFILES_DIR": DBT_PROFILES_DIR},
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"dbt compile exited {result.returncode}: {(result.stdout or '')[-1500:]}")

        for model, _ in MODELS:
            compiled_path = os.path.join(
                target_path, "compiled", "vive_recon", "models", "silver", f"{model}.sql"
            )
            with open(compiled_path, encoding="utf-8") as f:
                sql = f.read()
            if f"'{_PLACEHOLDER}'" not in sql:
                raise RuntimeError(f"compiled {model}.sql has no statement_id filter -- refusing to use it")
            with open(paths[model], "w", encoding="utf-8") as f:
                f.write(sql)

    return _read()


def _target_columns(cur, table: str) -> dict:
    schema, name = table.split(".")
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
        [schema, name],
    )
    return {row[0].lower(): row[0] for row in cur.fetchall()}


def _has_rows(cur, table: str, statement_id: str) -> bool:
    cur.execute(f"SELECT TOP 1 1 FROM {table} WHERE statement_id = ?", [statement_id])
    return cur.fetchone() is not None


def _select_rows(cur, sql: str, statement_id: str):
    quoted = f"'{_PLACEHOLDER}'"
    cur.execute(sql.replace(quoted, "?"), [statement_id] * sql.count(quoted))
    columns = [d[0] for d in cur.description]
    return columns, cur.fetchall()


def _append(cur, compiled: dict, statement_id: str) -> dict:
    from src.lakehouse.fabric_sql import insert_rows

    counts = {}
    for model, table in MODELS:
        columns, rows = _select_rows(cur, compiled[model], statement_id)
        target = _target_columns(cur, table)
        keep = [i for i, c in enumerate(columns) if c.lower() in target]
        dropped = [c for c in columns if c.lower() not in target]
        if dropped:
            logger.warning("%s: model columns missing from the table, not written: %s", table, dropped)
        insert_rows(
            cur, table,
            [target[columns[i].lower()] for i in keep],
            [[row[i] for i in keep] for row in rows],
        )
        counts[table] = len(rows)
    return counts


def build_silver_direct(statement_id: str) -> bool:
    """Appends this statement's silver.statement + silver.statement_line
    rows in ONE Warehouse transaction. Returns True on success (even if
    Bronze had nothing for it -- same contract as run_dbt_silver_build()),
    False on any failure. Never raises."""
    if not _fabric_configured():
        print("    Fabric Silver build reason: _fabric_configured() returned False (missing FABRIC_* env var)")
        return False
    if not _STATEMENT_ID_RE.match(statement_id or ""):
        print(f"    Fabric Silver build reason: unexpected statement_id format {statement_id!r}")
        return False

    from src.lakehouse.fabric_sql import get_warehouse_connection

    try:
        compiled = _compiled_sql()
    except Exception as e:
        logger.exception("Compiling Silver models failed for statement_id=%s", statement_id)
        print(f"    Fabric Silver build reason: dbt compile failed -- {type(e).__name__}: {str(e)[:250]}")
        return False

    conn = None
    try:
        conn = get_warehouse_connection()
        cur = conn.cursor()
        if any(_has_rows(cur, table, statement_id) for _, table in MODELS):
            # Re-run of an existing statement_id: DELETE + INSERT on shared
            # tables -- the one case that can conflict, so it keeps the lock.
            with fabric_pipeline_lock():
                for _, table in MODELS:
                    cur.execute(f"DELETE FROM {table} WHERE statement_id = ?", [statement_id])
                counts = _append(cur, compiled, statement_id)
                conn.commit()
        else:
            counts = _append(cur, compiled, statement_id)
            conn.commit()
        logger.info("Silver appended for statement_id=%s: %s", statement_id, counts)
        return True
    except Exception as e:
        logger.exception("Direct Silver build failed for statement_id=%s", statement_id)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"    Fabric Silver build reason: direct build failed -- {type(e).__name__}: {str(e)[:250]}")
        return False
    finally:
        if conn is not None:
            conn.close()
