## C09 — Document Understanding Engine
ID: M-024
Layer: pipeline
Source file: `src/ai/document_understanding_engine.py`

**Module** — Document Understanding Engine
**ID** — M-024
**Layer** — pipeline
**Primary Responsibility** — The core AI extraction stage: resolves the active provider via M-023, sends it the PDF, and falls back to deterministic pdfplumber extraction (M-031) if the primary provider fails.

**Inputs** — `pdf_path`; `pdf_text`/`statement_id` (accepted for call-site compatibility, `pdf_text` itself unused — both extraction paths read the PDF file directly).

**Outputs** — A Universal Financial Document Schema dict, tagged with `_provider_used`/`_model_used`.

**Public Interface**
- `DocumentUnderstandingEngine.understand(pdf_text, pdf_path, statement_id=None) -> dict`
- `extract_pdf_text(pdf_path) -> (text, page_count)` — still used by M-017 for char/page-count logging ahead of calling `understand()`.
- `CorruptedPDFError` — exception class raised by `extract_pdf_text()`.
- `VISION_PROMPT` — module-level prompt constant.

**Error Behaviour**
- `extract_pdf_text()` catches `PdfminerException`/`PDFSyntaxError` specifically and re-raises as `CorruptedPDFError` with a clean message — the only place in this module that raises rather than degrades.
- `understand()` never raises: the primary provider's exception (if any) is caught, logged via `print`, and the pipeline falls through to `extract_with_pdfplumber()` (M-031) unconditionally — a provider failure is always recoverable at this layer.

**Known Fragility**
- **`VISION_PROMPT` is dead code for the active provider** — confirmed directly this session: `ClaudeSonnetClient.generate_with_file()` (M-025) ignores the `prompt` parameter entirely and sends its own internal `EXTRACTION_PROMPT` instead. `VISION_PROMPT`'s carefully-written column-mapping and confidence-calibration instructions (mixed-prefix handling, exact transcription rules) are only reachable by a provider that actually honors the passed prompt — none of the currently-active chain (M-025 primary, M-031 fallback) does. A future engineer editing `VISION_PROMPT` expecting it to change extraction behavior would see no effect.
- `log_ai_call()` failures are silently swallowed (`except Exception: pass`) around the audit-log write — an audit-logging outage would never surface as a pipeline error, by design, but also never surfaces as a warning either.

**Change Impact** — This module is the sole caller of `client_factory.get_ai_client()` (M-023) from the primary extraction path — any change to provider resolution flows through here first.

**Callers** — M-017 (`extract_pdf_text`, `DocumentUnderstandingEngine().understand()`)
**Calls** — M-023 (`get_ai_client`), M-031 (`extract_with_pdfplumber`, fallback), M-040 (`log_ai_call`)
**Integration Points Used** — none directly (delegates to M-023 for the actual provider call)
