"""
connection.py

The only file that knows the storage backend. Locally (and in tests), it's
SQLite. In production, it's Azure SQL — selected automatically by whether
AZURE_SQL_SERVER is set in the environment (see .env). Every other module
gets a connection from here and writes backend-agnostic SQL against it;
this file is where the SQLite-vs-Azure-SQL dialect differences (INSERT OR
REPLACE vs MERGE, trailing LIMIT vs SELECT TOP) are absorbed, via
execute_sql()/execute_query(), so callers never need their own branching.

See RULES.md RULE-06 — mock ERP data is a deliberate placeholder for a real
NetSuite integration, not yet built. This isolation (plus the record_source
field in silver_reconciliation_standard) is what keeps that future swap narrow.

See RULES.md RULE-13 — Phase 3 switch to Azure SQL as the production backend.
"""

import json
import sqlite3
import os
import re
import tempfile
import threading
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "lakehouse", "reconciliation.db")

# Azure SQL serverless (free tier) auto-pauses when idle, and a long
# pipeline run's per-row connection pattern (write_to_bronze(),
# normalize_to_silver() in notebooks/01_document_intake.py) can outlast
# that pause window — the connection drops mid-run with SQLSTATE 08S01
# ("Communication link failure") or 08001 ("TCP Provider: Timeout").
# execute_sql()/execute_query() retry those specific errors with a fresh
# connection (never reusing the dropped one) before giving up.
CONNECTION_DROP_SQLSTATES = {"08S01", "08001"}
MAX_CONNECTION_RETRIES = 3
CONNECTION_RETRY_WAIT_SECONDS = 5

# Retry/backoff for the CONNECT attempt itself (e.g. "Login timeout
# expired") — distinct from CONNECTION_DROP_SQLSTATES above, which is for
# a connection that was working and then dropped mid-query. Kept short:
# this blocks a request/worker thread until it gives up or succeeds.
CONNECT_RETRY_ATTEMPTS = 3
CONNECT_RETRY_WAIT_SECONDS = 2

# One persistent Azure SQL connection per thread, reused across calls
# instead of opening a fresh pyodbc connection (TCP+TLS handshake to Azure
# SQL) on every single query — see get_connection()/_is_connection_alive().
# threading.local() rather than one shared global connection: pyodbc
# connections aren't safe for concurrent use from multiple threads, and
# both the web app's request threadpool and the worker's fixed 3-thread
# pool (web/worker.py) already give each thread its own long-lived
# identity to key this on. SQLite is untouched by this — that path still
# opens/closes a connection per call exactly as before.
_thread_local = threading.local()

# Fabric AD token cache — see _get_fabric_access_token(). AzureCliCredential
# .get_token() shells out to a brand-new `az` CLI subprocess and waits for
# it to authenticate on every single call with no caching of its own. With
# get_fabric_connection() called on every dashboard/sidebar render (see
# web/queries.py's get_pending_review_count(), called both from get_kpis()
# and web/deps.py's sidebar_context() — i.e. on every page, not just the
# dashboard), that subprocess spawn was the dominant cost behind "every
# click felt laggy" during the 2026-08-12 demo. Azure AD tokens are valid
# ~1hr; refreshing only when within FABRIC_TOKEN_REFRESH_BUFFER_SECONDS of
# actual expiry (per the real expires_on the token carries, not an
# assumed lifetime) cuts that to roughly one subprocess spawn per hour.
_fabric_token_lock = threading.Lock()
_fabric_token_cache = {"token": None, "expires_on": 0}
_fabric_credential = None
FABRIC_TOKEN_REFRESH_BUFFER_SECONDS = 300

