#!/usr/bin/env bash
# REGRESSION_SUITE.sh — VIVE Statement Reconciliation
# Assembled at Phase 8 Part 1 (System Sign-Off), 2026-09-01.
# Consolidates every REGRESSION-RELEVANT and HARNESS-CANDIDATE task's verification
# command from docs/EXECUTION_PLAN.md into one runnable suite, per DG-Forge PBVI
# methodology (skills/PBVI/SKILL.md, Phase 8 Part 1 step 7).
#
# Non-portable commands (live Fabric, live Claude API key) and commands whose
# referenced script was never actually committed are INCLUDED with a reason,
# never silently omitted, per the same methodology step.
#
# Run: ./verification/REGRESSION_SUITE.sh   (from repo root)
# Exit codes: 0 = all runnable checks passed, 1 = at least one runnable check failed
#             (non-portable / missing-script items never affect the exit code — they
#             are reported separately as SKIP, not counted as failures)

set -uo pipefail
cd "$(dirname "$0")/.."

PASS=0
FAIL=0
SKIP=0

run_check() {
  local task_id="$1"
  local desc="$2"
  local command="$3"

  if eval "$command" > /tmp/regression_out 2>&1; then
    echo "PASS | Task $task_id | $desc"
    PASS=$((PASS + 1))
  else
    echo "FAIL | Task $task_id | $desc"
    echo "  command: $command"
    sed 's/^/  /' /tmp/regression_out | head -20
    FAIL=$((FAIL + 1))
  fi
}

skip_check() {
  local task_id="$1"
  local desc="$2"
  local command="$3"
  local reason="$4"

  echo "SKIP | Task $task_id | $desc"
  echo "  command: $command"
  echo "  reason:  $reason"
  SKIP=$((SKIP + 1))
}

echo "=== REGRESSION_SUITE — VIVE Statement Reconciliation ==="
echo ""

# ---------------------------------------------------------------------------
# Session 1 — Scaffolding, Auth, DB schema
# ---------------------------------------------------------------------------

skip_check "1.2" "Database schema (extracted/silver/recon foundation)" \
  'sqlcmd -S "$FABRIC_SQL_ENDPOINT" -d recon -i migrations/001_foundation_schema.sql && sqlcmd -S "$FABRIC_SQL_ENDPOINT" -d recon -Q "INSERT INTO extracted.document (legal_entity_id) VALUES (NULL);" 2>&1 | grep -q "not-null constraint"' \
  "NOT PORTABLE — requires sqlcmd + a live Fabric SQL endpoint (\$FABRIC_SQL_ENDPOINT), not the local SQLite fallback. Equivalent local check: npm run test:schema (see below)."

run_check "1.3" "Authentication (Sign In screen)" \
  "npx playwright test ui_tests/sign-in.spec.ts"

run_check "1.4" "Global elements (nav, logout, error boundary, loading, toast)" \
  "npx playwright test ui_tests/global-elements.spec.ts"

# ---------------------------------------------------------------------------
# Session 2 — Document intake
# ---------------------------------------------------------------------------

run_check "2.1" "Upload screen (UI)" \
  "npx playwright test ui_tests/upload.spec.ts"

run_check "2.2" "Document registration + content-hash dedup" \
  "./scripts/test_document_registration.sh"

run_check "2.3" "Home's status badge wiring" \
  "./scripts/test_document_status_computation.sh"

run_check "2.4" "Extract action (UI trigger + endpoint)" \
  "npx playwright test ui_tests/extract-trigger.spec.ts"

# ---------------------------------------------------------------------------
# Session 3 — Extraction service
# ---------------------------------------------------------------------------

run_check "3.1" "Vendor identification, extraction routing, attempt recording" \
  "./scripts/test_extraction_attempt_recording.sh"

run_check "3.2" "Arithmetic/structural validation gate" \
  "./scripts/test_validation_gate.sh"

run_check "3.3" "Bounded retry logic (max 2 attempts)" \
  "./scripts/test_bounded_retry.sh"

run_check "3.4" "Prompt injection defense (data vs. instructions)" \
  "./scripts/test_prompt_injection_defense.sh"

run_check "3.5" "Extraction-method summary endpoint" \
  "./scripts/test_extraction_method_summary.sh"

run_check "3.6" "Silver normalization (extracted -> silver.statement_line)" \
  "./scripts/test_silver_normalization.sh"

# ---------------------------------------------------------------------------
# Session 5 — Matching service
# ---------------------------------------------------------------------------

run_check "5.1" "Matching invocation (manual + scheduled)" \
  "./scripts/test_matching_invocation.sh"

run_check "5.2" "Deterministic matching (SQL-based)" \
  "./scripts/test_deterministic_matching.sh"

run_check "5.3" "AI-assisted residual matching (never auto-approves)" \
  "./scripts/test_ai_residual_matching.sh"

run_check "5.4" "Exception category enum + schema wiring" \
  "./scripts/test_exception_schema_wiring.sh"

# ---------------------------------------------------------------------------
# Session 6 — Home + Exceptions + Document Detail
# ---------------------------------------------------------------------------

run_check "6.1" "Home screen" \
  "npx playwright test ui_tests/home.spec.ts"

run_check "6.2" "Exceptions vendor-grouped list screen" \
  "npx playwright test ui_tests/exceptions.spec.ts"

