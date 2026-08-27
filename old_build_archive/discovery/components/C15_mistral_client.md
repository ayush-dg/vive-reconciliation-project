## C15 — Mistral Client
ID: M-030
Layer: pipeline
Source file: `src/ai/mistral_client.py`

**Module** — Mistral Client
**ID** — M-030
**Layer** — pipeline
**Primary Responsibility** — Dormant (not in the active chain). Rasterizes every page to PNG (Mistral rejects raw PDF data URIs) and sends one chat-completions call per page.

**Inputs** — `config` (`config/ai/mistral.json`); env vars for API key/endpoint/deployment.

**Outputs** — `AIResponse` wrapping a Universal Financial Document Schema dict; the raw per-column dict is also stashed as JSON into the `description` field (explicitly marked TEMPORARY in the module docstring).

**Public Interface** — `MistralClient(config, transport=None)`, `.generate()`, `.generate_with_file()`.

**Error Behaviour** — Never raises. Per-page retry-once-then-record-failure, same shape as M-027's per-page handling.

**Known Fragility** — This client's extraction prompt deliberately does **not** ask for per-row confidence or document metadata — diagnostic testing found the model's self-reported confidence unreliable (100% "HIGH" regardless of known transcription errors) and its own row counts disagreeing with its own output on 12 of 14 test pages. Every row therefore gets a fixed placeholder `ROW_CONFIDENCE = 0.75` regardless of actual per-row reliability — a future engineer expecting genuine per-row confidence from this provider (by analogy with M-025) would be wrong.

**Change Impact** — None currently — dormant.

**Callers** — M-023 (`get_ai_client("mistral")`, instantiation — no current caller reaches this without an explicit provider name)
**Calls** — none
**Integration Points Used** — IP-006 (Mistral Medium)
