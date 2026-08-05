## G08 — AI audit logger
ID: M-032
Layer: infra
Source file: src/ai/audit_logger.py

**Module** — AI audit logger
**ID** — M-032
**Layer** — infra
**Primary Responsibility** — Logs every AI interaction to `ai_audit_log`; called only by extraction/explanation code, never directly by notebooks or scripts.

**Inputs** — `log_ai_call(response: AIResponse, *, interaction_type, prompt_version="v1", source_file=None, vendor_id=None, statement_id=None, validation_result=None, extraction_confidence=None) -> str`.

**Outputs** — One INSERT into `ai_audit_log`; returns the generated `audit_id` (UUID4) for cross-referencing.

**Public Interface**
- `log_ai_call(...) -> str`
- `_classify_status(response: AIResponse) -> str` (private) — maps `response.error` text to one of `SUCCESS`, `MISSING_API_KEY`, `TRANSPORT_ERROR`, `PARSE_ERROR`, `RATE_LIMITED`, `UNKNOWN_ERROR` via substring matching on the error message.

**Error Behaviour** — No try/except in this module itself — every caller (`document_understanding_engine.py`, `explanation_service.py`) wraps its own call to `log_ai_call()` in a bare `except Exception: pass`, meaning a logging failure never blocks the pipeline, but that resilience lives in the *callers*, not here. This module itself would propagate a DB error if called without that wrapper.

**Known Fragility** — `_classify_status()`'s error classification is a best-effort substring match against whatever free-text error string each provider client's `_clean_error()` produced — since each of the 6 clients has its own independently-written `_clean_error()` (confirmed by source read, not shared), the substrings this function matches against ("api key", "timeout", "429", "quota", "rate", "json", "parse") may not consistently appear across all providers' error message conventions. A provider-specific error phrasing that doesn't match any of these substrings silently falls into `UNKNOWN_ERROR`.

**Change Impact** — A new provider client's `_clean_error()` phrasing should be checked against `_classify_status()`'s substring list to ensure it classifies usefully, though nothing enforces this.

**Callers** — M-020 (`document_understanding_engine.py`), M-029 (`explanation_service.py`)
**Calls** — M-033 (`execute_sql`)
**Integration Points Used** — IP-008 (Lakehouse database)
