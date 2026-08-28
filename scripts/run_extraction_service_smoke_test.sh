#!/usr/bin/env bash
# Session 3 integration check (EXECUTION_PLAN.md's literal verification command for the
# whole session): confirms the extraction service — vendor routing, validation gate,
# bounded retry, prompt injection defense, method summary, Silver normalization — works
# together end-to-end, on top of (not instead of) each task's own dedicated test script.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Typecheck =="
npx tsc --noEmit

echo
echo "== Task 3.1 — vendor identification, routing, attempt recording =="
npx tsx scripts/test_extraction_attempt_recording.mjs

echo
echo "== Task 3.2 — arithmetic and structural validation gate =="
npx tsx scripts/test_validation_gate.mjs

echo
echo "== Task 3.3 — bounded retry logic =="
npx tsx scripts/test_bounded_retry.mjs

echo
echo "== Task 3.4 — prompt injection defense =="
npx tsx scripts/test_prompt_injection_defense.mjs

echo
echo "== Task 3.5 — extraction-method summary =="
npx tsx scripts/test_extraction_method_summary.mjs

echo
echo "== Task 3.6 — Silver normalization =="
npx tsx scripts/test_silver_normalization.mjs

echo
echo "== End-to-end round trip: register -> Extract trigger -> Silver =="
npx tsx scripts/e2e_extraction_service_round_trip.mjs

echo
echo "Session 3 integration check: PASS"
