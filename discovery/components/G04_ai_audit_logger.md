## G04 — AI Audit Logger
ID: M-040
Layer: infra
Source file: `src/ai/audit_logger.py`

**Module** — AI Audit Logger
**ID** — M-040
**Layer** — infra
**Primary Responsibility** — Writes one row to `ai_audit_log` per AI interaction, classifying the response status from the raw error message.

**Inputs** — An `AIResponse` (M-022) plus interaction metadata (`interaction_type`, `prompt_version`, `source_file`, `vendor_id`, `statement_id`, `validation_result`, `extraction_confidence`).

**Outputs** — One row in `ai_audit_log`; returns the generated `audit_id`.

**Public Interface** — `log_ai_call(response, *, interaction_type, ...) -> str`.

**Error Behaviour** — No explicit error handling within this module itself — every caller (M-024, M-033) wraps its own call to `log_ai_call()` in a bare `try/except Exception: pass`, so a failure here is invisible to the pipeline but also never retried or surfaced.

**Known Fragility** — `_classify_status()`'s error classification is a simple keyword match against the lower-cased error string (`"api key"`, `"timeout"`, `"429"`, etc.) — a provider whose error message wording doesn't match any of these substrings falls through to `UNKNOWN_ERROR` silently, with no alert that the classification itself may need a new keyword.

**Change Impact** — Purely additive/observational — a bug here affects audit-trail quality (mis-classified or missing rows) but never the pipeline's actual data correctness, since every caller treats logging failures as non-fatal by design.

**Callers** — M-024, M-033
**Calls** — M-037 (`execute_sql`)
**Integration Points Used** — IP-008 (via M-037)
