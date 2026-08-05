## B07 — upload router
ID: M-007
Layer: serving
Source file: web/routers/upload.py

**Module** — upload router
**ID** — M-007
**Layer** — serving
**Primary Responsibility** — Accept one or more vendor-statement PDF uploads, save them to `sample_data/`, and enqueue one `jobs` row per file — never runs the pipeline itself.

**Inputs** — `GET /upload` — no inputs. `POST /upload` — `files: List[UploadFile]` (required, multipart), `period: str = None`, `notes: str = None` (both accepted but `notes` is never persisted anywhere — read but unused beyond the form).

**Outputs** — Saves each accepted PDF to `sample_data/{original_filename}` (creating the directory if needed) and inserts one `jobs` row per file via `queries.create_job()`. Renders `upload.html` with a success/error message; never invokes the pipeline directly.

**Public Interface**
- `upload_form(request, user) -> TemplateResponse` — `GET /upload`
- `upload_submit(request, user, files, period=None, notes=None) -> TemplateResponse` — `POST /upload`

**Error Behaviour** — Filters `files` to only those ending `.pdf` (case-insensitive); if none remain, renders the form with an error and HTTP 400 rather than raising. No handling around the file-write itself (`open(pdf_path, "wb")`) — a disk-full or permission error would propagate as an unhandled 500 mid-loop, potentially after some files in a multi-file upload already succeeded (partial-success is possible and not communicated back to the user beyond whatever exception message FastAPI's default handler shows).

**Known Fragility**
- **Filename handling**: saves under `os.path.basename(file.filename.replace("\\", "/"))` — the code comment itself explains this handles a client sending a Windows-style path on what "is a Linux deployment" that "only splits on '/'"; confirms production target is Linux (Azure App Service, consistent with `startup.sh`). A client could still overwrite an existing `sample_data/` file of the same name (no collision check, no dedup by content hash at upload time — the *pipeline's* extraction cache dedups by content hash later, but the raw file itself can silently overwrite a prior upload of a same-named-but-different PDF).
- The vendor is derived downstream from the filename stem (`derive_vendor_slug_from_filename`/`derive_vendor_name_from_filename` in `notebooks/01_document_intake.py`) — this router's comment explicitly flags that "anything else breaks vendor detection downstream," meaning any future change to how files are named/saved here must stay compatible with those two functions.

**Change Impact** — A change to the `jobs` table schema (e.g. required columns) must be mirrored in `queries.create_job()`; a change to how vendor names are derived from filenames affects this router's save behavior indirectly (it must keep the original filename intact).

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`create_job`)
**Integration Points Used** — none directly (writes to local filesystem `sample_data/`, not Blob Storage — that happens later, inside the pipeline itself)
