#!/usr/bin/env bash
# Session 5 integration check (EXECUTION_PLAN.md's literal verification command for the
# whole session): confirms the matching service — invocation/locking, deterministic
# matching, AI-assisted residual matching, exception schema wiring — works together
# end-to-end, on top of (not instead of) each task's own dedicated test script.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Typecheck =="
npx tsc --noEmit

echo
echo "== Task 5.1 — matching invocation (manual + scheduled) =="
npx tsx scripts/test_matching_invocation.mjs

echo
echo "== Task 5.2 — deterministic matching (SQL-based) =="
npx tsx scripts/test_deterministic_matching.mjs

echo
echo "== Task 5.3 — AI-assisted residual matching =="
npx tsx scripts/test_ai_residual_matching.mjs

echo
echo "== Task 5.4 — exception category enum + schema wiring =="
npx tsx scripts/test_exception_schema_wiring.mjs

echo
echo "== End-to-end round trip: register -> extract -> match -> Match/Exception =="
npx tsx scripts/e2e_matching_service_round_trip.mjs

echo
echo "Session 5 integration check: PASS"
