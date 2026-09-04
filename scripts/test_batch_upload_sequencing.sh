#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npx tsx scripts/test_batch_upload_sequencing.mjs
