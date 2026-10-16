"""
Test isolation for the whole tests/ suite (2026-10-15).

web/app.py and the intake notebook call load_dotenv() on import, which put
the real FABRIC_* service principal from .env into the environment: tests
that don't patch web.queries.recon_sql / recon_query then connected to the
real Fabric Warehouse and COMMITTED their UPDATEs / INSERTs there. pytest
loads this file before it imports any test module, so:

  - every FABRIC_*, AZURE_SQL_*, AZURE_CLAUDE_* and AZURE_BLOB_* variable is
    set to "" -- load_dotenv() never overrides a key that already exists, so
    .env can't fill them in again (a test that sets one itself still can);
  - outbound sockets raise on connect, except to localhost;
  - pyodbc.connect raises: the ODBC driver opens its sockets natively, below
    the Python socket module, so the socket guard alone would not stop it.

A test that needs one of these services must mock it.
"""

import os
import socket

_PREFIXES = ("FABRIC_", "AZURE_SQL_", "AZURE_CLAUDE_", "AZURE_BLOB_")
# Every such name the code or .env uses (also blanked when not set, so a later
# load_dotenv() can't add it).
_NAMES = (
    "AZURE_BLOB_CONNECTION_STRING", "AZURE_BLOB_DROPZONE_CONNECTION_STRING", "AZURE_BLOB_MAILBOX_CONNECTION_STRING",
    "AZURE_CLAUDE_API_KEY", "AZURE_CLAUDE_DEPLOYMENT", "AZURE_CLAUDE_ENDPOINT", "AZURE_CLAUDE_SONNET_DEPLOYMENT",
    "AZURE_SQL_DATABASE", "AZURE_SQL_PASSWORD", "AZURE_SQL_SERVER", "AZURE_SQL_USERNAME",
    "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET", "FABRIC_LAKEHOUSE_ID", "FABRIC_LAKEHOUSE_NAME", "FABRIC_SQLDB_ENDPOINT",
    "FABRIC_SQLDB_NAME", "FABRIC_SQL_ENDPOINT", "FABRIC_SQL_ENDPOINT_ID", "FABRIC_TENANT_ID", "FABRIC_WAREHOUSE_NAME",
    "FABRIC_WORKSPACE_ID",
)
for _name in set(_NAMES) | {k for k in os.environ if k.startswith(_PREFIXES)}:
    os.environ[_name] = ""

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _is_local(address) -> bool:
    if not isinstance(address, tuple):  # AF_UNIX path
        return True
    host = str(address[0]).lower()
    return host in _LOCAL_HOSTS or host.startswith("127.")


def _guarded_connect(self, address):
    if not _is_local(address):
        raise RuntimeError(f"tests/conftest.py: outbound connection to {address!r} blocked -- mock the service")
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    if not _is_local(address):
        raise RuntimeError(f"tests/conftest.py: outbound connection to {address!r} blocked -- mock the service")
    return _real_connect_ex(self, address)


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex

try:
    import pyodbc

    def _blocked_pyodbc_connect(*_args, **_kwargs):
        raise RuntimeError("tests/conftest.py: pyodbc.connect blocked -- mock the database")

    pyodbc.connect = _blocked_pyodbc_connect
except ImportError:  # pragma: no cover
    pass
