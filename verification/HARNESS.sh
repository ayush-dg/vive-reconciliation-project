#!/usr/bin/env bash
# HARNESS.sh — Live Invariant Assertion Harness — VIVE Statement Reconciliation
# Assembled at Phase 8 Part 1 (System Sign-Off), 2026-09-01, per DG-Forge PBVI
# methodology Template 9 (skills/PBVI/pbvi_templates.md).
# Run before each future sprint and after sprint close-out.
# Trigger: "Run harness check" in CC
#
# Output format (machine-readable):
#   [PASS|FAIL] | INV-ID | CRITICAL|WARNING | [command] | [output on failure]
#
# Exit codes: 0 = all pass, 1 = warnings only, 2 = critical failures
#
# Invariant IDs use this project's own registry (docs/INVARIANTS.md), not a
# generic INV-NNN scheme: G1-G5 (GLOBAL, = Claude.md's IC-1-5) and S1-S11
# (task-scoped). Assertions are populated only from HARNESS-CANDIDATE tasks in
# docs/EXECUTION_PLAN.md — REGRESSION-RELEVANT tasks live in REGRESSION_SUITE.sh
# only, per the methodology's own split.

set -uo pipefail
cd "$(dirname "$0")/.."
PASS=0
FAIL=0
CRITICAL_FAIL=0
WARNING_FAIL=0
NOT_RUN=0

run_assertion() {
  local inv_id="$1"
  local severity="$2"
  local command="$3"

  if eval "$command" > /tmp/harness_out 2>&1; then
    echo "PASS | $inv_id | $severity | $command"
    PASS=$((PASS + 1))
  else
    local output
    output=$(cat /tmp/harness_out)
    echo "FAIL | $inv_id | $severity | $command | $output"
    FAIL=$((FAIL + 1))
    if [ "$severity" = "CRITICAL" ]; then
      CRITICAL_FAIL=$((CRITICAL_FAIL + 1))
    else
      WARNING_FAIL=$((WARNING_FAIL + 1))
    fi
  fi
}

not_run() {
  local inv_id="$1"
  local severity="$2"
  local command="$3"
  local reason="$4"
  echo "NOT_RUN | $inv_id | $severity | $command | $reason"
  NOT_RUN=$((NOT_RUN + 1))
}

echo "=== HARNESS — VIVE Statement Reconciliation ==="
echo ""

# =============================================================================
# G1 — Extraction attempts belong to exactly one document, and are append-only
# (promoted from S9; = Claude.md IC-1). Also covers S4, S5, S10, S11 (Task 1.2
# creates the schema all of these depend on).
# Severity:         CRITICAL
# Expected outcome: schema migration applies cleanly; a NULL legal_entity_id
#                    insert is rejected by a NOT NULL constraint.
# Source: Task 1.2
# =============================================================================
not_run "G1" "CRITICAL" \
  'sqlcmd -S "$FABRIC_SQL_ENDPOINT" -d recon -i migrations/001_foundation_schema.sql && sqlcmd -S "$FABRIC_SQL_ENDPOINT" -d recon -Q "INSERT INTO extracted.document (legal_entity_id) VALUES (NULL);" 2>&1 | grep -q "not-null constraint"' \
  "NOT PORTABLE — requires live Fabric (\$FABRIC_SQL_ENDPOINT + sqlcmd). Local-fallback equivalent: npm run test:schema (run separately, not part of this harness's portable set)."

# =============================================================================
# G1 (re-asserted) / S10 / S2 — Vendor identification, extraction routing, and
# attempt recording: extracted schema write precedes validation; re-uploads are
# version-chained, not duplicated.
# Severity:         CRITICAL
# Expected outcome: scripts/test_extraction_attempt_recording.sh exits 0.
# Source: Task 3.1
# =============================================================================
run_assertion "G1" "CRITICAL" "./scripts/test_extraction_attempt_recording.sh"

