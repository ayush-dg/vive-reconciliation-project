**Module:** exceptionWriter.ts
**ID:** M-020
**Layer:** serving
**Primary Responsibility:** The single write path for creating `recon_exception` rows — validates the category enum and persists reason codes, evidence, and optional reference-data provenance as an INSERT.

**Inputs:** `writeException(input: ExceptionInput)` — `{ statementLineId: string; category: ExceptionCategory ('amount_mismatch'|'not_posted'); reasonCodes: string[]; evidence: Record<string, unknown>; reference: { runId: string; extractedAt: string; sourceSystem: string } | null }`. `category` is runtime-validated against `VALID_CATEGORIES`; `statementLineId`, `reasonCodes`, and `evidence` shape are not validated here — trusted from the caller (M-025/`matchingPipeline.ts`), which sources them from its own structured deterministic/residual matching results per ARCHITECTURE.md D-K.

**Outputs:** Side effect only — INSERT into `recon_exception` (`exception_id` generated via `crypto.randomUUID()`; `reasonCodes` and `evidence` are `JSON.stringify`'d before storage). No return value (`void`).

**Public Interface:**
- `export const VALID_CATEGORIES = ['amount_mismatch', 'not_posted'] as const`
- `export type ExceptionCategory = (typeof VALID_CATEGORIES)[number]`
- `export type ExceptionInput`
- `export function writeException(input: ExceptionInput): void`

**Error Behaviour:** Throws an uncaught `Error` if `input.category` is not in `VALID_CATEGORIES` — defense-in-depth ahead of the DB's own CHECK constraint, matching the pattern documented as shared with `vendorSchema.ts`'s `assertValidVendorSlug`. No try/catch around the INSERT itself — any DB error (e.g. a constraint violation the pre-check didn't catch, or a FK violation on `statementLineId`) propagates uncaught to the caller (M-025).

**Known Fragility:**
- `owner`/`aging_started_at`/`run_reference` columns are deliberately left NULL by this writer ("reserved for BCE, never populated here" per the module's own comment) — a future engineer building out that feature must remember this write path needs updating too; nothing here would fail or warn if forgotten, the columns would simply stay perpetually NULL.
- No validation of `evidence`'s internal shape — this module trusts the caller completely for the evidence/reasonCodes contract (D-K). Since M-018 later reads this same evidence blob with untyped `as` casts, any drift between what M-025's callers actually write here and what M-018 expects to read would surface only as silently-missing fields on the Exception Detail screen, never as an error at write time.
- `writeException` is a pure fire-and-forget insert with no idempotency/dedup guard of its own (unlike `documents.ts`'s `registerDocument`) — if a caller invokes it twice for the same statement line (e.g. a retry after a partial matching-pipeline failure), two exception rows would be created with nothing preventing it, visible only as a count anomaly downstream (M-013/M-014) — NOT DETERMINABLE FROM SOURCE whether M-025 provides its own protection against this upstream.

**Change Impact:** M-025 is the sole caller — the entire exception-creation path (deterministic no-match/amount-mismatch, Task 5.2; and the AI residual pass, Task 5.3) funnels through this one function. A change to `ExceptionInput`'s required fields or `VALID_CATEGORIES` breaks M-025's matching pipeline directly, and transitively every downstream exception consumer (M-018, M-019).

**Callers:** M-025
**Calls:** M-003
**Integration Points Used:** None (routes through M-003)
