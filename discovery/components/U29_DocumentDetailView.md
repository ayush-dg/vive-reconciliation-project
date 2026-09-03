**Module:** DocumentDetailView
**ID:** M-076
**Layer:** component
**Primary Responsibility:** Client-side single-document detail screen — status/actions header, extraction-provider summary strip, and the full extracted-lines table, with Extract/Reconcile actions and manual refresh.

**Inputs (Props):** `{ detail: DocumentDetailData }` (type from `@/lib/documentDetail`, out-of-scope M-013).
**Outputs (Rendered UI + Side Effects):**
- Renders a topbar (vendor name or "Identifying…", a "Back to Home" link to `/home`), a status panel with a status badge, statement period, and conditional Extract/Reconcile buttons; an "Extraction summary" panel counting lines by `providerUsed`, each label passed through a local `providerLabel()` map (`python_library_pdfplumber` → "Deterministic (pdfplumber)", `claude_sonnet` → "Claude Sonnet", `pdfplumber_fallback` → "via OCR fallback", `unknown` → "Unknown (extraction failed before a provider was selected)"); an extracted-lines table (Invoice Ref/Amount/Confidence/Provider) with a computed reconciliation-progress summary sentence.
- `refresh()`: `GET /api/documents/{id}/detail` (M-045) — sets `loadError` on failure (never throws, decoupled from action try/catches, same pattern as M-068).
- `handleExtract()`: `POST /api/documents/{id}/extract` (M-046) — same 409/non-ok/exception → toast pattern as M-068/M-070.
- `handleReconcile()`: `POST /api/documents/{id}/match` (M-047) — same 409/non-ok/exception → toast pattern.
**State Consumed:** Reads `useToast()` (M-083) at lines 31, 58, 64, 67, 70, 82, 88, 91, 94. All other state (`detail`, `extracting`, `reconciling`, `loadError`) is local `useState`, seeded from the `detail` prop.
**Public Interface:** `export default function DocumentDetailView({ detail: initialDetail }: { detail: DocumentDetailData })`; internal (non-exported) `providerLabel()`.
**Error Behaviour:** `refresh()` sets `loadError`, rendering `<InlineLoadError onRetry={refresh} />` (M-081). `handleExtract`/`handleReconcile` show toasts on 409 or other failure, never throw. Reconciliation-progress text asserts (via comment, not a runtime check) that `processed` (`matchedLines + exceptionLines`) is "always either 0 or totalLines, never a partial figure" because "matchingPipeline.ts commits a document's matching results atomically" — this is an *assumed* invariant from an out-of-scope module, not verified here.
**Known Fragility:** `canExtract`/`canReconcile` gating (`status === 'registered'` / `status === 'processing' && statusBadge.badge === 'Extracted'`) duplicates the identical logic in M-068 (Home) and, in a related form, M-070 (Upload) — a rule change made in only one place produces inconsistent action availability between Home, Upload, and Document Detail for the same document. `PROVIDER_LABELS` is a hard-coded map — an extraction provider value not in this map (and not `'unknown'`) falls back to displaying the raw internal string per `providerLabel`'s `?? provider` fallback, which is a silent UX regression (no crash, just an unlabeled/technical-looking value) rather than an error.
**Change Impact:** Changes to `DocumentDetailData` shape (M-013) or to `/api/documents/{id}/detail` (M-045), `/extract` (M-046), `/match` (M-047) response shapes break this component. Adding a new extraction provider upstream requires updating `PROVIDER_LABELS` here or it silently displays raw provider strings.
**Callers:** M-075 (DocumentDetailPage) renders this.
**Calls:** M-083 (useToast, many lines: 31, 58, 64, 67, 70, 82, 88, 91, 94); fetch `GET /api/documents/{id}/detail` (line 39, → M-045); fetch `POST /api/documents/{id}/extract` (line 56, → M-046); fetch `POST /api/documents/{id}/match` (line 80, → M-047).
**Renders:** M-081 (InlineLoadError, conditional on `loadError`).
**Integration Points Used:** None (fetches internal API routes only).
