#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npx tsx scripts/test_prompt_injection_defense.mjs
