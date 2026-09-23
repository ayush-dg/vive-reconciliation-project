"""
blob_client.py

Azure Blob Storage client for permanent vendor-statement PDF archival
(upload_pdf) and for downloading newly-landed PDFs out of the auto-intake
dropzone container (download_pdf -- see web/routers/intake_trigger.py).
See docs/VIVE_Implementation_Context.md Section 4, Phase 2, "Object
storage (Blob)".

Path convention: {vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf -- keyed on
the same SHA-256 document_hash already computed for extraction caching
(RULE-02), so re-uploading the same PDF always lands on the same blob path
instead of creating a duplicate.

Never raises -- a blob upload/download failure must not crash the caller.
Callers get None/False back on any failure (missing config, missing file,
network/auth error) and are expected to log and continue.
"""

import os
import re
from typing import Callable, Optional
from urllib.parse import urlparse


def _slugify_vendor_name(vendor_name: Optional[str]) -> str:
    """Lowercase, alphanumeric-and-underscore-only vendor slug for blob paths."""
    slug = re.sub(r"[^a-z0-9]+", "_", (vendor_name or "").lower()).strip("_")
    return slug or "unknown_vendor"


def _parse_blob_url(blob_url: str):
    """Splits a blob URL's path into (container_name, blob_name). Raises
    ValueError if the URL has no distinct container/blob segments."""
    path = urlparse(blob_url).path.lstrip("/")
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"could not parse container/blob from URL: {blob_url}")
    return parts[0], parts[1]


