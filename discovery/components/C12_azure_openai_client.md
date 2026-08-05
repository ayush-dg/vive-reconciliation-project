## C12 — Azure OpenAI Client
ID: M-027
Layer: pipeline
Source file: `src/ai/azure_openai_client.py`

**Module** — Azure OpenAI Client
**ID** — M-027
**Layer** — pipeline
**Primary Responsibility** — Dormant (not in the active provider chain). One class serving three deployment configs (gpt-5-mini/nano/5.1) via the Responses API, reachable only through an explicit `get_ai_client("azure_gpt5_*")` call.

**Inputs** — `config` (one of 3 `config/ai/azure_gpt5_*.json` files); env vars for API key/endpoint/deployment.

**Outputs** — `AIResponse` — per-page extraction results aggregated into one document result.

**Public Interface** — `AzureOpenAIClient(config, transport=None)`, `.generate()`, `.generate_with_file()`.

**Error Behaviour** — Never raises out of either public method. Per-page calls in `generate_with_file()` retry once before recording that page as failed — one bad page doesn't abort the document. `_extract_text_or_error()` specifically detects `status == "incomplete"` (a reasoning-model quirk where the token budget was exhausted on internal reasoning before any visible output) and converts it to a clear "raise max_output_tokens" error rather than a silent empty success.

**Known Fragility**
- Sends `temperature` as an accepted-but-never-forwarded parameter — these reasoning models reject it outright (400) if sent; a future engineer "fixing" this to actually pass temperature through would break every call.
- `generate_with_file()` splits the PDF into per-page files via `pypdf`, and for scanned (no-text-layer) pages, rasterizes them itself at a controlled DPI rather than sending the raw PDF page — a direct response to a documented failure mode (Azure's own internal PDF-to-image conversion produced invoice-number corruption in testing). A future engineer routing scanned pages back through the raw-PDF path would silently reintroduce that corruption risk.
- Not exercised by any live traffic (dormant) — its retry/truncation-salvage logic has no production signal confirming it still works correctly against the current Responses API version.

**Change Impact** — None currently — dormant, reachable only via explicit direct call, not through `active_provider.json`'s chain.

**Callers** — M-023 (`get_ai_client("azure_gpt5_mini"|"azure_gpt5_nano"|"azure_gpt5_1")`, instantiation — no current caller reaches this without an explicit provider name)
**Calls** — none
**Integration Points Used** — IP-003 (Azure OpenAI)
