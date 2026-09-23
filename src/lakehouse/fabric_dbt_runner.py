"""Triggers the dbt Bronze -> Silver build (dbt/) for one statement, as a
subprocess. Additive to the existing pipeline, never required for it to
complete -- see fabric_bronze.py's write_bronze_fabric() docstring for the
same philosophy on the write side.

dbt-core/dbt-fabric are pinned directly in requirements.txt (2026-09-01 --
previously kept in a separate dbt/requirements-dbt.txt out of a
theoretical version-collision concern that a clean-venv dependency check
didn't confirm; that separation meant dbt was never actually installed in
the app's own image, so this whole module silently no-op'd on every job
until then). Installed this way, `dbt` lands on PATH wherever pip put it
(e.g. /usr/local/bin/dbt in the container, not this repo's own venv/,
which .dockerignore excludes from the image entirely) --
_default_dbt_executable() resolves it via shutil.which() for exactly that
reason, falling back to a venv/-relative guess only if PATH lookup finds
nothing (e.g. a venv activated without also being the active Python's own
install). DBT_EXECUTABLE_PATH still lets a deployment override both.

statement.sql/statement_line.sql source from bronze.raw_statement/
unnested_statement_lines (the dict-dump pipeline, see src/lakehouse/
bronze_raw.py) instead of the old per-vendor bronze.bronze_<vendor_id>_raw
tables -- there's no longer a per-vendor table list for this module to
discover or keep in sync anywhere. The per-vendor Bronze write itself
(fabric_bronze.py's write_bronze_fabric()) was removed from
notebooks/01_document_intake.py once nothing read it anymore.
"""
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DBT_PROJECT_DIR = os.path.join(PROJECT_ROOT, "dbt", "vive_recon")
DBT_PROFILES_DIR = os.path.join(PROJECT_ROOT, "dbt")
_LOCK_PATH = os.path.join(DBT_PROFILES_DIR, ".fabric_pipeline.lock")
_SILVER_SILVER_LOCK_PATH = os.path.join(DBT_PROFILES_DIR, ".silver_silver_pipeline.lock")


@contextlib.contextmanager
def fabric_pipeline_lock(timeout_seconds: int = 300, poll_interval: float = 0.5,
                          lock_path: str = None):
    """Cross-process exclusive lock for the whole "touches shared Fabric/dbt
    state" portion of one statement's pipeline -- see
    scripts/run_full_pipeline.py's caller, which wraps both
    run_dbt_silver_build() and run_fabric_matching() in this together.

    A plain threading.Lock() does NOT work here: web/worker.py's job pool
    runs each job's pipeline as a separate subprocess (`python
    scripts/run_full_pipeline.py ...`), not as threads sharing one
    interpreter -- a thread lock object in one process has zero visibility
    into a lock object in another. This uses atomic exclusive file creation
    (os.O_CREAT | os.O_EXCL, atomic on POSIX and Windows alike) as a mutex
    every process can see via the shared filesystem, instead.

    _regenerate_sources_yml() rewrites one shared file, `dbt run` reads/
    writes shared compiled-artifacts state under DBT_PROJECT_DIR/target/,
    and run_fabric_matching() opens its own Warehouse/Lakehouse connections
    -- none of that is safe for two statements' pipelines to touch at once.
    A multi-PDF upload landing on more than one worker at the same moment
    reliably raced here in practice (confirmed 2026-09-09): sources.yml
    corruption when the dbt step collided, and separately, transient
    Fabric-connection failures with no visible error when the matching step
    collided, once the dbt-level race alone was fixed. Serializing the
    whole sequence removes both. Each pipeline's Fabric-touching portion
    only takes on the order of a minute, so losing parallelism here
    specifically is cheap compared to debugging silent, non-deterministic
    per-statement failures -- extraction (Phase 1, before this) is
    unaffected and still runs concurrently across the worker pool.

    timeout_seconds also doubles as the stale-lock threshold: if a process
    holding the lock is killed without cleaning up (a crash, a container
    restart mid-run), a lock file older than this is assumed abandoned and
    is removed so the pipeline doesn't hang forever.

    lock_path defaults to the shared dbt/Bronze/matching lock (_LOCK_PATH)
    -- pass a different path to get an independent lock guarding some other
    shared resource without contending with (or queuing behind) this one.
    See src/lakehouse/bronze_raw.py, whose raw-dump write needs its own
    lock (protecting concurrent writers to bronze.raw_statement
    from each other) but has no reason to wait behind unrelated Bronze/dbt/
    matching work, especially in RESEARCH_MODE_EXTRACTION_ONLY where none
    of that even runs -- confirmed 2026-09-15: sharing the one lock across
    a large batch caused later jobs to queue past the 300s timeout and
    silently lose their raw-dump write.
    """
    path = lock_path or _LOCK_PATH
    deadline = time.time() + timeout_seconds
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > timeout_seconds:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                raise TimeoutError(f"Could not acquire {path} within {timeout_seconds}s")
            time.sleep(poll_interval)
    try:
        yield
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _default_dbt_executable() -> str:
    on_path = shutil.which("dbt")
    if on_path:
        return on_path
    exe_name = "dbt.exe" if sys.platform == "win32" else "dbt"
    return os.path.join(PROJECT_ROOT, "venv", "Scripts" if sys.platform == "win32" else "bin", exe_name)


