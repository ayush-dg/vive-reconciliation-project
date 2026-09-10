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

known_vendor_ids -- the list statement.sql/statement_line.sql loop over to
union each vendor's Bronze table into Silver -- used to be a hand-maintained
list in dbt_project.yml, duplicated a second time (as literal source table
names) in models/bronze/sources.yml. Both copies had to be updated by hand
every time a vendor was renamed or onboarded, and drifting out of sync
silently dropped a vendor from Silver with no error. Both are now driven
here from the one thing that's actually authoritative: which
bronze_<vendor_id>_raw tables exist in the Fabric Lakehouse right now (see
_discover_known_vendor_ids()) -- passed to dbt_project.yml's var via
`dbt run --vars`, and written into models/bronze/sources.yml as plain
generated YAML (see _regenerate_sources_yml() -- deliberately not a
Jinja-templated {% for %} in the checked-in file, which generic YAML
tooling/linters choke on outside of an actual dbt render pass). Nothing
about a vendor's id needs to be typed into dbt/ ever again -- the next dbt
run just picks up whatever tables exist.
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


@contextlib.contextmanager
def fabric_pipeline_lock(timeout_seconds: int = 300, poll_interval: float = 0.5):
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
    """
    deadline = time.time() + timeout_seconds
    while True:
        try:
            fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(_LOCK_PATH) > timeout_seconds:
                    os.remove(_LOCK_PATH)
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                raise TimeoutError(f"Could not acquire {_LOCK_PATH} within {timeout_seconds}s")
            time.sleep(poll_interval)
    try:
        yield
    finally:
        try:
            os.remove(_LOCK_PATH)
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


def _discover_known_vendor_ids() -> list:
    """Live-queries the Fabric Lakehouse for every bronze.bronze_<id>_raw
    table that actually exists and derives <id> from the table name. This
    is the ground truth for known_vendor_ids -- a vendor's table either
    exists (it's had at least one statement written to Bronze) or it
    doesn't; there's no separate config to keep in sync. Returns [] (never
    raises) if the Lakehouse can't be reached, matching this module's
    "additive, never blocks the pipeline" philosophy -- callers should
    treat an empty result as "can't build Silver right now", not "this
    vendor genuinely has zero data"."""
    from src.lakehouse.fabric_sql import get_lakehouse_connection

    try:
        conn = get_lakehouse_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT t.name FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id "
            "WHERE s.name = 'bronze' AND t.name LIKE 'bronze[_]%[_]raw'"
        )
        vendor_ids = sorted(
            row[0][len("bronze_"):-len("_raw")] for row in cur.fetchall()
        )
        return vendor_ids
    except Exception as e:
        logger.exception("Discovering known_vendor_ids from the Fabric Lakehouse failed (non-fatal)")
        # print(), not just logger.exception() -- see run_dbt_silver_build()'s
        # own "Fabric Silver build reason:" prints for why: this subprocess's
        # logging output isn't reliably surfaced to the container's own logs
        # (web/worker.py only echoes captured stdout on specific failure
        # branches), so a real exception here was previously indistinguishable
        # from every other silent "no vendor ids" outcome.
        print(f"    Fabric Silver build reason: vendor discovery query failed -- {type(e).__name__}: {e}")
        return []


def _regenerate_sources_yml(vendor_ids: list) -> None:
    """Rewrites models/bronze/sources.yml to declare exactly the bronze
    tables in vendor_ids. Plain YAML text, written fresh before every dbt
    run -- see this module's docstring for why this replaced a
    hand-maintained (or Jinja-templated) file."""
    lines = [
        "# GENERATED by src/lakehouse/fabric_dbt_runner.py -- do not hand-edit.",
        "# Rewritten fresh before every dbt run from whichever bronze.bronze_<id>_raw",
        "# tables actually exist in the Fabric Lakehouse (see",
        "# _discover_known_vendor_ids() / _regenerate_sources_yml()). This file's",
        "# committed state just reflects whatever vendors existed at the last real",
        "# run in this checkout -- editing it by hand has no lasting effect.",
        "version: 2",
        "sources:",
        "  - name: bronze",
        "    database: \"{{ env_var('FABRIC_LAKEHOUSE_NAME') }}\"",
        "    schema: bronze",
        "    tables:",
    ]
    lines.extend(f"      - name: bronze_{vendor_id}_raw" for vendor_id in vendor_ids)
    sources_yml_path = os.path.join(DBT_PROJECT_DIR, "models", "bronze", "sources.yml")
    with open(sources_yml_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def run_dbt_silver_build(statement_id: str, timeout_seconds: int = 300) -> bool:
    """Runs `dbt run --vars '{"statement_id": "...", "known_vendor_ids": [...]}'`
    scoped to one statement, with known_vendor_ids discovered fresh from the
    Lakehouse on every call (see _discover_known_vendor_ids()). Returns True
    on success, False otherwise (missing config, missing dbt executable,
    discovery failure, non-zero exit, or timeout) -- never raises.
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

    known_vendor_ids = _discover_known_vendor_ids()
    if not known_vendor_ids:
        logger.warning("No bronze_<vendor_id>_raw tables discovered in the Lakehouse -- skipping Silver build")
        print("    Fabric Silver build reason: no known_vendor_ids discovered (empty result, see prior line if an exception caused it)")
        return False

    try:
        _ensure_local_profile()
        _regenerate_sources_yml(known_vendor_ids)
        env = {**os.environ, "DBT_PROFILES_DIR": DBT_PROFILES_DIR}
        dbt_vars = json.dumps({"statement_id": statement_id, "known_vendor_ids": known_vendor_ids})
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
