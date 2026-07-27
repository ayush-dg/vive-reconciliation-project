## G12 — Blob Storage client
ID: M-039
Layer: infra
Source file: src/storage/blob_client.py
Rewritten: 2026-07-25 scoped BCE refresh (download_pdf added 2026-07-24 for the auto-intake dropzone; container-pinning security fix added 2026-07-25)

**Module** — Blob Storage client
**ID** — M-039
**Layer** — infra
**Primary Responsibility** — Azure Blob Storage client, now bidirectional: permanent vendor-statement PDF archival (`upload_pdf`, keyed on the same SHA-256 document hash used for extraction caching), plus (new, 2026-07-24) downloading newly-landed PDFs out of the Event Grid auto-intake dropzone container (`download_pdf`, used by M-046).

**Inputs**
- `BlobStorageClient(container_name="vendor-statements", connection_string_env_var="AZURE_BLOB_CONNECTION_STRING", transport=None, download_transport=None)` — **`download_transport` is new, 2026-07-24**, an injectable callable for testing downloads, mirroring `transport`'s existing role for uploads.
- `upload_pdf(pdf_path, vendor_name, year, month, document_hash, original_filename=None, uploaded_by=None)` — unchanged.
- **`download_pdf(blob_url, dest_path) -> bool` (new, 2026-07-24; container-pinning behavior rewritten 2026-07-25)** — downloads the blob named by `blob_url`'s path to `dest_path`.

**Outputs**
- `upload_pdf` — uploads to `{vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf` in the configured container; returns the blob URL on success, `None` on any failure. Unchanged.
- `download_pdf` — writes the downloaded blob to `dest_path`; returns `True`/`False`. **As of 2026-07-25, the download always targets `self.container_name` — never a container named in `blob_url` itself, even if the caller's URL claims a different one.**

**Public Interface**
- `class BlobStorageClient` — `__init__(...)`, `upload_pdf(...) -> Optional[str]`, `_real_upload(blob_path, pdf_path, metadata)` (private), **`download_pdf(blob_url, dest_path) -> bool` (new), `_real_download(container_name, blob_name, dest_path)` (private, new)**
- `_slugify_vendor_name(vendor_name) -> str` (module-level helper, unchanged)
- `_parse_blob_url(blob_url) -> (container_name, blob_name)` (module-level helper, new 2026-07-24) — splits a blob URL's path into its container and blob-name segments; raises `ValueError` if the URL has no distinct container/blob segments.

**Error Behaviour** — **Never raises, by design and confirmed by source, for both `upload_pdf` and `download_pdf`** — every failure path (missing connection string, missing `document_hash`/file for uploads, an unparseable URL or **a URL naming a container other than the configured one (new, 2026-07-25)** for downloads, any transport/SDK exception) is caught and returns `None`/`False` with a printed warning, never propagated. The never-raise guarantee is load-bearing in production for `upload_pdf` (wired into `notebooks/01_document_intake.py`'s `run_intake()` Step 8) and now equally load-bearing for `download_pdf` (wired into `web/routers/intake_trigger.py`, M-046, which must never crash on a malformed or hostile inbound webhook payload).

**Known Fragility**
- **The real `azure-storage-blob` SDK import is lazy** — unchanged from before, now true for both `_real_upload()` and `_real_download()`.
- **[FIXED 2026-07-25 — was a real security gap from 2026-07-24 to 2026-07-25] `download_pdf()` previously derived the container to download from directly out of the caller-supplied `blob_url`, ignoring `self.container_name` entirely.** `_parse_blob_url()` splits the URL into `(container_name, blob_name)`, and until 2026-07-25 both were passed straight through to the SDK/transport call — meaning the constructor's `container_name` argument (e.g. `DROPZONE_CONTAINER` in M-046) was silently dead code on the download path, and any caller of `download_pdf()` could make it read from *any* container the configured connection string had access to, not just the intended one. This was found and fixed during this session's security review of the Event Grid webhook (M-046) — see `discovery/RISK_REGISTER.md` R-009. **Current behavior:** `download_pdf()` still parses the URL's container for comparison, but refuses outright (`return False`, no download attempted) if it doesn't exactly equal `self.container_name`; even on a match, the actual download call is made with `self.container_name` (the configured value), never the parsed string — so a future bug in the comparison itself can't silently reopen this path. Verified by a dedicated test (`tests/test_blob_client.py::test_url_naming_a_different_container_is_refused`) that the download transport is never even invoked on a mismatch.
- **Path convention consumer still not traced** — unchanged from before; archival appears to remain write-only from the pipeline's perspective for the `vendor-statements` container. The new dropzone `download_pdf()` path is a *different* container/connection-string pair (`incoming-statements` / `AZURE_BLOB_DROPZONE_CONNECTION_STRING`) with its own distinct purpose (pulling a just-landed file down, not reading back an archived one) — the two flows should not be conflated.

**Change Impact** — The upload path convention (`{vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf`) is unchanged and still not depended on by any known reader. **New:** any future change to `download_pdf()`'s container-comparison logic must preserve the "always download from `self.container_name`, never the parsed URL value" property — this is now a security-load-bearing invariant, not just a convenience default; see `discovery/RISK_REGISTER.md` R-009 and `discovery/components/B10_intake_trigger_router.md`'s Known Fragility for why this router-level fix depended entirely on this file's correctness.

**Callers** — M-014 (`notebooks/01_document_intake.py`'s `upload_pdf_to_blob_storage()`, unchanged), **M-046 (`web/routers/intake_trigger.py`, new, 2026-07-24 — calls `download_pdf()`)**
**Calls** — none (lazily imports the Azure SDK internally)
**Integration Points Used** — IP-009 (Azure Blob Storage, `vendor-statements` archival), **IP-010 (new — the auto-intake dropzone container/connection-string pair, a different storage account from IP-009)**
