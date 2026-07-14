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

1. Copy `.env.example` to `.env` and fill in your Azure OpenAI credentials:
   ```
   cp .env.example .env
   ```
   ```
   AZURE_OPENAI_ENDPOINT=...
   AZURE_OPENAI_API_KEY=...
   AZURE_OPENAI_DEPLOYMENT_GPT5_MINI=...
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

## Running the pipeline stages

Either drop into an interactive shell:
```
docker compose exec app bash
python notebooks/01_document_intake.py --pdf sample_data/YOUR_FILE.pdf
python notebooks/02_generate_mock_erp.py --statement-id STMT-...
python notebooks/03_run_matching.py --statement-id STMT-...
python notebooks/04_generate_report.py --statement-id STMT-...
```

Or run one-off commands with `docker compose exec` directly:
```
docker compose exec app python notebooks/01_document_intake.py --pdf sample_data/YOUR_FILE.pdf --statement-id STMT-MY-001
docker compose exec app python notebooks/02_generate_mock_erp.py --statement-id STMT-MY-001
docker compose exec app python notebooks/03_run_matching.py --statement-id STMT-MY-001
docker compose exec app python notebooks/04_generate_report.py --statement-id STMT-MY-001
```

Or use the existing single-command entry point, which runs all four stages:
```
docker compose exec app python scripts/run_full_pipeline.py --pdf sample_data/YOUR_FILE.pdf
```

## Mock ERP CLI / re-reconciliation workflow

This remains CLI-only, exactly as it works outside Docker — there's no
dashboard in this codebase and this task didn't add one.

```
docker compose exec app python notebooks/02_generate_mock_erp.py --statement-id STMT-MY-001
docker compose exec app python notebooks/03_run_matching.py --statement-id STMT-MY-001
```

**Caveat:** `config/mock_erp/scenario_config.json` is baked into the image at
build time (only `lakehouse/` and `sample_data/` are volume-mounted, per the
task's requirements). So to edit it while working in the container, either:

- `docker compose exec app bash`, then edit the file in place with `vi`/`nano`
  inside the container (edits are lost when the container is removed/rebuilt
  — copy them back to the host if you want to keep them), or
- Edit `config/mock_erp/scenario_config.json` on the host, then
  `docker compose build && docker compose up -d` to rebuild with the new config.

If you'll be iterating on `scenario_config.json` often, consider adding
`./config/mock_erp:/app/config/mock_erp` as a third volume mount — this
wasn't in scope for this change, so it's left as a decision for you.

## Verifying the container

Run the existing test suite (see "Assumptions" — `pytest` isn't currently in
`requirements.txt`, so it's not in the image by default):
```
docker compose exec app pip install pytest
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

- **Python version**: no `pyproject.toml`, `setup.py`, `runtime.txt`, or
  `.python-version` pins a version anywhere in this repo. The image uses
  `python:3.12-slim`, matching `venv/pyvenv.cfg` (`version = 3.12.0`) from the
  existing local dev environment. Confirm this is right for production.
- **`poppler-utils`**: not explicitly requested, but added alongside
  `tesseract-ocr` because `pdf2image` (used by the OCR fallback) calls
  Poppler's `pdftoppm` binary directly — without it, OCR extraction would
  fail at runtime inside the container even with Tesseract installed and
  `is_ocr_available()` reporting `True` (see "Flags" below).
- **`config/` is baked into the image, not volume-mounted** — only
  `lakehouse/` and `sample_data/` are mounted, per the task's explicit
  requirements. Documented above as a caveat for the mock ERP workflow.
- **Default container command** is `tail -f /dev/null` (keeps the container
  running so `docker compose exec` works, same idea as a persistent dev
  shell) — the container does not auto-run the pipeline on start.