run_check "6.3" "Exception vendor detail screen (two-pane + resolution workflow)" \
  "npx playwright test ui_tests/exception-detail.spec.ts"

run_check "6.4" "Global error/loading state wiring" \
  "npx playwright test ui_tests/loading-error-consistency.spec.ts"

run_check "6.5" "Document Detail screen" \
  "npx playwright test ui_tests/document-detail.spec.ts"

# ---------------------------------------------------------------------------
# Session 8 — Extraction quality improvements
# NOTE: per sessions/S08_VERIFICATION_RECORD.md, this session ran in lightweight-
# patch mode with no Challenge Agent review; Tasks 8.1/8.3/8.4/8.5's documented
# verification commands reference scripts that were never actually committed
# (confirmed absent from scripts/ as of this revision) — those tasks were
# code-review-verified only, not live-tested by an independent script. Recorded
# honestly here rather than fabricated as runnable.
# ---------------------------------------------------------------------------

skip_check "8.1" "Known-vendor deterministic extraction" \
  "npx tsx scripts/test_lia_deterministic_extraction.mjs" \
  "SCRIPT NOT FOUND — never committed. Task was live-verified manually during Session 8/9 (see EXECUTION_PLAN.md Task 9.2/9.3 real vendor sums) but has no independent regression script."

skip_check "8.2" "Live Claude extraction default path + OCR fallback tier" \
  'ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" npx tsx scripts/test_live_claude_extraction.mjs' \
  "NOT PORTABLE (requires a live ANTHROPIC_API_KEY) AND SCRIPT NOT FOUND — never committed."

skip_check "8.3" "Python OCR/pdfplumber fallback tier" \
  "npx tsx scripts/test_ocr_fallback.mjs" \
  "SCRIPT NOT FOUND — never committed. Per S08_VERIFICATION_RECORD.md, this path is also environmentally blocked (Tesseract/Poppler not installed) and was superseded by Task 9.6's finding that OCR is unnecessary for all 6 tested scanned vendors."

skip_check "8.4" "Better column mapping + real per-row confidence" \
  "npx tsx scripts/test_column_mapping_fallback.mjs" \
  "SCRIPT NOT FOUND — never committed. Code-review-verified only per S08_VERIFICATION_RECORD.md."

skip_check "8.5" "Row-level duplicate detection" \
  "npx tsx scripts/test_row_level_dedup.mjs" \
  "SCRIPT NOT FOUND — never committed. Per S08_VERIFICATION_RECORD.md, no real duplicate line existed in any tested document, so even manual verification was incomplete."

# ---------------------------------------------------------------------------
# Session 9 — Per-vendor deterministic parsers + real OCR investigation
# Tasks 9.1-9.5 have no per-task command of their own — all covered by the
# umbrella script built in Task 9.7 (renumbered from 9.8). Listed once below,
# not repeated five times.
# ---------------------------------------------------------------------------

echo "INFO | Tasks 9.1-9.5 | credit-sign prompt rules + 8 vendor parsers | covered by Task 9.7's umbrella script below, no separate per-task command"

run_check "9.7" "Umbrella verification: all known-vendor extractors reconcile to statement total" \
  "npx tsx scripts/verify_known_vendor_extractors.mjs"

# ---------------------------------------------------------------------------
# ENH-001 — UI clarity fixes + multiple PDF upload (SPRINT-001)
# Task IDs prefixed "ENH1-" to avoid colliding with the numbered build sessions'
# own Task 2.1-2.4 above (Document intake) - ENH-001 is a separate, later
# enhancement, not a renumbering of Session 2.
#
# Sessions 1 (Tasks 1.1-1.4) and 2 (Tasks 2.3, 2.4) extend EXISTING spec files
# already covered by the checks above - home.spec.ts (6.1), document-detail.spec.ts
# (6.5), upload.spec.ts (2.1) - not duplicated here as separate entries, since
# re-running those same commands already exercises ENH-001's additions to those
# same files.
# ---------------------------------------------------------------------------

run_check "ENH1-2.1" "Extraction crash-recovery (Silver-normalization failure + exhausted recovery)" \
  "./scripts/test_extraction_crash_recovery.sh"

run_check "ENH1-2.2" "Sequential batch upload (no two extractions in flight simultaneously)" \
  "./scripts/test_batch_upload_sequencing.sh"

run_check "ENH1-toast" "Toast store (M-009) regression - zero-diff confirmed separately via git, this just re-verifies the store's own behavior" \
  "npm run test:toast"

# Two post-sign-off hotfixes (H1/H2, sessions/SPRINT-001/ENH-001/S2_SESSION_LOG.md
# "Post-Sign-Off Hotfixes") are covered by the SAME existing document-detail.spec.ts
# entry above (6.5) - no separate entry needed, H1 has no dedicated script (its
# effect on the live-Claude path was never confirmed, per that section's own
# honest note - not something a portable regression check can exercise).

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

TOTAL=$((PASS + FAIL + SKIP))
echo ""
echo "REGRESSION SUITE SUMMARY"
echo "Total: $TOTAL  Passed: $PASS  Failed: $FAIL  Skipped(non-portable/missing-script): $SKIP"

if [ "$FAIL" -gt 0 ]; then
  exit 1
else
  exit 0
fi
