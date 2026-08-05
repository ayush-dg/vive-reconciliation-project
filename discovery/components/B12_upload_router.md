## B12 — Upload Router
ID: M-012
Layer: serving
Source file: `web/routers/upload.py`

**Module** — Upload Router
**ID** — M-012
**Layer** — serving
**Primary Responsibility** — Accepts one or more PDF uploads, saves each to `sample_data/` under its original filename, and enqueues one `jobs` row per file. Never runs the pipeline synchronously.

**Inputs** — `files: List[UploadFile]` (multipart form), `period`/`notes` form fields (both accepted, `notes` unused downstream — not passed to `create_job()`).

**Outputs** — Files written to `sample_data/`; one `jobs` row per PDF via M-003's `create_job()`.

**Public Interface** — `GET /upload`, `POST /upload` — no functions called by other modules.

**Error Behaviour** — Non-PDF files are silently filtered out (by extension check) before any are saved; if the filtered list is empty, renders the upload page with a 400 and an error message. No per-file error handling once writing begins — a disk-write failure on file N would raise and abort before file N+1 is processed, with files before N already saved and no rollback.

**Known Fragility**
- The original filename is preserved verbatim (backslash-normalized, then `os.path.basename()`'d) because the pipeline derives the vendor from the filename stem — any change to this filename-preservation logic breaks vendor detection several steps downstream in M-017, a non-obvious coupling documented only in this router's own inline comment.
- `notes` form field is accepted but never persisted or used anywhere in the create_job() call — a UI element with no backing functionality.
- No per-file try/except around the save-and-enqueue loop — one bad file (e.g. a permissions error) aborts the whole batch partway through, silently leaving some files queued and others not, with no indication to the user of which succeeded.

**Change Impact** — Any change to how the filename is derived/sanitized here must be mirrored in M-017's `derive_vendor_slug_from_filename()`/`derive_vendor_name_from_filename()` assumptions about filename shape.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`, `require_login`, `sidebar_context`), M-003 (`create_job`)
**Integration Points Used** — none
