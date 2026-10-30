# Running the VIVE Reconciliation pipeline in Docker

This containerizes the existing pipeline for local/dev use. It does not change
any pipeline logic — it's packaging only. Nothing here (Python version,
dependencies, matching/extraction code) is different from running the project
directly on your machine; only *how you invoke it* changes.

## What's in the image

- Python 3.12 (matches the project's local dev venv — see "Assumptions" below)
- All packages from [`requirements.txt`](requirements.txt)
- `tesseract-ocr` and `poppler-utils` at the OS level, required by the
  pdfplumber + Tesseract OCR fallback path
  ([`src/ai/ocr_extractor.py`](src/ai/ocr_extractor.py)) — `poppler-utils` is
  needed by `pdf2image` to rasterize PDF pages before Tesseract can run on them
- The application code (everything except what's excluded by
  [`.dockerignore`](.dockerignore) — notably your local `.env`, `venv/`,
  `sample_data/`, and the SQLite `.db` file itself)

No API keys or `.env` contents are baked into the image. They're supplied at
container start via `env_file`.

## One-time setup

1. Copy `.env.example` to `.env` and fill in at least the Claude settings:
   ```
   cp .env.example .env
   ```
   ```
   AZURE_CLAUDE_ENDPOINT=...
   AZURE_CLAUDE_API_KEY=...
   AZURE_CLAUDE_SONNET_DEPLOYMENT=...
   AZURE_CLAUDE_DEPLOYMENT=...
   ```
   This file stays on your host and is never copied into the image — Docker
   reads it at container start (`docker-compose.yml`'s `env_file: .env`).

2. Build the image:
   ```
   docker compose build
   ```

## Starting the container

```
docker compose up -d
```

This starts a long-lived container (`app`) so you can `exec` into it
repeatedly, the same way you'd use a persistent dev shell. It does not
automatically run the pipeline — you drive each stage yourself, same as
running the numbered scripts locally.

Two volumes are mounted so data isn't rebuilt/lost between container recreations:

- `./lakehouse` → `/app/lakehouse` — the SQLite database persists across
  rebuilds
- `./sample_data` → `/app/sample_data` — add/remove input PDFs on the host
  without rebuilding the image

If this is the first time the lakehouse has been set up, create the schema:
```
docker compose exec app python notebooks/00_setup_lakehouse_schema.py
```

## Running the pipeline

Run the whole pipeline (intake, matching, report) for one PDF:
```
docker compose exec app python scripts/run_full_pipeline.py --pdf sample_data/YOUR_FILE.pdf
```

Or start the web app inside the container:
```
docker compose exec app python -m uvicorn web.app:app --host 0.0.0.0 --port 8000
```

## Verifying the container

Run the test suite:
```
docker compose exec app python -m pytest tests/ -v
```

Run the full pipeline end-to-end on a real sample PDF:
```
docker compose exec app python scripts/run_full_pipeline.py --pdf sample_data/ASTCollex0526.pdf --statement-id STMT-VERIFY-001
```

## Stopping the container

```
docker compose down
```

The `lakehouse/` and `sample_data/` directories are untouched on your host —
they're bind mounts, not container-internal storage.

## Assumptions made

- **Python version**: nothing in the repo pins one. The image uses
  `python:3.12-slim`, matching the local dev venv.
- **`poppler-utils`**: not explicitly requested, but added alongside
  `tesseract-ocr` because `pdf2image` (used by the OCR fallback) calls
  Poppler's `pdftoppm` binary directly — without it, OCR extraction would
  fail at runtime inside the container even with Tesseract installed and
  `is_ocr_available()` reporting `True` (see "Flags" below).
- **`config/` is baked into the image, not volume-mounted** — only
  `lakehouse/` and `sample_data/` are mounted, so a config change needs
  `docker compose build`.
- **Default container command** is `tail -f /dev/null` (keeps the container
  running so `docker compose exec` works, same idea as a persistent dev
  shell) — the container does not auto-run the pipeline on start.
