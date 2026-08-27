#!/usr/bin/env bash
# launch.sh — Unified session launcher for greenfield and enhancement builds
# Usage: ./tools/launch.sh <mode> <identifier> <session-id>
# Examples:
#   ./tools/launch.sh greenfield myproject S01
#   ./tools/launch.sh enhancement ENH-001 S02
#
# NOTE: Autonomous mode only. Manual mode sessions are run directly
# in CC using "Start manual session [N]" — do not use this script.

set -euo pipefail

MODE="${1:?Usage: launch.sh <greenfield|enhancement> <identifier> <session-id>}"
IDENTIFIER="${2:?Usage: launch.sh <greenfield|enhancement> <identifier> <session-id>}"
SESSION="${3:?Usage: launch.sh <greenfield|enhancement> <identifier> <session-id>}"

# ── Resolve paths ────────────────────────────────────────────────────────────
if [ "$MODE" = "greenfield" ]; then
  PROMPT_FILE="sessions/${SESSION}_execution_prompt.md"
  OUTPUT_FILE="sessions/${SESSION}_agent_output.log"
  LOG_FILE="sessions/${SESSION}_SESSION_LOG.md"

  # Serial gate — S01 has no prior session to check
  SESSION_NUM="${SESSION#S}"
  if [ "$SESSION_NUM" -gt 1 ]; then
    PREV_NUM=$((SESSION_NUM - 1))
    PREV_SESSION="S$(printf '%02d' $PREV_NUM)"
    PREV_LOG="sessions/${PREV_SESSION}_SESSION_LOG.md"

    if ! grep -q "^SIGNED OFF:" "$PREV_LOG" 2>/dev/null; then
      echo ""
      echo "🚫  SERIAL GATE — ${PREV_SESSION} not signed off."
      echo "    Sign off sessions/${PREV_SESSION}_SESSION_LOG.md before"
      echo "    launching ${SESSION}."
      echo ""
      exit 1
    fi
  fi

elif [ "$MODE" = "enhancement" ]; then
  # Derive sprint from REGISTRY.md
  SPRINT=$(grep "$IDENTIFIER" enhancements/REGISTRY.md 2>/dev/null \
    | grep -o 'SPRINT-[0-9]*' | head -1)

  if [ -z "$SPRINT" ]; then
    echo "ERROR: Cannot resolve sprint for ${IDENTIFIER} from REGISTRY.md"
    exit 1
  fi

  BASE="sessions/${SPRINT}/${IDENTIFIER}"
  PROMPT_FILE="${BASE}/${SESSION}_execution_prompt.md"
  OUTPUT_FILE="${BASE}/${SESSION}_agent_output.log"
  LOG_FILE="${BASE}/${SESSION}_SESSION_LOG.md"
  # No serial gate for enhancements — parallel execution permitted

else
  echo "ERROR: mode must be 'greenfield' or 'enhancement'. Got: ${MODE}"
  exit 1
fi

# ── Pre-flight checks ────────────────────────────────────────────────────────
if [ ! -f "$PROMPT_FILE" ]; then
  echo ""
  echo "ERROR: Prompt file not found: ${PROMPT_FILE}"
  echo "Run 'Produce session prompt files for this project' in CD (Phase 5)"
  echo "before launching any session."
  echo ""
  exit 1
fi

# ── Launch ───────────────────────────────────────────────────────────────────
echo ""
echo "[$(date +%H:%M:%S)] Launching ${MODE} ${IDENTIFIER} ${SESSION}..."
echo "Output: ${OUTPUT_FILE}"
echo ""

claude --print "$(cat "$PROMPT_FILE")" | tee "$OUTPUT_FILE"

echo ""

# ── Parse outcome ────────────────────────────────────────────────────────────
if grep -q "SESSION COMPLETE" "$OUTPUT_FILE" 2>/dev/null; then
  echo "✅  ${IDENTIFIER} ${SESSION} — COMPLETE"
  echo "    Sign off: ${LOG_FILE}"
  exit 0
elif grep -q "SESSION BLOCKED" "$OUTPUT_FILE" 2>/dev/null; then
  echo "⚠️   ${IDENTIFIER} ${SESSION} — BLOCKED"
  echo "    Diagnose: ${OUTPUT_FILE}"
  echo "    Resume:   ./tools/resume_session.sh ${MODE} ${IDENTIFIER} ${SESSION} <task-id> \"<fix>\""
  exit 1
elif grep -q "SCOPE VIOLATION" "$OUTPUT_FILE" 2>/dev/null; then
  echo "🚫  ${IDENTIFIER} ${SESSION} — SCOPE VIOLATION"
  echo "    Review:   ${OUTPUT_FILE}"
  echo "    Resolve:  ACCEPT or REVERT, then resume_session.sh"
  exit 3
elif grep -q "CHALLENGE FINDINGS" "$OUTPUT_FILE" 2>/dev/null; then
  echo "⚠️   ${IDENTIFIER} ${SESSION} — CHALLENGE FINDINGS"
  echo "    Review:   ${OUTPUT_FILE}"
  echo "    Resume:   ./tools/resume_challenge.sh ${MODE} ${IDENTIFIER} ${SESSION} <task-id>"
  exit 4
elif grep -q "PRE-BUILD-PAUSED" "$OUTPUT_FILE" 2>/dev/null; then
  echo "⏸️   ${IDENTIFIER} ${SESSION} — PRE-BUILD VALIDATION PAUSED"
  echo "    Review: ${OUTPUT_FILE}"
  echo "    Log:    ${LOG_FILE}"
  echo "    After review, if CONFIRMED: re-run ./tools/launch.sh ${MODE} ${IDENTIFIER} ${SESSION}"
  echo "    If -WRONG: return to planning, amend Claude.md, then re-run."
  exit 5
elif grep -q "LAUNCH ERROR" "$OUTPUT_FILE" 2>/dev/null; then
  echo "🚫  ${IDENTIFIER} ${SESSION} — LAUNCH ERROR"
  echo "    Fix:      ${OUTPUT_FILE}"
  exit 2
else
  echo "❓  ${IDENTIFIER} ${SESSION} — UNKNOWN OUTCOME"
  echo "    Review:   ${OUTPUT_FILE}"
  exit 99
fi
