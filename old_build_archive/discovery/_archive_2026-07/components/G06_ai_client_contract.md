## G06 — AI client contract
ID: M-030
Layer: infra
Source file: src/ai/base_client.py

**Module** — AI client contract
**ID** — M-030
**Layer** — infra
**Primary Responsibility** — Defines the `AIClient` abstract interface and `AIResponse` dataclass every provider adapter implements; nothing outside `src/ai/` imports a concrete provider class directly.

**Inputs/Outputs** — N/A — pure interface/data-shape definitions, no runtime behavior of its own.

**Public Interface**
- `class AIResponse` (dataclass): `success: bool`, `text: str = ""`, `parsed_json: Optional[dict] = None`, `model: str = ""`, `provider: str = ""`, `latency_ms: float = 0.0`, `attempt_count: int = 1`, `error: Optional[str] = None`, `raw_response: Any = None` (excluded from `repr`).
- `class AIClient(ABC)`: one abstract method, `generate(self, prompt, *, temperature=None, max_output_tokens=None) -> AIResponse`.

**Error Behaviour** — N/A (no executable logic beyond the ABC contract itself).

**Known Fragility** — The interface only formally declares `generate()` as abstract — `generate_with_file()` (implemented by 5 of the 6 concrete clients: all except none — actually all 6 implement it, including `ClaudeClient`, `AzureOpenAIClient`, `DocumentIntelligenceClient`, `GeminiClient`, `MistralClient`, `ClaudeSonnetClient`) is a de-facto second required method that every real caller (`document_understanding_engine.py`) actually depends on, but it is **not** part of the formal `AIClient` ABC contract — a new provider client that implements only `generate()` would satisfy the abstract base class but silently fail at runtime the moment `document_understanding_engine.py` calls `generate_with_file()` on it (an `AttributeError`, not a caught, clean failure). Worth an INVARIANT_CATALOGUE.md candidate at Session D.

**Change Impact** — Any change to `AIResponse`'s fields ripples to all 6 concrete clients (`src/ai/*_client.py`) and to every consumer that reads response fields (`document_understanding_engine.py`, `explanation_service.py`, `audit_logger.py`).

**Callers** — M-021, M-022, M-023, M-024, M-025, M-026 (all six concrete clients import `AIClient`/`AIResponse`)
**Calls** — none
**Integration Points Used** — none
