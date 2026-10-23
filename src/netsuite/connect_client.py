"""Read-only NetSuite SuiteAnalytics Connect client (ODBC, NetSuite2.com).

Reads PRODUCTION NetSuite -- vendors, vendor bills, vendor credits -- for
matching and the NetSuite search, as a live alternative to the nightly
Fabric copy (bronze.netsuite_*). Measured 2026-10-23 against prod from a
workstation: ~9 s to log in, then a vendor's whole bill history in seconds
(AsTech's 241,312 bills in ~17-30 s), 6 connections at once without a
refusal.

Login is Token-Based Authentication over ODBC: every NEW connection needs a
freshly signed one-time password (account&consumer&token&nonce&timestamp,
HMAC-SHA256 over consumer_secret&token_secret). A signed password can't be
reused, but an open connection stays logged in -- so ConnectClient keeps its
connection and reuses it for up to NETSUITE_CONNECT_MAX_AGE_SECONDS (default
30 min), then opens a fresh one. A query that fails on a dropped connection
is retried once on a new connection.

Read-only twice over: SuiteAnalytics Connect itself only reads, and query()
refuses anything that isn't a single SELECT/WITH statement.

Settings (environment):
  NETSUITE_CONNECT_ACCOUNT_ID, NETSUITE_CONNECT_CONSUMER_KEY,
  NETSUITE_CONNECT_CONSUMER_SECRET, NETSUITE_CONNECT_TOKEN_ID,
  NETSUITE_CONNECT_TOKEN_SECRET, NETSUITE_CONNECT_ROLE_ID  -- required
  NETSUITE_CONNECT_HOST        default <account>.connect.api.netsuite.com
  NETSUITE_CONNECT_DRIVER      default: the name the Docker image registers
                               (Linux) / the Windows installer's name
  NETSUITE_CONNECT_TRUSTSTORE  default: the driver's ca4.cer (Linux) / system
  NETSUITE_CONNECT_MAX_AGE_SECONDS  default 1800
"""
import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import sys
import threading
import time

logger = logging.getLogger(__name__)

LINUX_DRIVER = "NetSuite ODBC Drivers 9.0"      # registered in the Dockerfile
WINDOWS_DRIVER = "NetSuite Drivers 64bit"        # what the Windows installer registers
LINUX_TRUSTSTORE = "/opt/netsuite/odbcclient/cert/ca4.cer"
DEFAULT_MAX_AGE_SECONDS = 1800
LOGIN_TIMEOUT_SECONDS = 60

_REQUIRED = ("ACCOUNT_ID", "CONSUMER_KEY", "CONSUMER_SECRET", "TOKEN_ID", "TOKEN_SECRET", "ROLE_ID")
_PREFIX = "NETSUITE_CONNECT_"


class ConnectConfigError(Exception):
    """A required NETSUITE_CONNECT_* setting is missing or invalid."""


class ReadOnlyError(Exception):
    """query() was given something other than a single SELECT statement."""


def account_forms(raw_account_id: str) -> tuple:
    """(host_form, realm_form) of an account id given in either form:
    '7321761' -> ('7321761', '7321761'); '7321761_SB1' -> ('7321761-sb1', '7321761_SB1')."""
    cleaned = (raw_account_id or "").strip()
    if not re.fullmatch(r"\d+([-_][A-Za-z0-9]+)?", cleaned):
        raise ConnectConfigError(f"{_PREFIX}ACCOUNT_ID {cleaned!r} is not a NetSuite account id")
    return cleaned.lower().replace("_", "-"), cleaned.upper().replace("-", "_")


def load_config(env=None) -> dict:
    """The connection settings from the environment; raises ConnectConfigError
    naming every missing required one."""
    env = os.environ if env is None else env
    missing = [_PREFIX + k for k in _REQUIRED if not (env.get(_PREFIX + k) or "").strip()]
    if missing:
        raise ConnectConfigError("Missing setting(s): " + ", ".join(missing))
    host_form, realm_form = account_forms(env[_PREFIX + "ACCOUNT_ID"])
    role_id = env[_PREFIX + "ROLE_ID"].strip()
    if not role_id.isdigit():
        raise ConnectConfigError(f"{_PREFIX}ROLE_ID must be a number")
    windows = sys.platform == "win32"
    try:
        max_age = int(env.get(_PREFIX + "MAX_AGE_SECONDS") or DEFAULT_MAX_AGE_SECONDS)
    except ValueError:
        raise ConnectConfigError(f"{_PREFIX}MAX_AGE_SECONDS must be a whole number of seconds")
    return {
        "account": realm_form,
        "host": (env.get(_PREFIX + "HOST") or "").strip() or f"{host_form}.connect.api.netsuite.com",
        "consumer_key": env[_PREFIX + "CONSUMER_KEY"].strip(),
        "consumer_secret": env[_PREFIX + "CONSUMER_SECRET"].strip(),
        "token_id": env[_PREFIX + "TOKEN_ID"].strip(),
        "token_secret": env[_PREFIX + "TOKEN_SECRET"].strip(),
        "role_id": role_id,
        "driver": (env.get(_PREFIX + "DRIVER") or "").strip() or (WINDOWS_DRIVER if windows else LINUX_DRIVER),
        "truststore": (env.get(_PREFIX + "TRUSTSTORE") or "").strip() or ("system" if windows else LINUX_TRUSTSTORE),
        "max_age_seconds": max_age,
    }


