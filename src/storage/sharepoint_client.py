"""
sharepoint_client.py

Archives a vendor statement PDF to a SharePoint document library through
Microsoft Graph (app-only, client-credentials), for the NetSuite bill link
(src/netsuite/writeback.py resolve_pdf_link). Called from
notebooks/01_document_intake.py Step 8b for RECONCILIATION statements.

Path: {SHAREPOINT_BASE_FOLDER}/{vendor_slug}/{yyyy}/{mm}/{original_stem}__{hash12}.pdf
-- the content hash in the name makes a name clash (HTTP 409) mean "these
exact bytes are already archived", so the existing file is reused, never
replaced.

Rules:
  - Never raises: every problem becomes SharePointUploadResult(status="failed").
  - Never deletes or overwrites a file (conflictBehavior=fail). The only
    DELETE ever sent cancels this module's own unfinished upload session.
  - Never creates the base folder: a missing base folder fails the upload.
    Graph creates the vendor/year/month folders below it on upload.
  - Settings are SHAREPOINT_* only, read at call time; the credential is an
    explicit ClientSecretCredential (never Default/EnvironmentCredential).
  - No secret or token ever appears in a result, an error or the output
    (this module prints nothing).
  - Until VIVE approves the real folder, SHAREPOINT_BASE_FOLDER must end in
    /_dev_test unless SHAREPOINT_ALLOW_LIVE_FOLDER=true.
"""

import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import quote

from src.storage.blob_client import _slugify_vendor_name

FLAG = "SHAREPOINT_ARCHIVE_ENABLED"
ALLOW_LIVE_FOLDER = "SHAREPOINT_ALLOW_LIVE_FOLDER"
REQUIRED = (
    "SHAREPOINT_TENANT_ID", "SHAREPOINT_CLIENT_ID", "SHAREPOINT_CLIENT_SECRET",
    "SHAREPOINT_SITE_HOSTNAME", "SHAREPOINT_SITE_PATH", "SHAREPOINT_LIBRARY", "SHAREPOINT_BASE_FOLDER",
)
DEV_FOLDER = "_dev_test"

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "https://graph.microsoft.com/.default"
SIMPLE_UPLOAD_MAX_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 10 * 320 * 1024          # 3,276,800 -- Graph needs a multiple of 320 KiB
UPLOAD_BUDGET_SECONDS = 300
METADATA_TIMEOUT = 60
CHUNK_TIMEOUT = 120
MAX_RETRIES = 3
MAX_RETRY_AFTER = 30
MAX_PATH_CHARS = 400
MAX_STEM_CHARS = 80
MIN_STEM_CHARS = 10
MAX_ERROR_CHARS = 300

_ILLEGAL_NAME_CHARS = re.compile(r'["*:<>?/\\|#%\x00-\x1f]')


@dataclass
class SharePointUploadResult:
    status: str                 # "uploaded" | "existing" | "failed" | "skipped"
    web_url: str = None
    item_id: str = None
    drive_id: str = None
    path: str = None
    error: str = None


class SharePointConfigError(Exception):
    pass


class SharePointAuthError(Exception):
    pass


class SharePointUploadError(Exception):
    pass


class _BudgetExceeded(Exception):
    pass


def sharepoint_enabled() -> bool:
    """True only when SHAREPOINT_ARCHIVE_ENABLED is the literal "true"."""
    return os.getenv(FLAG, "").strip().lower() == "true"


