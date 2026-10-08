"""Sandbox-only NetSuite REST client (record/v1 + SuiteQL), OAuth 1.0a TBA.

Credentials come from env vars -- SANDBOX_ACCOUNT_ID, SANDBOX_CONSUMER_KEY,
SANDBOX_CONSUMER_SECRET, SANDBOX_TOKEN_ID, SANDBOX_TOKEN_SECRET -- never
from code.

NetSuite writes the same account id two different ways, and mixing them
up produces a misleading 401 rather than an error naming the mismatch:
  - the REST DOMAIN wants it lowercase with hyphens:  7321761-sb1
  - the OAuth1 REALM wants it uppercase with underscores:  7321761_SB1
Both are derived here from the one configured value (accepted in either
form), so they cannot drift apart.

This client refuses to be built for anything that is not an unambiguous
sandbox id (<digits>-sb<digits>). There is deliberately no flag to
override that -- pointing write-back at production needs an explicit code
change, not a config slip.
"""
import logging
import os
import re
import time

import requests
from requests_oauthlib import OAuth1

logger = logging.getLogger(__name__)

# <digits> then sb<digits>, either separator, either case. A bare
# "7321761" (production) deliberately does not match.
_SANDBOX_ID = re.compile(r"^(\d+)[-_]sb(\d+)$", re.IGNORECASE)

_ENV_VARS = (
    "SANDBOX_ACCOUNT_ID",
    "SANDBOX_CONSUMER_KEY",
    "SANDBOX_CONSUMER_SECRET",
    "SANDBOX_TOKEN_ID",
    "SANDBOX_TOKEN_SECRET",
)

# SuiteQL returns at most 1000 rows per page.
SUITEQL_PAGE_SIZE = 1000
_RETRY_STATUSES = (429, 502, 503, 504)
_MAX_ATTEMPTS = 3
_TIMEOUT_SECONDS = 60


class NetSuiteConfigError(Exception):
    """Credentials missing, or the account id is not an unambiguous sandbox."""


class NetSuiteAPIError(Exception):
    def __init__(self, status_code, message, body=None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.body = body


def derive_account_forms(raw_account_id: str) -> tuple:
    """Returns (domain_id, realm) for a sandbox account id, accepting the
    id in either form ('7321761-sb1' or '7321761_SB1'). Raises
    NetSuiteConfigError for anything that is not an unambiguous sandbox."""
    cleaned = (raw_account_id or "").strip()
    match = _SANDBOX_ID.match(cleaned)
    if not match:
        raise NetSuiteConfigError(
            f"SANDBOX_ACCOUNT_ID={cleaned!r} is not an unambiguous sandbox id "
            "(expected e.g. '7321761-sb1' or '7321761_SB1'). Refusing to run."
        )
    digits, sandbox_n = match.groups()
    return f"{digits}-sb{sandbox_n}", f"{digits}_SB{sandbox_n}"


def _read_credentials() -> dict:
    missing = [name for name in _ENV_VARS if not os.getenv(name)]
    if missing:
        raise NetSuiteConfigError(f"Missing env var(s): {', '.join(missing)}")
    return {name: os.environ[name].strip() for name in _ENV_VARS}


class NetSuiteClient:
    def __init__(self, session=None):
        creds = _read_credentials()
        self.domain_id, self.realm = derive_account_forms(creds["SANDBOX_ACCOUNT_ID"])
        self.base_url = f"https://{self.domain_id}.suitetalk.api.netsuite.com/services/rest"
        self._auth = OAuth1(
            creds["SANDBOX_CONSUMER_KEY"],
            client_secret=creds["SANDBOX_CONSUMER_SECRET"],
            resource_owner_key=creds["SANDBOX_TOKEN_ID"],
            resource_owner_secret=creds["SANDBOX_TOKEN_SECRET"],
            signature_method="HMAC-SHA256",
            realm=self.realm,
        )
        self._session = session or requests.Session()

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
        """PATCH fields onto an existing record. NetSuite answers 204."""
        self._request(
            "PATCH", f"{self.base_url}/record/v1/{record_type}/{record_id}",
            headers={"Content-Type": "application/json"}, json=body,
        )

    def create_record(self, record_type: str, body: dict) -> str:
        """POST a new record and return its internal id, taken from the
        Location header NetSuite sends back (it answers 204, no body)."""
        resp = self._request(
            "POST", f"{self.base_url}/record/v1/{record_type}",
            headers={"Content-Type": "application/json"}, json=body,
        )
        return resp.headers.get("Location", "").rstrip("/").rsplit("/", 1)[-1]

    def delete_record(self, record_type: str, record_id: str) -> None:
        """DELETE a record. Used only to undo Statement Lines this tool created."""
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
