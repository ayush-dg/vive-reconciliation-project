"""NetSuite REST client (record/v1 + SuiteQL), OAuth 1.0a TBA -- sandbox or production.

WHICH ACCOUNT is decided by ONE setting, NETSUITE_ACCOUNT_ID:
  7321761-sb1  (or 7321761_SB1)   -> the sandbox,   credentials from SANDBOX_*
  7321761                          -> production,    credentials from PROD_*
  anything else                    -> refused
Each credential set is SANDBOX_/PROD_ + ACCOUNT_ID, CONSUMER_KEY, CONSUMER_SECRET,
TOKEN_ID, TOKEN_SECRET -- never from code. The chosen set's own *_ACCOUNT_ID must
equal NETSUITE_ACCOUNT_ID, so sandbox keys can never be sent to production (or the
reverse). With NETSUITE_ACCOUNT_ID unset the client falls back to SANDBOX_ACCOUNT_ID:
an unconfigured setup can only ever mean the sandbox.

READING works in either account. WRITING to production additionally needs
NETSUITE_PROD_WRITES_ENABLED=true, and every write -- either account -- is checked by
src/netsuite/guard.py (our custom fields only).

NetSuite writes the same account id two different ways, and mixing them
up produces a misleading 401 rather than an error naming the mismatch:
  - the REST DOMAIN wants it lowercase with hyphens:  7321761-sb1
  - the OAuth1 REALM wants it uppercase with underscores:  7321761_SB1
(a production id is the same digits in both places). Both are derived here from the
one configured value, so they cannot drift apart.
"""
import logging
import os
import re
import time
from dataclasses import dataclass

import requests
from requests_oauthlib import OAuth1

from src.netsuite import guard

logger = logging.getLogger(__name__)

# <digits> then sb<digits>, either separator, either case. A bare
# "7321761" is production.
_SANDBOX_ID = re.compile(r"^(\d+)[-_]sb(\d+)$", re.IGNORECASE)
_PRODUCTION_ID = re.compile(r"^\d+$")

_CREDENTIAL_NAMES = ("ACCOUNT_ID", "CONSUMER_KEY", "CONSUMER_SECRET", "TOKEN_ID", "TOKEN_SECRET")

# Things that differ between the accounts but are not credentials. The exception list was
# created by hand in each account, so its table name is not the same (see
# writeback.fetch_exception_list_ids).
SANDBOX = "sandbox"
PRODUCTION = "production"
_EXCEPTION_LIST_TABLE = {SANDBOX: "customlist_exception", PRODUCTION: "customlist673"}

PROD_WRITES_FLAG = "NETSUITE_PROD_WRITES_ENABLED"

# SuiteQL returns at most 1000 rows per page.
SUITEQL_PAGE_SIZE = 1000
_RETRY_STATUSES = (429, 502, 503, 504)
_MAX_ATTEMPTS = 3
_TIMEOUT_SECONDS = 60


class NetSuiteConfigError(Exception):
    """Credentials missing, or the account id is not an unambiguous sandbox or production id."""