def read_settings() -> tuple:
    """(settings, None) when usable, else (None, reason). The reason names
    settings, never their values. Does not look at the on/off flag."""
    values = {name: (os.getenv(name) or "").strip() for name in REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        return None, f"missing setting(s): {', '.join(missing)}"
    base = values["SHAREPOINT_BASE_FOLDER"].strip("/")
    allow_live = os.getenv(ALLOW_LIVE_FOLDER, "").strip().lower() == "true"
    if base.split("/")[-1] != DEV_FOLDER and not allow_live:
        return None, (f"SHAREPOINT_BASE_FOLDER is not a {DEV_FOLDER} folder "
                      f"(set {ALLOW_LIVE_FOLDER}=true only once the real folder is approved)")
    return {
        "tenant_id": values["SHAREPOINT_TENANT_ID"],
        "client_id": values["SHAREPOINT_CLIENT_ID"],
        "client_secret": values["SHAREPOINT_CLIENT_SECRET"],
        "site_hostname": values["SHAREPOINT_SITE_HOSTNAME"].strip("/"),
        "site_path": "/" + values["SHAREPOINT_SITE_PATH"].strip("/"),
        "library": values["SHAREPOINT_LIBRARY"],
        "base_folder": base,
    }, None


def safe_stem(original_filename: str, limit: int = MAX_STEM_CHARS) -> str:
    """The file name without extension, made legal for SharePoint: illegal
    characters become "_", leading/trailing spaces and dots are trimmed, and
    it is cut to `limit` characters."""
    stem = os.path.splitext(os.path.basename(original_filename or ""))[0]
    stem = _ILLEGAL_NAME_CHARS.sub("_", stem).strip(" .")
    stem = stem[:limit].strip(" .")
    return stem or "statement"


def build_path(base_folder: str, vendor_name: str, year, month, original_filename: str,
               document_hash: str) -> str:
    """Library-relative path, kept within MAX_PATH_CHARS by shortening the
    file stem. Raises SharePointUploadError when it can't fit."""
    folder = f"{base_folder.strip('/')}/{_slugify_vendor_name(vendor_name)}/{int(year):04d}/{int(month):02d}"
    suffix = f"__{document_hash[:12].lower()}.pdf"
    room = MAX_PATH_CHARS - len(folder) - 1 - len(suffix)
    if room < MIN_STEM_CHARS:
        raise SharePointUploadError("path too long for SharePoint")
    return f"{folder}/{safe_stem(original_filename, min(MAX_STEM_CHARS, room))}{suffix}"


_CREDENTIALS = {}


def _default_token_provider(settings: dict) -> Callable[[], str]:
    """Explicit ClientSecretCredential, one per (tenant, client) per process."""
    def provide() -> str:
        key = (settings["tenant_id"], settings["client_id"])
        credential = _CREDENTIALS.get(key)
        if credential is None:
            from azure.identity import ClientSecretCredential
            credential = ClientSecretCredential(
                tenant_id=settings["tenant_id"], client_id=settings["client_id"],
                client_secret=settings["client_secret"])
            _CREDENTIALS[key] = credential
        return credential.get_token(SCOPE).token
    return provide


def _default_http():
    import requests
    session = requests.Session()
    return session.request


class SharePointArchiveClient:
    """http(method, url, headers=..., data=..., json=..., timeout=...) returns
    a response with .status_code, .headers, .json() and .text (requests'
    shape). Both http and token_provider are injectable for tests; sleep and
    clock too, so retries and the time budget are testable."""

    def __init__(self, settings: dict, http: Optional[Callable] = None,
                 token_provider: Optional[Callable[[], str]] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self._http = http
        self._token_provider = token_provider or _default_token_provider(settings)
        self._sleep = sleep
        self._clock = clock
        self._token = None
        self._deadline = None

    # ------------------------------------------------------------------ public
    def upload_statement_pdf(self, pdf_path: str, *, vendor_name: str, year, month,
                             document_hash: str, original_filename: str) -> SharePointUploadResult:
        drive_id = path = None
        try:
            if not document_hash:
                raise SharePointUploadError("document hash is empty")
            if not os.path.isfile(pdf_path):
                raise SharePointUploadError("PDF file not found")
            try:
                path = build_path(self.settings["base_folder"], vendor_name, year, month,
                                  original_filename, document_hash)
            except (TypeError, ValueError):
                raise SharePointUploadError("invalid year/month")
            self._deadline = self._clock() + UPLOAD_BUDGET_SECONDS
            self._token = self._get_token()
            drive_id = self._resolve_drive()
            self._check_base_folder(drive_id)
            size = os.path.getsize(pdf_path)
            if size <= SIMPLE_UPLOAD_MAX_BYTES:
                return self._simple_upload(drive_id, path, pdf_path, size)
            return self._session_upload(drive_id, path, pdf_path, size)
        except _BudgetExceeded:
            return self._failed("timeout (upload took longer than the time budget)", drive_id, path)
        except (SharePointConfigError, SharePointAuthError, SharePointUploadError) as exc:
            return self._failed(str(exc), drive_id, path)
        except Exception as exc:  # never raise to the caller; the type only, since a
            # transport error's text can carry the pre-authenticated upload URL
            return self._failed(f"unexpected {type(exc).__name__}", drive_id, path)

    # ----------------------------------------------------------------- helpers
    def _redact(self, text: str) -> str:
        text = str(text)
        for secret in (self.settings.get("client_secret"), self._token):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text[:MAX_ERROR_CHARS]

    def _failed(self, error: str, drive_id=None, path=None) -> SharePointUploadResult:
        return SharePointUploadResult("failed", drive_id=drive_id, path=path, error=self._redact(error))

    def _get_token(self) -> str:
        try:
            token = self._token_provider()
        except Exception as exc:
            raise SharePointAuthError(f"authentication failed ({type(exc).__name__})")
        if not token:
            raise SharePointAuthError("authentication failed (empty token)")
        return token

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _check_budget(self):
        if self._deadline is not None and self._clock() > self._deadline:
            raise _BudgetExceeded()

    def _send(self, method: str, url: str, *, headers=None, data=None, json=None, timeout=METADATA_TIMEOUT):
        """One request with retries: 429/503 honour Retry-After (capped), other
        5xx and transport errors back off briefly. Returns the last response."""
        http = self._http or _default_http()
        self._http = http
        for attempt in range(MAX_RETRIES + 1):
            self._check_budget()
            try:
                response = http(method, url, headers=headers, data=data, json=json, timeout=timeout)
            except Exception as exc:
                if attempt == MAX_RETRIES:
                    raise SharePointUploadError(f"{method} failed ({type(exc).__name__})")
                self._sleep(2 ** attempt)
                continue
            status = response.status_code
            if status in (429, 503) and attempt < MAX_RETRIES:
                self._sleep(self._retry_after(response, attempt))
                continue
            if status >= 500 and attempt < MAX_RETRIES:
                self._sleep(2 ** attempt)
                continue
            return response
        return response

    @staticmethod
    def _retry_after(response, attempt: int) -> float:
        try:
            value = float((response.headers or {}).get("Retry-After"))
        except (TypeError, ValueError):
            value = 2 ** attempt
        return max(0.0, min(value, MAX_RETRY_AFTER))

    def _error(self, what: str, response) -> SharePointUploadError:
        code = ""
        try:
            code = (response.json() or {}).get("error", {}).get("code", "")
        except Exception:
            pass
        return SharePointUploadError(f"{what} -> HTTP {response.status_code}{(' ' + code) if code else ''}")

    @staticmethod
    def _q(path: str) -> str:
        return quote(path, safe="/")

    def _resolve_drive(self) -> str:
        s = self.settings
        site = self._send("GET", f"{GRAPH}/sites/{s['site_hostname']}:{self._q(s['site_path'])}", headers=self._auth())
        if site.status_code != 200:
            raise self._error("site lookup", site)
        site_id = site.json()["id"]
        drives = self._send("GET", f"{GRAPH}/sites/{site_id}/drives?$select=id,name", headers=self._auth())
        if drives.status_code != 200:
            raise self._error("library lookup", drives)
        for drive in drives.json().get("value", []):
            if drive.get("name") == s["library"]:
                return drive["id"]
        raise SharePointConfigError("library not found on the site")

    def _check_base_folder(self, drive_id: str):
        base = self.settings["base_folder"]
        r = self._send("GET", f"{GRAPH}/drives/{drive_id}/root:/{self._q(base)}?$select=id,folder",
                       headers=self._auth())
        if r.status_code == 404:
            raise SharePointConfigError("base folder missing (it is never created automatically)")
        if r.status_code != 200:
            raise self._error("base folder lookup", r)
        if "folder" not in (r.json() or {}):
            raise SharePointConfigError("base folder path is not a folder")

    def _item_result(self, status: str, item: dict, drive_id: str, path: str) -> SharePointUploadResult:
        if not item.get("webUrl") or not item.get("id"):
            raise SharePointUploadError("upload response had no webUrl/id")
        return SharePointUploadResult(status, web_url=item["webUrl"], item_id=item["id"],
                                      drive_id=drive_id, path=path)

    def _existing(self, drive_id: str, path: str, size: int) -> SharePointUploadResult:
        """A 409: the same name exists. The name carries the content hash, so
        the same size means the same file -- reuse it."""
        r = self._send("GET", f"{GRAPH}/drives/{drive_id}/root:/{self._q(path)}?$select=id,webUrl,size",
                       headers=self._auth())
        if r.status_code != 200:
            raise self._error("existing file lookup", r)
        item = r.json() or {}
        if item.get("size") != size:
            raise SharePointUploadError("name exists with different size")
        return self._item_result("existing", item, drive_id, path)

    def _simple_upload(self, drive_id: str, path: str, pdf_path: str, size: int) -> SharePointUploadResult:
        with open(pdf_path, "rb") as f:
            data = f.read()
        r = self._send("PUT", f"{GRAPH}/drives/{drive_id}/root:/{self._q(path)}:/content"
                              "?@microsoft.graph.conflictBehavior=fail",
                       headers={**self._auth(), "Content-Type": "application/pdf"}, data=data,
                       timeout=CHUNK_TIMEOUT)
        if r.status_code in (200, 201):
            return self._item_result("uploaded", r.json() or {}, drive_id, path)
        if r.status_code == 409:
            return self._existing(drive_id, path, size)
        raise self._error("upload", r)

    def _session_upload(self, drive_id: str, path: str, pdf_path: str, size: int) -> SharePointUploadResult:
        r = self._send("POST", f"{GRAPH}/drives/{drive_id}/root:/{self._q(path)}:/createUploadSession",
                       headers=self._auth(), json={"item": {"@microsoft.graph.conflictBehavior": "fail"}})
        if r.status_code == 409:
            return self._existing(drive_id, path, size)
        if r.status_code != 200:
            raise self._error("upload session", r)
        upload_url = (r.json() or {}).get("uploadUrl")
        if not upload_url:
            raise SharePointUploadError("upload session had no uploadUrl")
        try:
            with open(pdf_path, "rb") as f:
                start = 0
                while start < size:
                    chunk = f.read(CHUNK_BYTES)
                    end = start + len(chunk) - 1
                    # The uploadUrl is pre-authenticated: no bearer token is sent to it.
                    r = self._send("PUT", upload_url, data=chunk, timeout=CHUNK_TIMEOUT, headers={
                        "Content-Length": str(len(chunk)), "Content-Range": f"bytes {start}-{end}/{size}"})
                    if r.status_code == 202:
                        start = end + 1
                        continue
                    if r.status_code in (200, 201):
                        return self._item_result("uploaded", r.json() or {}, drive_id, path)
                    if r.status_code == 409:
                        self._cancel(upload_url)
                        return self._existing(drive_id, path, size)
                    raise self._error("upload chunk", r)
            raise SharePointUploadError("upload session ended without a file")
        except Exception:
            self._cancel(upload_url)
            raise

    def _cancel(self, upload_url: str):
        """Cancels this module's own unfinished upload session -- the only
        DELETE this module ever sends. Removes no file."""
        try:
            http = self._http or _default_http()
            http("DELETE", upload_url, headers=None, data=None, json=None, timeout=METADATA_TIMEOUT)
        except Exception:
            pass