# =============================================================================
# G2 — No unvalidated extraction becomes match-eligible (= Claude.md IC-2).
# Severity:         CRITICAL
# Expected outcome: scripts/test_validation_gate.sh exits 0 — structural +
#                    arithmetic gate enforced, confidence never used as a gate.
# Source: Task 3.2
# =============================================================================
run_assertion "G2" "CRITICAL" "./scripts/test_validation_gate.sh"

# =============================================================================
# G2 (re-asserted via known-vendor deterministic path) — every registered
# known-vendor extractor's output reconciles to its statement's own printed
# total within $0.01, across all 9 real vendors from Session 9.
# Severity:         CRITICAL
# Expected outcome: scripts/verify_known_vendor_extractors.mjs exits 0. Covers
#                    Tasks 9.2, 9.3, 9.4, 9.5, 9.7 collectively — they share
#                    this one umbrella command, not listed as 5 separate blocks.
# Source: Tasks 9.2-9.5, 9.7 (renumbered from 9.8)
# =============================================================================
run_assertion "G2" "CRITICAL" "npx tsx scripts/verify_known_vendor_extractors.mjs"

# =============================================================================
# G3 — Extracted content is model data, never model instructions (= Claude.md
# IC-3, prompt injection defense).
# Severity:         CRITICAL
# Expected outcome: scripts/test_prompt_injection_defense.sh exits 0.
# Source: Task 3.4
# =============================================================================
run_assertion "G3" "CRITICAL" "./scripts/test_prompt_injection_defense.sh"

# =============================================================================
# G3 (re-asserted) + AI-write-authority non-negotiable — AI-assisted residual
# matching never auto-approves, writes only a proposed field.
# Severity:         CRITICAL
# Expected outcome: scripts/test_ai_residual_matching.sh exits 0.
# Source: Task 5.3
# =============================================================================
run_assertion "G3" "CRITICAL" "./scripts/test_ai_residual_matching.sh"

# =============================================================================
# G4 — Content-hash idempotency (= Claude.md IC-4): byte-identical documents
# are never independently re-extracted or re-matched.
# Severity:         CRITICAL
# Expected outcome: scripts/test_document_registration.sh exits 0.
# Source: Task 2.2
# =============================================================================
run_assertion "G4" "CRITICAL" "./scripts/test_document_registration.sh"

# =============================================================================
# G5 — Single active processing owner (= Claude.md's G5). First harness assertion
# for this invariant — added at SPRINT-001 close-out (2026-09-06), ENH-001 Task
# 2.1's crash-recovery fix extended G5's existing enforcement (a finally-block
# equivalent status reset around the unchanged lock guard) and is the first task
# to give it dedicated harness coverage.
# Severity:         CRITICAL
# Expected outcome: scripts/test_extraction_crash_recovery.sh exits 0 — the
#                    atomic guard rejects a genuinely-processing document
#                    unchanged (TC-5), AND a recoverable/exhausted failure
#                    resets status back to 'registered' rather than leaving it
#                    permanently stuck (TC-4, TC-6, TC-7).
# Source: ENH-001 Task 2.1 (SPRINT-001)
# =============================================================================
run_assertion "G5" "CRITICAL" "./scripts/test_extraction_crash_recovery.sh"

# =============================================================================
# G4 (re-asserted, batch-upload context) — sequential batch processing must not
# bypass the existing content-hash dedup path (registerDocument()'s race-tolerant
# catch block, relied on unchanged).
# Severity:         CRITICAL
# Expected outcome: scripts/test_batch_upload_sequencing.sh exits 0 — no two
#                    extractions in flight simultaneously (the acceptance
#                    criterion this task exists to guarantee), and a duplicate
#                    hit within one batch is skipped, not double-registered.
# Source: ENH-001 Task 2.2 (SPRINT-001)
# =============================================================================
run_assertion "G4" "CRITICAL" "./scripts/test_batch_upload_sequencing.sh"

# =============================================================================
# S6 — Normalization version traceability.
# Severity:         WARNING
# Expected outcome: scripts/test_silver_normalization.sh exits 0.
# Source: Task 3.6
# =============================================================================
run_assertion "S6" "WARNING" "./scripts/test_silver_normalization.sh"