# Second cache layer, on disk — the in-memory dict above only helps within
# one long-lived process (the web app). Every PDF upload runs
# scripts/run_full_pipeline.py as a brand-new subprocess (web/worker.py's
# subprocess.run()), which starts with empty module-level state and would
# otherwise pay the same slow Azure CLI subprocess cost on every single
# upload — confirmed as ~90s of a ~390s KSI upload, twice (once for the
# extraction-cache check, once for the extraction-cache update), on
# 2026-08-12. This file lets any process — web app or pipeline subprocess —
# reuse a token another process already fetched. Same
# lakehouse/ai_call_slots/ directory convention as
# src/ai/concurrency_limiter.py for cross-process coordination via disk.
FABRIC_TOKEN_CACHE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "lakehouse", "fabric_token_cache.json"
)

# Table -> unique key columns, used to translate "INSERT OR REPLACE INTO
# table (...)" (SQLite upsert syntax) into a T-SQL MERGE statement when
# running against Azure SQL. Add an entry here whenever a new INSERT OR
# REPLACE call site targets a table not already listed.
AZURE_UPSERT_KEYS = {
    "silver_reconciliation_standard": ["record_id"],
    "extraction_cache": ["document_hash", "statement_id"],
}

_INSERT_OR_REPLACE_RE = re.compile(
    r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\((.*?)\)\s*VALUES\s*\((.*?)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)

_TRAILING_LIMIT_RE = re.compile(
    r"^\s*SELECT\s+(.*?)\s+LIMIT\s+(\d+)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _using_azure_sql():
    return bool(os.getenv("AZURE_SQL_SERVER"))


def _using_fabric_warehouse():
    return bool(os.getenv("FABRIC_WORKSPACE_ID"))


def _using_fabric_sqldb():
    return bool(os.getenv("FABRIC_SQLDB_ENDPOINT"))


SQL_COPT_SS_ACCESS_TOKEN = 1256


def _read_fabric_token_cache_file():
    """Returns {"token": str, "expires_on": number} from
    FABRIC_TOKEN_CACHE_PATH, or None if the file is missing, unreadable, or
    malformed. Never raises — a bad cache file just means "fall through to
    Azure CLI", the same outcome as an empty in-memory cache, not an error."""
    try:
        with open(FABRIC_TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "token" not in data or "expires_on" not in data:
        return None
    return data


def _write_fabric_token_cache_file(token: str, expires_on) -> None:
    """Writes {token, expires_on} to FABRIC_TOKEN_CACHE_PATH so every other
    process (web app, or the next pipeline subprocess) can reuse this token
    instead of shelling out to the Azure CLI again. Written via mkstemp() in
    the same directory + os.replace() — replace() is an atomic rename on
    both POSIX and Windows, so a concurrent reader always sees either the
    complete old file or the complete new one, never a half-written one.
    Best-effort: any failure here just means the next reader falls through
    to Azure CLI, same as if this layer didn't exist — never raises."""
    cache_dir = os.path.dirname(FABRIC_TOKEN_CACHE_PATH)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=".fabric_token_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"token": token, "expires_on": expires_on}, f)
            os.replace(tmp_path, FABRIC_TOKEN_CACHE_PATH)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return
    except OSError:
        return
    _restrict_fabric_token_cache_permissions()


def _restrict_fabric_token_cache_permissions() -> None:
    """Best-effort lockdown of FABRIC_TOKEN_CACHE_PATH (a live access token)
    to the current user only. os.chmod() alone doesn't strip inherited
    other-user ACEs on Windows, so this shells out to icacls there; POSIX
    gets a plain chmod 0600. Defense-in-depth only, not correctness-load-
    bearing — swallows every failure rather than breaking the caller."""
    try:
        if os.name == "nt":
            import subprocess
            username = os.environ.get("USERNAME", "")
            if username:
                subprocess.run(
                    ["icacls", FABRIC_TOKEN_CACHE_PATH, "/inheritance:r", "/grant:r", f"{username}:F"],
                    capture_output=True, timeout=10,
                )
        else:
            os.chmod(FABRIC_TOKEN_CACHE_PATH, 0o600)
    except Exception:
        pass


def _get_fabric_access_token() -> str:
    """Returns a cached Azure AD access token for the Fabric SQL database,
    refreshing only when there's no valid cached token or the cached one is
    within FABRIC_TOKEN_REFRESH_BUFFER_SECONDS of its real expires_on. Two
    cache layers, checked in order: (1) the in-memory dict, fastest, but
    scoped to this one process; (2) FABRIC_TOKEN_CACHE_PATH on disk, shared
    across every process — this is what lets a run_full_pipeline.py
    subprocess reuse a token the web app (or an earlier subprocess) already
    fetched, instead of paying the Azure CLI cost on every single upload.
    Azure CLI is only invoked when both layers miss. Thread-safe via
    _fabric_token_lock for the in-memory layer — under concurrent requests
    in the same process, the first one through refreshes and every other
    waits and reuses the result. Across processes, the disk layer has no
    lock — a rare simultaneous miss just means two processes both call
    Azure CLI and both write the file, same accepted-race posture as
    src/ai/concurrency_limiter.py's slot files; the atomic os.replace() in
    _write_fabric_token_cache_file() still guarantees no reader ever sees a
    corrupted file."""
    global _fabric_credential
    with _fabric_token_lock:
        now = time.time()
        cached_token = _fabric_token_cache["token"]
        if cached_token and _fabric_token_cache["expires_on"] - now > FABRIC_TOKEN_REFRESH_BUFFER_SECONDS:
            return cached_token

        disk_cached = _read_fabric_token_cache_file()
        if disk_cached and disk_cached["expires_on"] - now > FABRIC_TOKEN_REFRESH_BUFFER_SECONDS:
            _fabric_token_cache["token"] = disk_cached["token"]
            _fabric_token_cache["expires_on"] = disk_cached["expires_on"]
            return disk_cached["token"]

        if _fabric_credential is None:
            from azure.identity import AzureCliCredential
            tenant_id = os.getenv("FABRIC_TENANT_ID")
            _fabric_credential = AzureCliCredential(tenant_id=tenant_id)

        token = _fabric_credential.get_token("https://database.windows.net/.default")
        _fabric_token_cache["token"] = token.token
        _fabric_token_cache["expires_on"] = token.expires_on
        _write_fabric_token_cache_file(token.token, token.expires_on)
        return token.token


# This uses an Azure CLI-issued token (AzureCliCredential + SQL_COPT_SS_ACCESS_TOKEN)
# instead of the ODBC driver's Authentication=ActiveDirectoryInteractive keyword.
# Interactive auth was tried first and fails on this machine with FA004/0x534 —
# the Windows WAM broker can't complete the sign-in. The CLI-token approach
# sidesteps the driver's own auth flow entirely and was confirmed working; it
# requires `az login` to have been run once already in this environment — it
# reuses that session rather than prompting for one. Do not switch this to
# Authentication=ActiveDirectoryInteractive — same WAM-broker failure mode.
#
# Repointed 2026-08-06 from Fabric Warehouse to a real "SQL database in
# Fabric" item (FABRIC_SQLDB_ENDPOINT/FABRIC_SQLDB_NAME) — same auth
# mechanism, different target. This is what actually resolves R-012/IC-19
# for these three tables: SQL database in Fabric supports IDENTITY columns
# (schema created by scripts/create_fabric_sqldb_schema.py — deliberately
# not a migrations/ file, see that script's docstring for why), Fabric
# Warehouse did not.
def get_fabric_connection():
    """Returns a connection for the Fabric-cut-over tables: extraction_cache,
    document_intake_log, validation_document_review_queue — see
    notebooks/01_document_intake.py's check_cache()/update_cache()/
    write_to_review_queue()/write_intake_log().

    Falls back to the SAME local SQLite backend (same DB_PATH) whenever
    Fabric itself isn't configured (FABRIC_SQLDB_ENDPOINT unset) — this is
    intentionally independent of _using_azure_sql(): plain Azure SQL and
    the Fabric SQL database item are two separate cut-overs (see the
    module docstring), and a deployment can have one configured without
    the other. Originally this checked _using_azure_sql() instead, on the
    assumption real Azure SQL and real Fabric would always be configured
    together — that assumption broke the first time someone ran against a
    real Azure SQL Database without a Fabric SQL database item also set
    up, sending get_fabric_connection() to a real Fabric endpoint that was
    never provided. AZURE_SQL_SERVER="" is still this codebase's
    established test-isolation convention for get_connection() — every
    test that already relies on it to get a clean local run (e.g.
    tests/test_level2_matching_integration.py) is unaffected, since a test
    environment with AZURE_SQL_SERVER unset also has FABRIC_SQLDB_ENDPOINT
    unset. Real Fabric (Azure CLI token auth) is only used when Fabric
    itself is genuinely configured."""
    if not _using_fabric_sqldb():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    import struct

    import pyodbc

    endpoint = os.getenv("FABRIC_SQLDB_ENDPOINT")
    database = os.getenv("FABRIC_SQLDB_NAME")

    access_token = _get_fabric_access_token()
    token_bytes = access_token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server={endpoint},1433;"
        f"Database={database};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})


def _connect_azure_sql():
    """Opens one fresh pyodbc connection to Azure SQL. Retries
    CONNECT_RETRY_ATTEMPTS times with a short pause on a failed connect
    attempt (e.g. "Login timeout expired") before giving up — the 2026-08-12
    demo hit exactly this error with no retry, failing the request outright
    on what was often a transient blip."""
    import pyodbc

    server = os.getenv("AZURE_SQL_SERVER")
    database = os.getenv("AZURE_SQL_DATABASE")
    username = os.getenv("AZURE_SQL_USERNAME")
    password = os.getenv("AZURE_SQL_PASSWORD")
    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    last_exc = None
    for attempt in range(1, CONNECT_RETRY_ATTEMPTS + 1):
        try:
            return pyodbc.connect(conn_str)
        except Exception as e:
            last_exc = e
            if attempt < CONNECT_RETRY_ATTEMPTS:
                print(f"  Azure SQL connect failed (attempt {attempt}/{CONNECT_RETRY_ATTEMPTS}) — "
                      f"retrying in {CONNECT_RETRY_WAIT_SECONDS}s: {e}")
                time.sleep(CONNECT_RETRY_WAIT_SECONDS)
    raise last_exc


class _ReusableAzureConnection:
    """Wraps a real pyodbc connection so that .close() is inert — the
    connection is reused across many execute_sql()/execute_query() calls
    (see get_connection()) via a thread-local cache, and _run_with_retry()
    unconditionally calls conn.close() in a finally block after every
    single call (unchanged, original behavior — see _run_with_retry()'s
    docstring). Without this wrapper, that unconditional close would tear
    down the real connection right after its first use, defeating reuse
    entirely. Real teardown only happens via _real_close(), called by
    _discard_thread_local_azure_connection() when the connection is
    actually being replaced (found dead, or dropped mid-query).
    Everything else (execute, cursor, commit, ...) delegates straight to
    the wrapped pyodbc connection via __getattr__."""

    def __init__(self, real_conn):
        self._real_conn = real_conn

    def __getattr__(self, name):
        return getattr(self._real_conn, name)

    def close(self):
        pass  # intentionally inert — see class docstring

    def _real_close(self):
        self._real_conn.close()


def _is_connection_alive(conn) -> bool:
    """True if conn responds to a trivial query. Never raises — any
    failure means the connection is dead or in an unusable state, so the
    caller should discard it and reconnect rather than trust it further."""
    try:
        conn.execute("SELECT 1").fetchall()
        return True
    except Exception:
        return False


def _discard_thread_local_azure_connection():
    """Really closes and clears the thread-local reused Azure SQL
    connection, if one exists. A no-op when there isn't one (e.g. in
    tests that mock get_connection() directly and never populate
    _thread_local, or when running against SQLite) — safe to call
    unconditionally from _run_with_retry()'s retry branch."""
    conn = getattr(_thread_local, "azure_sql_conn", None)
    if conn is not None:
        try:
            conn._real_close()
        except Exception:
            pass
        _thread_local.azure_sql_conn = None


def get_connection():
    """Returns a connection to the configured backend. Azure SQL (via
    pyodbc) if AZURE_SQL_SERVER is set in the environment, otherwise a
    local SQLite connection — creating the DB file if it doesn't exist.

    Azure SQL: reuses one persistent connection per thread (see
    _thread_local), wrapped in _ReusableAzureConnection so the caller's
    conn.close() doesn't actually tear it down — instead of opening a
    fresh pyodbc connection (TCP+TLS handshake to Azure SQL) on literally
    every query, which was a major source of per-request latency, and
    Azure SQL serverless auto-pausing mid-idle was a real source of the
    "Login timeout expired" / "Communication link failure" errors seen
    during the 2026-08-12 demo. A cheap SELECT 1 health check runs before
    reuse; a dead connection is discarded and replaced, never trusted.
    SQLite is unaffected — this path still opens a fresh connection per
    call exactly as before, since there's no network round-trip to
    amortize and the existing test suite already depends on that
    per-call boundary."""
    if _using_azure_sql():
        conn = getattr(_thread_local, "azure_sql_conn", None)
        if conn is not None:
            if _is_connection_alive(conn):
                return conn
            _discard_thread_local_azure_connection()

        conn = _ReusableAzureConnection(_connect_azure_sql())
        _thread_local.azure_sql_conn = conn
        return conn

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # so rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _translate_for_azure(sql):
    """Rewrites SQLite-only syntax into T-SQL equivalents. Only touches
    the two patterns this codebase actually uses (see module docstring) —
    not a general-purpose SQL dialect translator."""
    match = _INSERT_OR_REPLACE_RE.match(sql)
    if match:
        table, columns_raw, values_raw = match.groups()
        columns = [c.strip() for c in columns_raw.split(",")]
        if table not in AZURE_UPSERT_KEYS:
            raise NotImplementedError(
                f"No AZURE_UPSERT_KEYS entry for table '{table}' — add one in connection.py"
            )
        key_columns = AZURE_UPSERT_KEYS[table]
        src_cols = [f"? AS {c}" for c in columns]
        on_clause = " AND ".join(f"target.{k} = source.{k}" for k in key_columns)
        update_cols = [c for c in columns if c not in key_columns]
        update_clause = ", ".join(f"{c} = source.{c}" for c in update_cols)
        insert_cols = ", ".join(columns)
        insert_vals = ", ".join(f"source.{c}" for c in columns)
        return (
            f"MERGE INTO {table} AS target "
            f"USING (SELECT {', '.join(src_cols)}) AS source "
            f"ON {on_clause} "
            f"WHEN MATCHED THEN UPDATE SET {update_clause} "
            f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals});"
        )

    match = _TRAILING_LIMIT_RE.match(sql)
    if match:
        body, limit_n = match.groups()
        return f"SELECT TOP {limit_n} {body}"

    return sql


def _is_dropped_connection_error(exc) -> bool:
    """True if exc is a pyodbc error with SQLSTATE 08S01/08001 — a dropped
    or timed-out Azure SQL connection, worth retrying with a fresh
    connection. False for anything else (a genuine query/schema error, or
    any SQLite error), which should propagate immediately."""
    try:
        import pyodbc
    except ImportError:
        return False
    if not isinstance(exc, pyodbc.Error):
        return False
    sqlstate = exc.args[0] if exc.args else None
    return sqlstate in CONNECTION_DROP_SQLSTATES


def _run_with_retry(fn):
    """
    Calls fn(conn) with a connection from get_connection(). If it raises a
    dropped-connection error (see _is_dropped_connection_error), retries
    up to MAX_CONNECTION_RETRIES times, each time discarding the dropped
    connection and getting a fresh one, after waiting
    CONNECTION_RETRY_WAIT_SECONDS. Any other error, or a dropped-connection
    error once retries are exhausted, re-raises the original exception
    unchanged.

    conn.close() runs unconditionally in the finally block, exactly as
    before connection reuse was added — this is safe for the reused Azure
    SQL connection because get_connection() returns it wrapped in
    _ReusableAzureConnection, whose close() is deliberately a no-op (see
    that class's docstring); a genuinely dropped connection is discarded
    for real via _discard_thread_local_azure_connection() in the retry
    branch below, so the next get_connection() call reconnects instead of
    retrying against a connection already known to be dead. SQLite's
    get_connection() returns an unwrapped connection, so its close() here
    still really closes it, unchanged from before.
    """
    for attempt in range(1, MAX_CONNECTION_RETRIES + 2):
        conn = get_connection()
        try:
            return fn(conn)
        except Exception as e:
            if _is_dropped_connection_error(e) and attempt <= MAX_CONNECTION_RETRIES:
                print(f"  Azure SQL connection dropped — retrying (attempt {attempt}/{MAX_CONNECTION_RETRIES})...")
                _discard_thread_local_azure_connection()
                time.sleep(CONNECTION_RETRY_WAIT_SECONDS)
                continue
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass


def execute_sql(sql, params=None):
    """Execute a single SQL statement and return the cursor. Retries on a
    dropped Azure SQL connection — see _run_with_retry."""
    def _run(conn):
        stmt = _translate_for_azure(sql) if _using_azure_sql() else sql
        cursor = conn.execute(stmt, params or [])
        conn.commit()
        return cursor
    return _run_with_retry(_run)


def execute_query(sql, params=None):
    """Execute a SELECT and return all rows as list of dicts. Retries on a
    dropped Azure SQL connection — see _run_with_retry."""
    def _run(conn):
        stmt = _translate_for_azure(sql) if _using_azure_sql() else sql
        cursor = conn.execute(stmt, params or [])
        rows = cursor.fetchall()
        if _using_azure_sql():
            columns = [col[0] for col in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            # Ends this SELECT's implicit transaction. Harmless when each
            # call got a fresh, immediately-closed connection (the old
            # behavior); now that the connection is reused across calls
            # (see get_connection()), leaving a read transaction open
            # between calls would hold locks on a connection that might
            # sit idle for a while, unlike before.
            conn.commit()
            return result
        return [dict(row) for row in rows]
    return _run_with_retry(_run)


def execute_sql_fabric(sql, params=None):
    """Execute a single SQL statement against get_fabric_connection() and
    return the cursor — real SQL database in Fabric in production
    (repointed 2026-08-06, was Fabric Warehouse), the same
    local SQLite DB_PATH as execute_sql() in local/test mode (see
    get_fabric_connection()). No dialect translation and no drop-retry:
    callers must write SQL that's valid on both SQLite and T-SQL (no
    LIMIT/TOP, no INSERT OR REPLACE — see check_cache()/update_cache() in
    notebooks/01_document_intake.py for the pattern). Additive only;
    execute_sql() is untouched and still targets Azure SQL directly."""
    conn = get_fabric_connection()
    try:
        cursor = conn.execute(sql, params or [])
        conn.commit()
        return cursor
    finally:
        conn.close()


def execute_query_fabric(sql, params=None):
    """Execute a SELECT against get_fabric_connection() and return all
    rows as a list of dicts — real SQL database in Fabric in production
    (repointed 2026-08-06, was Fabric Warehouse), the
    same local SQLite DB_PATH as execute_query() in local/test mode (see
    get_fabric_connection()). dict(zip(columns, row)) works unchanged
    against both a pyodbc row and a sqlite3.Row, so no backend branching
    is needed here the way execute_query() needs for Azure SQL. Additive
    only; execute_query() is untouched and still targets Azure SQL
    directly."""
    conn = get_fabric_connection()
    try:
        cursor = conn.execute(sql, params or [])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()
