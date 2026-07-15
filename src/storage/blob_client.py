"""
blob_client.py

Azure Blob Storage client for permanent vendor-statement PDF archival.
See docs/VIVE_Implementation_Context.md Section 4, Phase 2, "Object
storage (Blob)".

Path convention: {vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf -- keyed on
the same SHA-256 document_hash already computed for extraction caching
(RULE-02), so re-uploading the same PDF always lands on the same blob path
instead of creating a duplicate.

Never raises -- a blob upload failure must not crash the ingestion
pipeline. Callers get None back on any failure (missing config, missing
file, network/auth error) and are expected to log and continue.
"""

import os
import re
from typing import Callable, Optional


def _slugify_vendor_name(vendor_name: Optional[str]) -> str:
    """Lowercase, alphanumeric-and-underscore-only vendor slug for blob paths."""
    slug = re.sub(r"[^a-z0-9]+", "_", (vendor_name or "").lower()).strip("_")
    return slug or "unknown_vendor"


class BlobStorageClient:
    """
    transport: optional injectable callable for testing. Signature:
        (blob_path, pdf_path, metadata, container_name, connection_string)
            -> (success: bool, blob_url: Optional[str], error: Optional[str])
    If None, uses the real azure-storage-blob SDK (imported lazily, only
    on the real upload path, so tests never require it installed).
    """

    def __init__(
        self,
        container_name: str = "vendor-statements",
        connection_string_env_var: str = "AZURE_BLOB_CONNECTION_STRING",
        transport: Optional[Callable] = None,
    ):
        self.container_name = container_name
        self.connection_string_env_var = connection_string_env_var
        self.connection_string = os.environ.get(connection_string_env_var)
        self._transport = transport

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
