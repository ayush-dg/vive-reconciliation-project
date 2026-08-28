#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npx tsx scripts/test_bounded_retry.mjs