class BlobStorageClient:
    """
    transport: optional injectable callable for testing uploads. Signature:
        (blob_path, pdf_path, metadata, container_name, connection_string)
            -> (success: bool, blob_url: Optional[str], error: Optional[str])
    download_transport: optional injectable callable for testing downloads.
    Signature:
        (container_name, blob_name, dest_path, connection_string)
            -> (success: bool, error: Optional[str])
    If either is None, uses the real azure-storage-blob SDK (imported
    lazily, only on the real upload/download path, so tests never require
    it installed).
    """

    def __init__(
        self,
        container_name: str = "vendor-statements",
        connection_string_env_var: str = "AZURE_BLOB_CONNECTION_STRING",
        transport: Optional[Callable] = None,
        download_transport: Optional[Callable] = None,
    ):
        self.container_name = container_name
        self.connection_string_env_var = connection_string_env_var
        self.connection_string = os.environ.get(connection_string_env_var)
        self._transport = transport
        self._download_transport = download_transport

    def upload_pdf(
        self,
        pdf_path: str,
        vendor_name: Optional[str],
        year,
        month,
        document_hash: str,
        original_filename: Optional[str] = None,
        uploaded_by: Optional[str] = None,
    ) -> Optional[str]:
        """
        Uploads pdf_path to {vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf
        in the configured container. Returns the blob URL on success, or
        None on any failure -- never raises.
        """
        if not self.connection_string:
            print(f"[blob_client] Skipping upload -- {self.connection_string_env_var} not set")
            return None

        if not document_hash:
            print("[blob_client] Skipping upload -- document_hash is required")
            return None

        if not os.path.isfile(pdf_path):
            print(f"[blob_client] Skipping upload -- file not found: {pdf_path}")
            return None

        try:
            blob_path = f"{_slugify_vendor_name(vendor_name)}/{int(year):04d}/{int(month):02d}/{document_hash}.pdf"
        except (TypeError, ValueError) as e:
            print(f"[blob_client] Skipping upload -- invalid year/month ({year!r}/{month!r}): {e}")
            return None

        metadata = {
            "original_filename": original_filename or os.path.basename(pdf_path),
            "vendor_name": vendor_name or "",
            "uploaded_by": uploaded_by or "",
        }

        try:
            if self._transport:
                success, url, error = self._transport(
                    blob_path, pdf_path, metadata, self.container_name, self.connection_string
                )
            else:
                success, url, error = self._real_upload(blob_path, pdf_path, metadata)
        except Exception as e:
            print(f"[blob_client] Unexpected error uploading {blob_path}: {e}")
            return None

        if not success:
            print(f"[blob_client] Upload failed for {blob_path}: {error}")
            return None

        return url

    def _real_upload(self, blob_path: str, pdf_path: str, metadata: dict):
        try:
            from azure.storage.blob import BlobServiceClient

            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            container_client = service_client.get_container_client(self.container_name)
            blob_client = container_client.get_blob_client(blob_path)

            with open(pdf_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True, metadata=metadata)

            return True, blob_client.url, None
        except Exception as e:
            return False, None, str(e)

    def list_pdf_blobs(self) -> list:
        """
        Lists PDF blob names currently in the configured container. Used by
        the dropzone polling watcher (web/worker.py) to find newly-landed
        statements without needing Event Grid. Returns [] on any failure
        (missing config, network/auth error) -- never raises.
        """
        if not self.connection_string:
            return []
        try:
            from azure.storage.blob import BlobServiceClient

            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            container_client = service_client.get_container_client(self.container_name)
            return [b.name for b in container_client.list_blobs() if b.name.lower().endswith(".pdf")]
        except Exception as e:
            print(f"[blob_client] Failed to list blobs in {self.container_name}: {e}")
            return []

    def get_blob_metadata_map(self, prefix: Optional[str] = None) -> dict:
        """
        Returns {blob_name: {"metadata": {...}, "etag": str}} for every PDF
        blob in the configured container (optionally scoped to prefix) --
        one listing call, metadata included, no per-blob downloads. Used by
        the "Sync to Webapp" mailbox-ingest flow (web/routers/mailbox_sync.py)
        to decide what needs processing without downloading anything first.
        Returns {} on any failure -- never raises.
        """
        if not self.connection_string:
            return {}
        try:
            from azure.storage.blob import BlobServiceClient

            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            container_client = service_client.get_container_client(self.container_name)
            result = {}
            for b in container_client.list_blobs(name_starts_with=prefix, include=["metadata"]):
                if b.name.lower().endswith(".pdf"):
                    result[b.name] = {"metadata": b.metadata or {}, "etag": b.etag}
            return result
        except Exception as e:
            print(f"[blob_client] Failed to list blob metadata in {self.container_name}: {e}")
            return {}

    def try_claim_blob_for_processing(self, blob_name: str, etag: str, existing_metadata: dict) -> bool:
        """
        Conditionally sets extraction_status=processing on blob_name, only
        if its ETag still matches what the caller last saw (via
        get_blob_metadata_map()) -- an atomic compare-and-set so two
        near-simultaneous "Sync to Webapp" clicks can't both claim the same
        blob and queue duplicate jobs for it. Carries existing_metadata's
        other keys (attempt_count/last_error from a prior failed attempt)
        forward unchanged, since set_blob_metadata() REPLACES the whole
        metadata set rather than merging -- otherwise claiming a
        previously-failed blob would silently erase its attempt history.
        Returns True if this call won the claim, False if the blob was
        already changed by someone else (or any other failure) -- never
        raises.
        """
        if not self.connection_string:
            return False
        try:
            from azure.core import MatchConditions
            from azure.storage.blob import BlobServiceClient

            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            blob_client = service_client.get_blob_client(container=self.container_name, blob=blob_name)
            new_metadata = dict(existing_metadata)
            new_metadata["extraction_status"] = "processing"
            blob_client.set_blob_metadata(
                new_metadata, etag=etag, match_condition=MatchConditions.IfNotModified,
            )
            return True
        except Exception as e:
            print(f"[blob_client] Failed to claim {blob_name}: {e}")
            return False

    def set_blob_extraction_outcome(self, blob_name: str, status: str,
                                     last_error: Optional[str] = None) -> bool:
        """
        Writes the final outcome (status='completed' or 'failed') back onto
        blob_name's metadata, incrementing its attempt_count by one for
        this attempt -- called by web/worker.py once a job tied to this
        blob (jobs.source_blob_path) finishes. Reads the blob's current
        metadata first to get its prior attempt_count -- claiming a blob
        (try_claim_blob_for_processing()) doesn't increment it; only a
        real, finished attempt does, exactly once each. Unconditional (no
        etag check): by this point the blob is uniquely "owned" by the job
        that claimed it, so there's no concurrent writer to race against.
        Returns True on success, False on any failure -- never raises.
        """
        if not self.connection_string:
            return False
        try:
            from azure.storage.blob import BlobServiceClient

            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            blob_client = service_client.get_blob_client(container=self.container_name, blob=blob_name)
            current_metadata = blob_client.get_blob_properties().metadata or {}
            attempt_count = int(current_metadata.get("attempt_count", "0")) + 1
            metadata = {"extraction_status": status, "attempt_count": str(attempt_count)}
            if last_error:
                metadata["last_error"] = last_error[:1000]
            blob_client.set_blob_metadata(metadata)
            return True
        except Exception as e:
            print(f"[blob_client] Failed to set extraction outcome for {blob_name}: {e}")
            return False

    def get_blob_last_modified(self, blob_name: str):
        """
        Returns blob_name's last-modified timestamp (a tz-aware datetime),
        or None if it doesn't exist, config is missing, or any other
        failure -- never raises. Used by the Home page's "Last Sync"
        freshness display (web/routers/dashboard.py) to read
        watermark/mailbox.json's own last-write time as a proxy for when
        the mailbox-sync Function last ran, without needing to parse its
        JSON contents.
        """
        if not self.connection_string:
            return None
        try:
            from azure.storage.blob import BlobServiceClient

            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            blob_client = service_client.get_blob_client(container=self.container_name, blob=blob_name)
            return blob_client.get_blob_properties().last_modified
        except Exception as e:
            print(f"[blob_client] Failed to get last-modified for {blob_name}: {e}")
            return None

    def download_blob_by_name(self, blob_name: str, dest_path: str) -> bool:
        """
        Downloads blob_name (as returned by list_pdf_blobs(), not a full
        URL) from the configured container to dest_path. Returns True on
        success, False on any failure -- never raises. Unlike download_pdf(),
        this trusts blob_name directly rather than parsing/validating a
        caller-supplied URL, since the caller here (the dropzone watcher)
        got the name from this same client's own list_pdf_blobs() call
        against self.container_name, not from an external request.
        """
        if not self.connection_string:
            print(f"[blob_client] Skipping download -- {self.connection_string_env_var} not set")
            return False
        try:
            success, error = self._real_download(self.container_name, blob_name, dest_path)
        except Exception as e:
            print(f"[blob_client] Unexpected error downloading {blob_name}: {e}")
            return False
        if not success:
            print(f"[blob_client] Download failed for {blob_name}: {error}")
            return False
        return True

    def delete_blob(self, blob_name: str) -> bool:
        """
        Deletes blob_name from the configured container. Used by the
        dropzone polling watcher after a blob has been downloaded and
        queued, so the dropzone container stays a transient inbox (already
        -picked-up files don't pile up and get re-scanned/re-queued on
        every poll). Returns True on success, False on any failure --
        never raises. A failed delete is logged but never blocks intake --
        the job is already queued by the time this runs, so the worst
        outcome is the same PDF sitting in the dropzone to be picked up
        again from scratch (or its already-completed job to be skipped
        because of an existing statement_id, since re-running the pipeline
        for the same file is idempotent per RULE-02).
        """
        if not self.connection_string:
            return False
        try:
            from azure.storage.blob import BlobServiceClient

            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            blob_client = service_client.get_blob_client(container=self.container_name, blob=blob_name)
            blob_client.delete_blob()
            return True
        except Exception as e:
            print(f"[blob_client] Delete failed for {blob_name}: {e}")
            return False

    def download_pdf(self, blob_url: str, dest_path: str) -> bool:
        """
        Downloads the blob named by blob_url's path to dest_path. Returns
        True on success, False on any failure -- never raises.

        blob_url is caller/webhook-supplied (see
        web/routers/intake_trigger.py, which passes through whatever
        `data.url` an inbound request claims) and must never be trusted to
        pick which container gets read. The container segment of the URL
        is only used to verify it names self.container_name -- any other
        container is refused outright -- and the actual download always
        targets self.container_name (never the parsed string) so a bug in
        that comparison can't reopen the door to an arbitrary container.
        """
        if not self.connection_string:
            print(f"[blob_client] Skipping download -- {self.connection_string_env_var} not set")
            return False

        try:
            url_container_name, blob_name = _parse_blob_url(blob_url)
        except ValueError as e:
            print(f"[blob_client] Skipping download -- {e}")
            return False

        if url_container_name != self.container_name:
            print(
                f"[blob_client] Refusing download -- blob URL names container "
                f"'{url_container_name}', expected '{self.container_name}'"
            )
            return False

        try:
            if self._download_transport:
                success, error = self._download_transport(
                    self.container_name, blob_name, dest_path, self.connection_string
                )
            else:
                success, error = self._real_download(self.container_name, blob_name, dest_path)
        except Exception as e:
            print(f"[blob_client] Unexpected error downloading {blob_name}: {e}")
            return False

        if not success:
            print(f"[blob_client] Download failed for {blob_name}: {error}")
            return False

        return True

    def _real_download(self, container_name: str, blob_name: str, dest_path: str):
        try:
            from azure.storage.blob import BlobServiceClient

            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            blob_client = service_client.get_blob_client(container=container_name, blob=blob_name)

            with open(dest_path, "wb") as f:
                f.write(blob_client.download_blob().readall())

            return True, None
        except Exception as e:
            return False, str(e)
