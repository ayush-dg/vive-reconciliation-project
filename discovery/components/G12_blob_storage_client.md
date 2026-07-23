## G12 — Blob Storage client
ID: M-039
Layer: infra
Source file: src/storage/blob_client.py

**Module** — Blob Storage client
**ID** — M-039
**Layer** — infra
**Primary Responsibility** — Azure Blob Storage client for permanent vendor-statement PDF archival, keyed on the same SHA-256 document hash used for extraction caching.

**Inputs** — `BlobStorageClient(container_name="vendor-statements", connection_string_env_var="AZURE_BLOB_CONNECTION_STRING", transport=None)`; `upload_pdf(pdf_path, vendor_name, year, month, document_hash, original_filename=None, uploaded_by=None)`.

**Outputs** — Uploads the PDF to `{vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf` in the configured container; returns the blob URL on success, `None` on any failure.

**Public Interface**
- `class BlobStorageClient` — `__init__(...)`, `upload_pdf(...) -> Optional[str]`, `_real_upload(blob_path, pdf_path, metadata)` (private)
- `_slugify_vendor_name(vendor_name) -> str` (module-level helper)

**Error Behaviour** — **Never raises, by design and confirmed by source** — every failure path (missing connection string, missing `document_hash`, missing file, invalid year/month, any transport/SDK exception) is caught and returns `None` with a printed warning, never propagated. This is now confirmed **not** theoretical — Session A's call trace found this actually wired into `notebooks/01_document_intake.py`'s `run_intake()` Step 8 (correcting the Implementation Context's stale "not wired in" claim), so this never-raise guarantee is load-bearing in production, not just a defensive pattern that's never exercised.

**Known Fragility** — The real `azure-storage-blob` SDK import is lazy (only on `_real_upload()`'s actual call path), so tests never require it installed — confirmed by source, matching the same pattern `document_intelligence_client.py` uses for its Azure SDK. If `azure-storage-blob` isn't installed in a given deployment, the *first* real upload attempt fails (caught, returns `None`, logs a warning) rather than failing at import time — meaning a missing dependency here degrades silently into "no PDFs are ever archived" rather than a clear startup error.

**Change Impact** — The path convention (`{vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf`) is depended on only by whatever eventually reads blobs back (not traced — no reader of Blob Storage was found in this codebase; archival appears to be write-only from the pipeline's perspective, confirmed by absence of any `download`/`get_blob` call anywhere in the traced source).

**Callers** — M-014 (`notebooks/01_document_intake.py`'s `upload_pdf_to_blob_storage()`)
**Calls** — none (lazily imports the Azure SDK internally)
**Integration Points Used** — IP-009 (Azure Blob Storage)
