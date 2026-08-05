## G07 — Blob Storage Client
ID: M-043
Layer: infra
Source file: `src/storage/blob_client.py`

**Module** — Blob Storage Client
**ID** — M-043
**Layer** — infra
**Primary Responsibility** — Azure Blob Storage client for permanent PDF archival (`upload_pdf`) and downloading newly-landed drop-zone blobs (`download_pdf`) — used by two different containers/connection-strings depending on caller.

**Inputs** — `pdf_path`/`vendor_name`/`year`/`month`/`document_hash` (upload); `blob_url`/`dest_path` (download); constructor `container_name`/`connection_string_env_var` (defaults to the archival container/env var; M-015 overrides both for the drop-zone container).

**Outputs** — A blob written at `{vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf` (upload) or a local file at `dest_path` (download).

**Public Interface** — `BlobStorageClient(container_name="vendor-statements", connection_string_env_var="AZURE_BLOB_CONNECTION_STRING", transport=None, download_transport=None)`, `.upload_pdf(...)`, `.download_pdf(blob_url, dest_path) -> bool`.

**Error Behaviour** — Never raises from either public method — every failure (missing connection string, missing file, invalid year/month, any SDK/network error) is caught and returns `None` (upload) or `False` (download), with a printed warning. This is a deliberate, explicit design invariant stated in the module docstring.

**Known Fragility** — `download_pdf()`'s container-name check (comparing the inbound blob URL's container segment against `self.container_name`, refusing any mismatch) is a real security control, not incidental — it exists specifically because the blob URL is caller/webhook-supplied (M-015 passes through whatever an inbound Event Grid event claims) and must never be trusted to pick which container gets read. The actual download always targets `self.container_name` directly (never the parsed string), so a bug in the *comparison* can't reopen the door to an arbitrary container — this defense-in-depth detail is easy to accidentally weaken if refactored carelessly (e.g. if a future change passed the parsed container name to the actual download call instead of `self.container_name`).

**Change Impact** — Used by two different call sites with two different containers/connection-strings (M-017 for archival via `AZURE_BLOB_CONNECTION_STRING`; M-015 for drop-zone download via `AZURE_BLOB_DROPZONE_CONNECTION_STRING`) — a change to the default constructor args would silently affect only the caller that doesn't override them.

**Callers** — M-015 (`download_pdf`), M-017 (`upload_pdf`)
**Calls** — none
**Integration Points Used** — IP-009 (Azure Blob Storage)
