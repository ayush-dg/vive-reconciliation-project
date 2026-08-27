#!/usr/bin/env bash
# resume_session.sh — Resume a BLOCKED or SCOPE VIOLATION stopped session
# Usage: ./tools/resume_session.sh <mode> <identifier> <session-id> <task-id> "<fix>"
# Examples:
#   ./tools/resume_session.sh greenfield myproject S02 T-03 "Added missing env var"
#   ./tools/resume_session.sh enhancement ENH-001 S01 T-02 "Reverted out-of-scope change"

set -euo pipefail

MODE="${1:?Usage: resume_session.sh <mode> <identifier> <session-id> <task-id> \"<fix>\"}"
IDENTIFIER="${2:?}"
SESSION="${3:?}"
BLOCKED_TASK="${4:?}"
FIX_DESC="${5:?}"

# ── Resolve log path ─────────────────────────────────────────────────────────
if [ "$MODE" = "greenfield" ]; then
  OUTPUT_FILE="sessions/${SESSION}_resume_output.log"
  LOG_FILE="sessions/${SESSION}_SESSION_LOG.md"
  EXEC_PLAN="docs/EXECUTION_PLAN.md"
elif [ "$MODE" = "enhancement" ]; then
  SPRINT=$(grep "$IDENTIFIER" enhancements/REGISTRY.md 2>/dev/null \
    | grep -o 'SPRINT-[0-9]*' | head -1)
  BASE="sessions/${SPRINT}/${IDENTIFIER}"
  OUTPUT_FILE="${BASE}/${SESSION}_resume_output.log"
  LOG_FILE="${BASE}/${SESSION}_SESSION_LOG.md"
  EXEC_PLAN=$(find enhancements -name "${IDENTIFIER}_EXECUTION_PLAN.md" | head -1)
else
  echo "ERROR: mode must be 'greenfield' or 'enhancement'."
  exit 1
fi

# ── Resume prompt ────────────────────────────────────────────────────────────
RESUME_PROMPT="You are resuming ${SESSION} — ${IDENTIFIER} after a stop.

Stopped task: ${BLOCKED_TASK}
Fix applied:  ${FIX_DESC}

Before any action, read in order:
1. docs/Claude.md
2. ${EXEC_PLAN}
3. ${LOG_FILE}

STATE VERIFICATION
- Confirm all tasks with Status = Completed have matching commits on
  the session branch.
- Confirm the stopped task matches ${BLOCKED_TASK}.
- If any inconsistency: stop and report. Do not attempt to resolve it.

If state verification passes:
- Add a resume row to the Resumed Sessions table in ${LOG_FILE}:
  Resumed at: [timestamp]
  Resumed from: ${BLOCKED_TASK}
  Blocking issue resolution: ${FIX_DESC}
  Resolved at: [timestamp]
  Root cause: [PLANNING GAP | ENVIRONMENTAL | SCOPE CREEP]

RESUME TASK ${BLOCKED_TASK}
Re-run from scratch using the task prompt from ${EXEC_PLAN}.
Apply all TASK-LEVEL VERIFICATION steps from the session execution
prompt: file boundary check, pre-commit declaration, challenge agent,
BCE impact, out of scope observations, commit, session log update.

If verification passes: proceed to all remaining tasks in ${SESSION}.
If verification fails again: output SESSION BLOCKED (second attempt)
and stop. Do not proceed further.

All FAILURE HANDLING, SCOPE VIOLATION HANDLING, CHALLENGE FINDINGS
HANDLING, git hygiene, scope boundary, and invariant rules from the
original session execution prompt continue to apply."

echo ""
echo "[$(date +%H:%M:%S)] Resuming ${IDENTIFIER} ${SESSION} from ${BLOCKED_TASK}..."

claude --print "$RESUME_PROMPT" | tee "$OUTPUT_FILE"

echo ""

if grep -q "^  SESSION COMPLETE" "$OUTPUT_FILE" 2>/dev/null; then
  echo "✅  ${IDENTIFIER} ${SESSION} — COMPLETE after resume"
  echo "    Sign off: ${LOG_FILE}"
  exit 0
elif grep -q "^  SESSION BLOCKED" "$OUTPUT_FILE" 2>/dev/null; then
  echo "⚠️   ${IDENTIFIER} ${SESSION} — BLOCKED again"
  echo "    Needs direct attention: ${OUTPUT_FILE}"
  exit 1
elif grep -q "^  SCOPE VIOLATION" "$OUTPUT_FILE" 2>/dev/null; then
  echo "🚫  ${IDENTIFIER} ${SESSION} — SCOPE VIOLATION on resume"
  echo "    Review: ${OUTPUT_FILE}"
  exit 3
elif grep -q "^  CHALLENGE FINDINGS" "$OUTPUT_FILE" 2>/dev/null; then
  echo "⚠️   ${IDENTIFIER} ${SESSION} — CHALLENGE FINDINGS on resume"
  echo "    Resume: ./tools/resume_challenge.sh ${MODE} ${IDENTIFIER} ${SESSION} ${BLOCKED_TASK}"
  exit 4
else
  echo "❓  ${IDENTIFIER} ${SESSION} — UNKNOWN OUTCOME"
  echo "    Review: ${OUTPUT_FILE}"
  exit 99
fi
