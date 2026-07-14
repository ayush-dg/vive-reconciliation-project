# VIVE Vendor Statement Reconciliation

An AI-enabled reconciliation system that takes **any vendor statement PDF** — any
vendor, any layout — extracts its invoice data with AI, compares it against internal
ERP data, and produces a reconciliation report showing matches and exceptions.

No vendor-specific configuration is required before uploading a PDF. The AI figures
out the vendor, statement period, invoice table, and column mapping on its own.

## Architecture

```
PDF upload
   │
   ▼
AI extraction (generic, schema-constrained)
   │
   ▼
Bronze  — raw AI output, untyped, one row per extracted invoice line
   │
   ▼
Silver  — standardized & typed, one shared schema for both vendor statement
          and internal ERP records (distinguished by record_source)
   │
   ▼
Matching engine — 100% deterministic Python/SQL (no AI)
   │
   ├─▶ Gold: matched_invoices
   ├─▶ Gold: exceptions (AI adds a plain-language explanation here only)
   └─▶ Gold: reconciliation_summary
```

**Medallion layers**

- **Bronze** — raw extraction, exactly as the AI (or pdfplumber) returned it. Every
  business field is stored as TEXT; nothing is typed or validated yet.
- **Silver** — standardized, typed, and normalized. Vendor statement rows and
  internal ERP rows share one schema (`silver_reconciliation_standard`) so the
  matching engine never needs to know which side a record came from.
- **Gold** — business-ready outputs: matched invoices, exceptions, and a
  per-statement reconciliation summary.

**Where AI is used, and where it isn't**

AI is used for two things only:
1. Extracting structured invoice data out of an arbitrary PDF layout.
2. Writing a plain-language explanation for an exception, after the fact.

Matching, normalization, and all business rules are deterministic Python/SQL,
driven entirely by [`config/matching/matching_rules.json`](config/matching/matching_rules.json).
The AI never decides whether two invoices match.

## AI provider fallback chain

Configured in [`config/ai/active_provider.json`](config/ai/active_provider.json):

1. **Azure OpenAI gpt-5-mini** (primary) — [`config/ai/azure_gpt5_mini.json`](config/ai/azure_gpt5_mini.json), sends the PDF one page at a time, handles text/scanned/hybrid PDFs identically
2. **pdfplumber** (last resort) — no API key needed; handles scanned pages internally via per-page Tesseract OCR

If the primary provider errors, times out, or exhausts its quota, the pipeline automatically
falls through to the deterministic pdfplumber fallback. Both paths return data
shaped exactly like [`config/schema/universal_financial_document_schema.json`](config/schema/universal_financial_document_schema.json)
— this is the single contract between the AI layer and everything downstream.

## Setup

1. Clone/copy this project.
2. Copy `.env.example` to `.env` and fill in your Azure OpenAI credentials:
   ```
   AZURE_OPENAI_ENDPOINT=...
   AZURE_OPENAI_API_KEY=...
   AZURE_OPENAI_DEPLOYMENT_GPT5_MINI=...
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Create the local SQLite lakehouse schema:
   ```
   python notebooks/00_setup_lakehouse_schema.py
   ```
   This creates `lakehouse/reconciliation.db` with all Bronze/Silver/Gold tables,
   plus the intake log, AI audit log, review queue, and extraction cache. Safe to
   re-run at any time.

Locally, storage is SQLite. In production, the same schema design maps onto
Microsoft Fabric Delta tables — [`src/lakehouse/connection.py`](src/lakehouse/connection.py)
is the only file that knows which backend is in use; swapping backends means
changing only that file.

## Mock ERP and re-reconciliation

Since there's no NetSuite access yet, internal ERP data is simulated by a
**mutable Mock ERP** generator, controlled by
[`config/mock_erp/scenario_config.json`](config/mock_erp/scenario_config.json).

The `controlled_exceptions` block lets you deliberately introduce scenarios between
runs — e.g. remove an invoice to simulate "the shop hasn't posted it yet," or alter
an amount to simulate a mismatch. Nothing here is random; every exception is
explicit and deterministic.

This enables a re-reconciliation loop without ever re-extracting the PDF:

1. Run the pipeline once — PDF is extracted into Bronze, matched against the Mock
   ERP, and a reconciliation report is produced.
2. Edit `scenario_config.json` to add/remove/modify an ERP-side invoice (e.g. "shop
   now posts the missing invoice").
3. Re-run matching only — the vendor statement side is untouched (already in
   Bronze/Silver), so no AI call happens again. Only the ERP side regenerates and
   the match/exception outputs are recomputed.

## Running in Docker

The pipeline can also be run in a container — see [`DOCKER.md`](DOCKER.md) for
build/run instructions, environment variable setup, and how to run each
pipeline stage (including the Mock ERP CLI workflow) inside the container.

## Generic by design

There is no per-vendor setup step. Upload any vendor statement PDF and the AI:

- Detects the document type and vendor identity
- Locates the invoice table regardless of layout
- Maps columns to the universal schema fields
- Flags anything it's unsure about via `warnings` and per-field confidence scores

Low-confidence extractions route to `validation_document_review_queue` instead of
silently flowing into matching.