# =============================================================================
# S7 — Extraction attempts are bounded (max 2, then OCR_LOW_CONFIDENCE).
# Severity:         WARNING
# Expected outcome: scripts/test_bounded_retry.sh exits 0.
# Source: Task 3.3
# =============================================================================
run_assertion "S7" "WARNING" "./scripts/test_bounded_retry.sh"

# =============================================================================
# S8 — Reference data is version-bound [AMENDED 2026-08-28 — satisfied by
# capturing _run_id/_extracted_at/_source_system at match time, not a formal
# ReferenceSnapshot entity].
# Severity:         WARNING
# Expected outcome: scripts/test_deterministic_matching.sh exits 0.
# Source: Task 5.2
# =============================================================================
run_assertion "S8" "WARNING" "./scripts/test_deterministic_matching.sh"

# =============================================================================
# S5 / S8 (amended) — Exception category is a closed enum; schema wiring.
# Severity:         WARNING
# Expected outcome: scripts/test_exception_schema_wiring.sh exits 0.
# Source: Task 5.4
# =============================================================================
run_assertion "S5" "WARNING" "./scripts/test_exception_schema_wiring.sh"

# =============================================================================
# G1/G2 (unchanged, consumed not re-defined) — known-vendor deterministic
# extraction bypass.
# Severity:         CRITICAL
# Expected outcome: not determinable — script never committed.
# Source: Task 8.1
# =============================================================================
not_run "G1" "CRITICAL" "npx tsx scripts/test_lia_deterministic_extraction.mjs" \
  "SCRIPT NOT FOUND — never committed. Session 8 ran in lightweight-patch mode with no Challenge Agent review (sessions/S08_VERIFICATION_RECORD.md); this task was code-review-verified only."

# =============================================================================
# G3 (unchanged) — live Claude extraction default path + OCR fallback tier.
# Severity:         CRITICAL
# Expected outcome: not determinable — script never committed, and the command
#                    itself requires a live ANTHROPIC_API_KEY.
# Source: Task 8.2
# =============================================================================
not_run "G3" "CRITICAL" 'ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" npx tsx scripts/test_live_claude_extraction.mjs' \
  "NOT PORTABLE (live API key) AND SCRIPT NOT FOUND — never committed."

# =============================================================================
# G2 (reaffirmed, IC-2) — real per-row model-reported confidence remains
# diagnostic-only, never a gate.
# Severity:         CRITICAL
# Expected outcome: not determinable — script never committed.
# Source: Task 8.4
# =============================================================================
not_run "G2" "CRITICAL" "npx tsx scripts/test_column_mapping_fallback.mjs" \
  "SCRIPT NOT FOUND — never committed. Code-review-verified only per sessions/S08_VERIFICATION_RECORD.md."

# =============================================================================
# S12 (candidate, not yet formally added to INVARIANTS.md — see EXECUTION_PLAN.md
# Task 8.5's own "Invariant enforcement: TBD" note) — row-level duplicate
# detection.
# Severity:         WARNING
# Expected outcome: not determinable — script never committed, and no real
#                    duplicate line existed in any tested document even for the
#                    manual check that was done.
# Source: Task 8.5
# =============================================================================
not_run "S12(candidate)" "WARNING" "npx tsx scripts/test_row_level_dedup.mjs" \
  "SCRIPT NOT FOUND — never committed. No formal invariant ID assigned yet (engineer decision open, see INVARIANTS.md)."

# =============================================================================
# HARNESS SUMMARY
# =============================================================================
TOTAL=$((PASS + FAIL))
echo ""
echo "HARNESS SUMMARY"
echo "Total run: $TOTAL  Passed: $PASS  Failed: $FAIL  (CRITICAL: $CRITICAL_FAIL  WARNING: $WARNING_FAIL)  Not run (non-portable/missing script): $NOT_RUN"

if [ "$CRITICAL_FAIL" -gt 0 ]; then
  exit 2
elif [ "$FAIL" -gt 0 ]; then
  exit 1
else
  exit 0
fi
