## C07 — document understanding engine
ID: M-020
Layer: pipeline
Source file: src/ai/document_understanding_engine.py

**Module** — document understanding engine
**ID** — M-020
**Layer** — pipeline
**Primary Responsibility** — The core AI extraction stage: resolves the active provider via the factory, attempts extraction, falls back to deterministic pdfplumber on failure. Returns a Universal Financial Document Schema dict.

**Inputs** — `DocumentUnderstandingEngine().understand(pdf_text, pdf_path, statement_id=None) -> dict`. `pdf_text` is accepted for call-site compatibility with `notebooks/01_document_intake.py` but not actually used — both primary and fallback paths read the PDF file directly.

**Outputs** — A Universal Financial Document Schema dict, tagged with `_provider_used`/`_model_used`.

**Public Interface**
- `class DocumentUnderstandingEngine`: `understand(pdf_text, pdf_path, statement_id=None) -> dict`
- `extract_pdf_text(pdf_path) -> (str, int)` — module-level function, still used by `notebooks/01_document_intake.py` for its own char/page-count logging.
- `VISION_PROMPT` (module-level constant) — the detailed extraction prompt.

**Error Behaviour** — `understand()` wraps the primary provider call in `try/except Exception`, logging via `audit_logger.log_ai_call()` (itself wrapped in a further silent `try/except: pass`) and falling through to pdfplumber on *any* primary failure — confirmed by source: even an unexpected exception type from a provider client (not just a clean `AIResponse(success=False)`) is caught here.

**Known Fragility**
- **`VISION_PROMPT` is passed to `primary_client.generate_with_file(pdf_path, VISION_PROMPT)`, but the actual active primary (`ClaudeSonnetClient`, M-023) ignores the passed prompt entirely** and sends its own much shorter `EXTRACTION_PROMPT` instead — confirmed by direct comparison during this session's engineer-requested follow-up, including the concrete regressions this causes (fabricated per-row confidence, no totals-row exclusion) — see `discovery/components/A02_module_call_map.md` Section 4, item 1, and `discovery/DOMAIN_MODEL.json`'s risk-relevant annotations. This module's own module docstring is also stale, claiming "Azure OpenAI gpt-5-mini + pdfplumber/OCR is the settled decision" — one of the six stale AI-provider-chain locations catalogued in TOPOLOGY.md.
- The provider is resolved via `client_factory.get_ai_client()` with **no argument** — meaning this module has no awareness of, or control over, which provider it's actually invoking; it always gets whatever `provider_chain[0]` resolves to. Any change to `active_provider.json` silently changes this module's behavior with zero code change here.

**Change Impact** — This is the single point where the "primary vs. fallback" decision is made — any change to the fallback trigger condition (currently: any exception, or a clean `success=False`) changes system-wide extraction behavior.

**Callers** — M-014 (`notebooks/01_document_intake.py`)
**Calls** — M-031 (`client_factory.get_ai_client()`), M-028 (`extract_with_pdfplumber`), M-032 (`log_ai_call`)
**Integration Points Used** — IP-001 (whichever provider `provider_chain[0]` currently resolves to — confirmed IP-001, Claude Sonnet, as of this session)