def _fabric_configured() -> bool:
    return bool(
        os.getenv("FABRIC_TENANT_ID")
        and os.getenv("FABRIC_CLIENT_ID")
        and os.getenv("FABRIC_CLIENT_SECRET")
        and os.getenv("FABRIC_SQL_ENDPOINT")
        and os.getenv("FABRIC_WAREHOUSE_NAME")
    )


def _ensure_local_profile() -> None:
    """dbt/profiles.yml is gitignored (matches .env's convention) but has
    no literal secrets -- every value is env_var(). Safe to auto-create
    from the committed template on first use in a fresh checkout."""
    profile_path = os.path.join(DBT_PROFILES_DIR, "profiles.yml")
    example_path = os.path.join(DBT_PROFILES_DIR, "profiles.yml.example")
    if not os.path.exists(profile_path) and os.path.exists(example_path):
        import shutil
        shutil.copyfile(example_path, profile_path)


def run_dbt_silver_build(statement_id: str, timeout_seconds: int = 300,
                          expected_lines: int = None, expected_fields: int = None) -> bool:
    """Runs `dbt run --vars '{"statement_id": "..."}'` scoped to one
    statement. Returns True on success, False otherwise (missing config,
    missing dbt executable, staging data never became visible, non-zero
    exit, or timeout) -- never raises.

    expected_lines/expected_fields (the counts scripts/run_full_pipeline.py's
    caller just wrote to bronze.unnested_statement_lines/_fields): when both
    given, polls wait_for_visibility() first -- the same read-after-write
    race confirmed real 2026-09-18 (see that function's own docstring) and
    already guarded against on the (now-dead) silver_silver path, just never
    wired into this, the actual pipeline's own dbt trigger, until now. A
    dbt run triggered immediately after a fresh Bronze write can otherwise
    silently see 0 rows for this statement_id and "succeed" having written
    nothing -- exit 0, no error, but silver.statement/statement_line end up
    empty and matching then reports "no_silver_statement". Left optional
    (None skips the wait, original behavior) so any other/future caller
    that doesn't have these counts handy isn't forced to supply them.
    """
    if not _fabric_configured():
        logger.debug("Fabric not configured -- skipping dbt Silver build")
        print("    Fabric Silver build reason: _fabric_configured() returned False (missing FABRIC_* env var)")
        return False

    dbt_executable = os.getenv("DBT_EXECUTABLE_PATH") or _default_dbt_executable()
    if not os.path.exists(dbt_executable):
        logger.warning(
            "dbt executable not found at %s (set DBT_EXECUTABLE_PATH if dbt "
            "lives elsewhere in this environment) -- skipping Silver build",
            dbt_executable,
        )
        print(f"    Fabric Silver build reason: dbt executable not found at {dbt_executable}")
        return False

    if expected_lines is not None and expected_fields is not None:
        from src.lakehouse.bronze_unnest import wait_for_visibility
        _wait_start = time.time()
        if not wait_for_visibility(statement_id, expected_lines, expected_fields):
            logger.warning(
                "Bronze staging data never became visible for statement_id=%s after %.1fs -- skipping Silver build",
                statement_id, time.time() - _wait_start,
            )
            print("    Fabric Silver build reason: staging data not visible via SQL endpoint within timeout")
            return False

    try:
        _ensure_local_profile()
        env = {**os.environ, "DBT_PROFILES_DIR": DBT_PROFILES_DIR}
        dbt_vars = json.dumps({"statement_id": statement_id})
        result = subprocess.run(
            [
                dbt_executable, "run",
                "--project-dir", DBT_PROJECT_DIR,
                "--vars", dbt_vars,
            ],
            cwd=DBT_PROJECT_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            logger.error(
                "dbt run failed for statement_id=%s (exit %d):\n%s",
                statement_id, result.returncode, result.stdout[-4000:],
            )
            last_line = (result.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
            print(f"    Fabric Silver build reason: dbt run exited {result.returncode} -- {last_line[0][:300]}")
            return False
        return True

    except subprocess.TimeoutExpired:
        logger.error("dbt run timed out after %ds for statement_id=%s", timeout_seconds, statement_id)
        print(f"    Fabric Silver build reason: dbt run timed out after {timeout_seconds}s")
        return False
    except Exception as e:
        logger.exception("dbt run failed to start for statement_id=%s", statement_id)
        print(f"    Fabric Silver build reason: dbt run failed to start -- {type(e).__name__}: {e}")
        return False


def run_dbt_silver_silver_build(statement_id: str, expected_lines: int, expected_fields: int,
                                 timeout_seconds: int = 300) -> bool:
    """Best-effort dbt run for silver_silver_statement +
    silver_silver_statement_line (dbt/vive_recon/models/silver_silver/),
    which read bronze.raw_statement/unnested_statement_lines/
    unnested_statement_fields -- all written by
    src.lakehouse.bronze_unnest.write_unnested_from_invoices() and
    src.lakehouse.bronze_raw.write_raw_statement() just before this is
    called.

    Polls src.lakehouse.bronze_unnest.wait_for_visibility() first --
    confirmed 2026-09-18 that running dbt immediately after those writes
    can silently see 0 rows (the SQL analytics endpoint's propagation lag
    applies to every table here, not just raw_payload's width problem).
    Skips the dbt run entirely (returns False, logged) rather than risk
    running it against data that isn't visible yet -- better a delayed
    build than one that silently no-ops.

    Called from notebooks/01_document_intake.py right after
    write_raw_statement() and write_unnested_from_invoices(), NOT
    alongside run_dbt_silver_build() in scripts/run_full_pipeline.py --
    that call site is skipped entirely under RESEARCH_MODE_EXTRACTION_ONLY,
    but the raw dump/unnest this reads runs unconditionally regardless of
    that flag.

    Runs under its own lock (_SILVER_SILVER_LOCK_PATH), not the shared
    fabric_pipeline_lock() run_dbt_silver_build()/matching use -- this is
    a separate, additive test path with nothing to race against there.
    Returns True on success, False otherwise (missing config, missing dbt
    executable, staging data never became visible, non-zero exit, or
    timeout) -- never raises."""
    if not _fabric_configured():
        logger.debug("Fabric not configured -- skipping silver_silver dbt build")
        print("    silver_silver dbt build reason: _fabric_configured() returned False (missing FABRIC_* env var)")
        return False

    dbt_executable = os.getenv("DBT_EXECUTABLE_PATH") or _default_dbt_executable()
    if not os.path.exists(dbt_executable):
        logger.warning(
            "dbt executable not found at %s -- skipping silver_silver build",
            dbt_executable,
        )
        print(f"    silver_silver dbt build reason: dbt executable not found at {dbt_executable}")
        return False

    from src.lakehouse.bronze_unnest import wait_for_visibility
    _wait_start = time.time()
    if not wait_for_visibility(statement_id, expected_lines, expected_fields):
        logger.warning(
            "silver_silver staging data never became visible for statement_id=%s after %.1fs -- skipping dbt build",
            statement_id, time.time() - _wait_start,
        )
        print(f"    silver_silver dbt build reason: staging data not visible via SQL endpoint within timeout")
        return False

    try:
        _ensure_local_profile()
        env = {**os.environ, "DBT_PROFILES_DIR": DBT_PROFILES_DIR}
        dbt_vars = json.dumps({"statement_id": statement_id})
        with fabric_pipeline_lock(timeout_seconds=timeout_seconds, lock_path=_SILVER_SILVER_LOCK_PATH):
            result = subprocess.run(
                [
                    dbt_executable, "run",
                    "--project-dir", DBT_PROJECT_DIR,
                    "--select", "silver_silver_statement", "silver_silver_statement_line",
                    "--vars", dbt_vars,
                ],
                cwd=DBT_PROJECT_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        if result.returncode != 0:
            logger.error(
                "silver_silver dbt run failed for statement_id=%s (exit %d):\n%s",
                statement_id, result.returncode, result.stdout[-4000:],
            )
            last_line = (result.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
            print(f"    silver_silver dbt build reason: dbt run exited {result.returncode} -- {last_line[0][:300]}")
            return False
        return True

    except subprocess.TimeoutExpired:
        logger.error("silver_silver dbt run timed out after %ds for statement_id=%s", timeout_seconds, statement_id)
        print(f"    silver_silver dbt build reason: dbt run timed out after {timeout_seconds}s")
        return False
    except Exception as e:
        logger.exception("silver_silver dbt run failed to start for statement_id=%s", statement_id)
        print(f"    silver_silver dbt build reason: dbt run failed to start -- {type(e).__name__}: {e}")
        return False

