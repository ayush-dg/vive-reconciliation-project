**Module:** validationGate
**ID:** M-023
**Layer:** pipeline
**Primary Responsibility:** Pure function that runs Task 3.2's structural + arithmetic validation over an `ExtractedStatement`, producing a structured `ValidationResult` (never a bare boolean).

**Inputs:**
- `extracted: ExtractedStatement | null` — the only parameter. No DB access, no I/O — a pure function.

**Outputs:**
- Returns `ValidationResult` — no side effects, no mutation, nothing written anywhere. Pure.

**Public Interface:**
- `export function validateExtraction(extracted: ExtractedStatement | null): ValidationResult`
- `export type ValidationResult = { stage: 'validation'; status: 'pass' | 'fail'; reasonCodes: string[]; evidence: Record<string, unknown>; requiresReview: boolean }`

**Error Behaviour:** Never throws. `extracted === null` short-circuits to `{ status: 'fail', reasonCodes: ['EXTRACTION_ERROR'], requiresReview: true }` immediately. All numeric edge cases (NaN statement total, NaN line amount, NaN diff) are explicitly guarded rather than allowed to produce a false pass — the module's own comments flag these as deliberate fixes (`NaN > tolerance` is always false, so an unparseable total would otherwise silently pass without the explicit `Number.isNaN` check).

**Known Fragility:**
- Confidence is explicitly NOT part of this gate (G2, amended) — a future engineer adding a confidence threshold here would violate a documented architectural decision (G2/IC-2).
- `MISSING_IDENTIFIER` conflates two different failure meanings under one reason code: per-line structural issues (missing invoice_ref/ro_number, non-numeric amount, unparseable date) AND `vendorNameGuessMissing` (no vendor identifiable at all). The module's own comment explains WHY this was added (without it, a document with valid lines but no vendor would show `arithmetic_pass=1/structural_pass=1` and read as healthy forever, since vendor resolution never completes downstream) — but a future engineer reading `evidence.structuralIssues` alone (without checking `evidence.vendorNameGuessMissing`) could misdiagnose a missing-vendor failure as a per-line data problem.
- Arithmetic tolerance is a fixed constant (`0.01`, one cent) — not configurable per vendor. A statement with legitimate rounding behavior beyond one cent would always fail arithmetic validation with no override path.
- A blank/null line amount is treated as `0` for the arithmetic sum (documented as intentional — "a credit/payment line with no stated amount, not an error") — a future engineer unaware of this could mistake a genuinely missing amount for a valid zero-amount line when reading `evidence.arithmetic`.

**Change Impact:** `extractionPipeline.ts` (M-022) is the sole caller and derives `arithmeticPass`/`structuralPass` by checking `reasonCodes.includes(...)` against exact string literals (`'ARITHMETIC_MISMATCH'`, `'MISSING_IDENTIFIER'`) — renaming a reason code here silently breaks that downstream boolean derivation without a compile-time error (both sides use bare string literals, not a shared enum).

**Callers:** M-022
**Calls:** none (pure function, no internal pipeline calls)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
