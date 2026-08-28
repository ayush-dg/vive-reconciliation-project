#!/usr/bin/env bash
# Thin wrapper matching EXECUTION_PLAN.md Task 2.2's literal Verification
# Command path. Actual test logic lives in test_document_registration.mjs,
# consistent with every other verification script in this project (tsx-run
# TypeScript, not bash) — see scripts/test_foundation_schema.mjs, etc.
set -euo pipefail
cd "$(dirname "$0")/.."
npx tsx scripts/test_document_registration.mjs
