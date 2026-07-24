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

    def download_pdf(self, blob_url: str, dest_path: str) -> bool:
        """
        Downloads blob_url to dest_path. Returns True on success, False on
        any failure -- never raises.
        """
        if not self.connection_string:
            print(f"[blob_client] Skipping download -- {self.connection_string_env_var} not set")
            return False

        try:
            container_name, blob_name = _parse_blob_url(blob_url)
        except ValueError as e:
            print(f"[blob_client] Skipping download -- {e}")
            return False

        try:
            if self._download_transport:
                success, error = self._download_transport(
                    container_name, blob_name, dest_path, self.connection_string
                )
            else:
                success, error = self._real_download(container_name, blob_name, dest_path)
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