def build_password(config: dict, nonce: str = None, timestamp: str = None) -> str:
    """The one-time TBA password for ONE new connection. Never reuse it."""
    nonce = nonce or secrets.token_hex(10)
    timestamp = timestamp or str(int(time.time()))
    base = "&".join([config["account"], config["consumer_key"], config["token_id"], nonce, timestamp])
    key = f"{config['consumer_secret']}&{config['token_secret']}".encode()
    signature = base64.b64encode(hmac.new(key, base.encode(), hashlib.sha256).digest()).decode()
    return f"{base}&{signature}&HMAC-SHA256"


def connection_string(config: dict, password: str) -> str:
    return (
        f"DRIVER={{{config['driver']}}};Host={config['host']};Port=1708;Encrypted=1;"
        f"AllowSinglePacketLogout=1;Truststore={config['truststore']};SDSN=NetSuite2.com;StaticSchema=1;"
        f"UID=TBA;PWD={password};CustomProperties=AccountID={config['account']};RoleID={config['role_id']}"
    )


_COMMENT = re.compile(r"(--[^\n]*)|(/\*.*?\*/)", re.S)


def check_read_only(sql: str) -> None:
    """Raises ReadOnlyError unless sql is one SELECT (or WITH ... SELECT)."""
    stripped = _COMMENT.sub(" ", sql or "").strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", stripped):
        raise ReadOnlyError("Only SELECT queries are allowed")
    if ";" in stripped:
        raise ReadOnlyError("Only one statement per query")


class ConnectClient:
    """One reusable Connect connection. Thread-safe: queries on one client run
    one at a time (an ODBC connection must not run two at once)."""

    def __init__(self, config: dict = None, connect_fn=None, clock=time.monotonic):
        self.config = config or load_config()
        self._connect_fn = connect_fn
        self._clock = clock
        self._lock = threading.Lock()
        self._conn = None
        self._opened_at = None
        self.logins = 0
        self.last_login_seconds = None

    # -- connection handling ------------------------------------------------
    def _open(self):
        connect = self._connect_fn
        if connect is None:
            import pyodbc
            connect = pyodbc.connect
        started = self._clock()
        conn = connect(connection_string(self.config, build_password(self.config)), timeout=LOGIN_TIMEOUT_SECONDS)
        self.last_login_seconds = round(self._clock() - started, 2)
        self.logins += 1
        logger.info("NetSuite Connect login #%d took %.1fs", self.logins, self.last_login_seconds)
        self._conn, self._opened_at = conn, self._clock()

    def _close_quietly(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                logger.warning("closing a NetSuite Connect connection failed (ignored)")
        self._conn, self._opened_at = None, None

    def _connection(self):
        too_old = self._opened_at is not None and self._clock() - self._opened_at >= self.config["max_age_seconds"]
        if self._conn is None or too_old:
            self._close_quietly()
            self._open()
        return self._conn

    # -- queries ------------------------------------------------------------
    def query(self, sql: str, params=None) -> list:
        """Rows as dicts with lowercase column names. Retries once on a fresh
        connection if the first attempt fails (e.g. a dropped connection)."""
        check_read_only(sql)
        with self._lock:
            for attempt in (1, 2):
                try:
                    cur = self._connection().cursor()
                    cur.execute(sql, list(params or []))
                    cols = [d[0].lower() for d in cur.description]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
                except ReadOnlyError:
                    raise
                except Exception:
                    self._close_quietly()
                    if attempt == 2:
                        raise
                    logger.warning("NetSuite Connect query failed; retrying once on a new connection", exc_info=True)

    def close(self) -> None:
        with self._lock:
            self._close_quietly()


_shared = None
_shared_lock = threading.Lock()


def get_shared_client() -> ConnectClient:
    """The process-wide client (the web app keeps one connection open)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = ConnectClient()
        return _shared


def installed_drivers() -> list:
    """ODBC driver names registered on this machine ([] if pyodbc is missing)."""
    try:
        import pyodbc
        return list(pyodbc.drivers())
    except Exception:
        return []
