# VIVE Vendor Statement Reconciliation

An AI-enabled reconciliation system that takes **vendor statement PDFs**, extracts
their invoice lines, compares them against VIVE's NetSuite vendor bills and credits,
and shows the AP team what matched and what needs attention.

## Architecture

```
PDF (upload page, blob drop zone, or mailbox Logic App)
   │
   ▼
Extraction — a dedicated Python extractor for known text-layer vendors,
             otherwise Claude Sonnet 4.6; pdfplumber + OCR as last resort
   │
   ▼
Validation gate — statement total checks; rows below 0.90 confidence go to review
   │
   ▼
Bronze  — raw extracted lines, every business field as TEXT
   │
   ▼
Silver  — standardized and typed (dbt models in dbt/vive_recon)
   │
   ▼
Matching — deterministic, against NetSuite bills/credits (no AI)
   │
   ├─▶ recon_matched_invoices
   ├─▶ recon_exceptions (AI adds a plain-language explanation here only)
   └─▶ recon_summary
   │
   ▼
Optional NetSuite write-back (docs/NETSUITE_WRITEBACK.md)
```

**Where AI is used, and where it isn't**

AI is used for two things only:
1. Extracting invoice lines from a PDF layout that has no dedicated extractor.
2. Writing a plain-language explanation for an exception, after the fact.

Matching is deterministic Python/SQL in
[`src/matching/fabric_matching.py`](src/matching/fabric_matching.py) (its docstring
lists the rules). The AI never decides whether two invoices match.

## Extraction

[`notebooks/01_document_intake.py`](notebooks/01_document_intake.py) picks the route
per PDF:

- **Python library** — text-layer statements from the vendors mapped in
  [`src/extraction/python_library/adapter.py`](src/extraction/python_library/adapter.py),
  one hand-written extractor per vendor layout.
- **AI** — scanned PDFs and every other vendor. The chain is configured in
  [`config/ai/active_provider.json`](config/ai/active_provider.json):
  1. **Claude Sonnet 4.6** (Azure AI Foundry) —
     [`config/ai/claude_sonnet_extraction.json`](config/ai/claude_sonnet_extraction.json)
  2. **pdfplumber** (last resort) — no API key needed; OCRs scanned pages with Tesseract

If Claude errors or times out, the pipeline falls through to pdfplumber.
Exception explanations use Claude Haiku 4.5 ([`config/ai/claude.json`](config/ai/claude.json)).

## NetSuite data

Matching reads NetSuite vendor bills, credits and vendors from one of two sources,
chosen by `NETSUITE_SOURCE` ([`src/netsuite/connect_source.py`](src/netsuite/connect_source.py)):

- `fabric` (default) — the nightly Fabric Lakehouse copy
- `connect` — live, read-only production NetSuite through SuiteAnalytics Connect,
  falling back to the Fabric copy if a read fails

## Setup

1. Copy `.env.example` to `.env` and fill in at least the Claude settings:
   ```
   AZURE_CLAUDE_ENDPOINT=...
   AZURE_CLAUDE_API_KEY=...
   AZURE_CLAUDE_SONNET_DEPLOYMENT=...
   AZURE_CLAUDE_DEPLOYMENT=...
   ```
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create the local SQLite schema:
   ```
   python notebooks/00_setup_lakehouse_schema.py
   ```
   This creates `lakehouse/reconciliation.db` from the files in `migrations/`. Safe to
   re-run at any time.
4. Start the web app:
   ```
   uvicorn web.app:app --reload
   ```

Locally, storage is SQLite. In Azure, [`src/lakehouse/connection.py`](src/lakehouse/connection.py)
selects Azure SQL and the Fabric items from the environment.

Azure infrastructure is Terraform under [`deploy/`](deploy/). Container builds and
runs are described in [`DOCKER.md`](DOCKER.md).
