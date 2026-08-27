## C07 — AI Client Contract
ID: M-022
Layer: pipeline
Source file: `src/ai/base_client.py`

**Module** — AI Client Contract
**ID** — M-022
**Layer** — pipeline
**Primary Responsibility** — Defines the `AIClient` abstract interface and `AIResponse` dataclass every concrete provider adapter implements and returns.

**Inputs** — None (pure type/interface definitions).

**Outputs** — None (no side effects; a contract module).

**Public Interface** — `AIResponse` (dataclass: `success`, `text`, `parsed_json`, `model`, `provider`, `latency_ms`, `attempt_count`, `error`, `raw_response`), `AIClient` (ABC with abstract `generate()`).

**Error Behaviour** — N/A — no executable logic beyond the abstract method declaration (raises `NotImplementedError` if a subclass fails to override it, standard ABC behavior).

**Known Fragility** — `AIClient` only formally declares `generate()` as abstract — every concrete client (M-025–M-030) also implements `generate_with_file()`, which is not part of this formal contract; `document_understanding_engine.py` (M-024) calls `generate_with_file()` directly, meaning the real, load-bearing interface is broader than what this file enforces. A new provider adapter that implements only `generate()` would type-check against this contract but fail at runtime the moment M-024 calls `generate_with_file()`.

**Change Impact** — Any change to `AIResponse`'s fields is a breaking change across all 6 concrete clients (M-025–M-030) and every consumer of their return values (M-024, M-033, M-040).

**Callers** — M-025, M-026, M-027, M-028, M-029, M-030 (all implement/extend this contract)
**Calls** — none
**Integration Points Used** — none