class NetSuiteAPIError(Exception):
    def __init__(self, status_code, message, body=None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class Environment:
    name: str            # SANDBOX or PRODUCTION
    account: str         # the id as written in the REST domain, e.g. 7321761-sb1 or 7321761
    realm: str           # the OAuth1 realm, e.g. 7321761_SB1 or 7321761
    prefix: str          # "SANDBOX" or "PROD": which credential set
    exception_list_table: str

    @property
    def is_production(self) -> bool:
        return self.name == PRODUCTION

    @property
    def label(self) -> str:
        return f"{self.name.upper()} {self.account}"


def derive_account_forms(raw_account_id: str) -> tuple:
    """Returns (domain_id, realm) for a SANDBOX account id, accepting the
    id in either form ('7321761-sb1' or '7321761_SB1'). Raises
    NetSuiteConfigError for anything that is not an unambiguous sandbox."""
    cleaned = (raw_account_id or "").strip()
    match = _SANDBOX_ID.match(cleaned)
    if not match:
        raise NetSuiteConfigError(
            f"{cleaned!r} is not an unambiguous sandbox id "
            "(expected e.g. '7321761-sb1' or '7321761_SB1')."
        )
    digits, sandbox_n = match.groups()
    return f"{digits}-sb{sandbox_n}", f"{digits}_SB{sandbox_n}"


def _clean(value) -> str:
    return (value or "").strip().strip('"').strip("'").strip()


def _classify(raw_account_id: str) -> Environment:
    """The environment a single account id means. Anything ambiguous is refused."""
    cleaned = _clean(raw_account_id)
    if _SANDBOX_ID.match(cleaned):
        domain, realm = derive_account_forms(cleaned)
        return Environment(SANDBOX, domain, realm, "SANDBOX", _EXCEPTION_LIST_TABLE[SANDBOX])
    if _PRODUCTION_ID.match(cleaned):
        return Environment(PRODUCTION, cleaned, cleaned, "PROD", _EXCEPTION_LIST_TABLE[PRODUCTION])
    raise NetSuiteConfigError(
        f"NETSUITE_ACCOUNT_ID={cleaned!r} is neither a sandbox id (e.g. 7321761-sb1) nor a production id "
        "(digits only, e.g. 7321761). Refusing to run."
    )


def resolve_environment(env=None):
    """(Environment, credentials) from the process environment (or `env`)."""
    env = os.environ if env is None else env
    selected = _clean(env.get("NETSUITE_ACCOUNT_ID")) or _clean(env.get("SANDBOX_ACCOUNT_ID"))
    if not selected:
        raise NetSuiteConfigError("NETSUITE_ACCOUNT_ID is not set (use the sandbox id, or the production id).")
    environment = _classify(selected)
    wanted = {name: f"{environment.prefix}_{name}" for name in _CREDENTIAL_NAMES}
    missing = [var for var in wanted.values() if not _clean(env.get(var))]
    if missing:
        raise NetSuiteConfigError(f"Missing env var(s) for {environment.label}: {', '.join(missing)}")
    own = _classify(env.get(wanted["ACCOUNT_ID"]))
    if (own.name, own.account.lower()) != (environment.name, environment.account.lower()):
        raise NetSuiteConfigError(
            f"NETSUITE_ACCOUNT_ID is {environment.label} but {wanted['ACCOUNT_ID']} is {own.label}. "
            "The credential set must belong to the account it is used for. Refusing to run.")
    return environment, {name: _clean(env.get(var)) for name, var in wanted.items()}


def production_writes_enabled() -> bool:
    return os.getenv(PROD_WRITES_FLAG, "").strip().lower() == "true"


class NetSuiteClient:
    def __init__(self, session=None):
        self.environment, creds = resolve_environment()
        self.domain_id = self.environment.account   # the REST domain (name kept: the logs use it)
        self.realm = self.environment.realm
        self.base_url = f"https://{self.domain_id}.suitetalk.api.netsuite.com/services/rest"
        self._auth = OAuth1(
            creds["CONSUMER_KEY"],
            client_secret=creds["CONSUMER_SECRET"],
            resource_owner_key=creds["TOKEN_ID"],
            resource_owner_secret=creds["TOKEN_SECRET"],
            signature_method="HMAC-SHA256",
            realm=self.realm,
        )
        self._session = session or requests.Session()

    def _require_writes_allowed(self):
        """Production is written to only when explicitly armed; the sandbox always may."""
        if self.environment.is_production and not production_writes_enabled():
            raise guard.WriteBlocked(
                f"production writes are off: {PROD_WRITES_FLAG} is not true ({self.environment.label})")

    def _request(self, method, url, **kwargs):
        """One HTTP call with a small retry on throttling/transient 5xx.
        Raises NetSuiteAPIError on any non-2xx final response -- the body
        is attached for diagnosis; credentials never appear in it."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            resp = self._session.request(
                method, url, auth=self._auth, timeout=_TIMEOUT_SECONDS, **kwargs
            )
            if resp.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            break
        if not resp.ok:
            raise NetSuiteAPIError(resp.status_code, resp.reason, resp.text[:2000])
        return resp

    def suiteql(self, query: str) -> list:
        """Runs a SuiteQL read and returns every row, paging until
        hasMore is false. Don't put FETCH/OFFSET in `query` -- paging is
        done through the limit/offset URL params."""
        rows, offset = [], 0
        while True:
            resp = self._request(
                "POST",
                f"{self.base_url}/query/v1/suiteql?limit={SUITEQL_PAGE_SIZE}&offset={offset}",
                headers={"Prefer": "transient", "Content-Type": "application/json"},
                json={"q": query},
            )
            payload = resp.json()
            rows.extend(payload.get("items", []))
            if not payload.get("hasMore"):
                return rows
            offset += SUITEQL_PAGE_SIZE

    def patch_record(self, record_type: str, record_id: str, body: dict) -> None:
        """PATCH fields onto an existing record. NetSuite answers 204.
        Refused (guard.WriteBlocked) unless every field is on the allowlist."""
        guard.check_patch(record_type, record_id, body)
        self._require_writes_allowed()
        self._request(
            "PATCH", f"{self.base_url}/record/v1/{record_type}/{record_id}",
            headers={"Content-Type": "application/json"}, json=body,
        )

    def create_record(self, record_type: str, body: dict) -> str:
        """POST a new record and return its internal id, taken from the
        Location header NetSuite sends back (it answers 204, no body).
        Refused (guard.WriteBlocked) for anything but an allowlisted Statement Line."""
        guard.check_create(record_type, body)
        self._require_writes_allowed()
        resp = self._request(
            "POST", f"{self.base_url}/record/v1/{record_type}",
            headers={"Content-Type": "application/json"}, json=body,
        )
        return resp.headers.get("Location", "").rstrip("/").rsplit("/", 1)[-1]

    def delete_record(self, record_type: str, record_id: str, statement_id: str = None) -> None:
        """DELETE a Statement Line this tool created. Refused unless the row is read
        first and found to belong to `statement_id`; bills and credits can never be deleted."""
        guard.check_delete(record_type, record_id, statement_id)
        self._require_writes_allowed()
        rows = self.suiteql(
            f"SELECT custrecord_sl_statement_id AS sid FROM {record_type} WHERE id = {int(record_id)}")
        if not rows:
            raise guard.WriteBlocked(f"Statement Line {record_id} not found; not deleted")
        guard.check_delete_target(rows[0].get("sid"), statement_id)
        self._request("DELETE", f"{self.base_url}/record/v1/{record_type}/{record_id}")

    def get_record_schema(self, record_type: str) -> dict:
        """JSON-schema metadata for a record type, including its custom
        fields. Used by the preflight to confirm fields exist."""
        resp = self._request(
            "GET",
            f"{self.base_url}/record/v1/metadata-catalog/{record_type}",
            headers={"Accept": "application/schema+json"},
        )
        return resp.json()
