#!/usr/bin/env bash
# Thin wrapper matching EXECUTION_PLAN.md Task 2.3's literal Verification
# Command path — actual logic in test_document_status.mjs (tsx), consistent
# with every other verification script in this project.
set -euo pipefail
cd "$(dirname "$0")/.."
npx tsx scripts/test_document_status.mjs
