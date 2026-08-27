#!/usr/bin/env bash
# resume_challenge.sh — Resume after engineer dispositions CHALLENGE FINDINGS
# Usage: ./tools/resume_challenge.sh <mode> <identifier> <session-id> <task-id>
# Then paste dispositions when prompted, ending with END_DISPOSITIONS
# Example: ./tools/resume_challenge.sh greenfield myproject S02 T-03

set -euo pipefail

MODE="${1:?Usage: resume_challenge.sh <mode> <identifier> <session-id> <task-id>}"
IDENTIFIER="${2:?}"
SESSION="${3:?}"
TASK="${4:?}"

# ── Resolve paths ────────────────────────────────────────────────────────────
if [ "$MODE" = "greenfield" ]; then
  OUTPUT_FILE="sessions/${SESSION}_challenge_resume_output.log"
  LOG_FILE="sessions/${SESSION}_SESSION_LOG.md"
  EXEC_PLAN="docs/EXECUTION_PLAN.md"
elif [ "$MODE" = "enhancement" ]; then
  SPRINT=$(grep "$IDENTIFIER" enhancements/REGISTRY.md 2>/dev/null \
    | grep -o 'SPRINT-[0-9]*' | head -1)
  BASE="sessions/${SPRINT}/${IDENTIFIER}"
  OUTPUT_FILE="${BASE}/${SESSION}_challenge_resume_output.log"
  LOG_FILE="${BASE}/${SESSION}_SESSION_LOG.md"
  EXEC_PLAN=$(find enhancements -name "${IDENTIFIER}_EXECUTION_PLAN.md" | head -1)
else
  echo "ERROR: mode must be 'greenfield' or 'enhancement'."
  exit 1
fi

# ── Collect dispositions interactively ───────────────────────────────────────
echo ""
echo "Enter engineer dispositions for ${SESSION} ${TASK} findings."
echo "One per line. Format:"
echo "  ACCEPT [N] — <rationale>"
echo "  TEST [N] — <test case description>"
echo "Type END_DISPOSITIONS on its own line when done."
echo ""

DISPOSITIONS=""
while IFS= read -r line; do
  [ "$line" = "END_DISPOSITIONS" ] && break
  DISPOSITIONS="${DISPOSITIONS}${line}"$'\n'
done

# ── Resume prompt ─────────────────────────────────────────────────────────────
RESUME_PROMPT="You are resuming ${SESSION} — ${IDENTIFIER} after CHALLENGE FINDINGS
on task ${TASK}.

Engineer dispositions:
${DISPOSITIONS}

Before any action, read in order:
1. docs/Claude.md
2. ${EXEC_PLAN}
3. ${LOG_FILE}

APPLY DISPOSITIONS FOR TASK ${TASK}
For each ACCEPT disposition:
- Write the finding number and rationale into the Finding dispositions
  table in the Verification Record for ${TASK}.
- No test required. Mark disposition = ACCEPTED.

For each TEST disposition:
- Add the specified test case to the Verification Record for ${TASK}.
- Run the test immediately.
- If PASS: record result, mark disposition = TESTED — PASS.
- If FAIL: invoke FAILURE HANDLING. Stop. Output SESSION BLOCKED.

After all dispositions applied:
- If all PASS or ACCEPTED: update Status in session log to Completed.
- Commit using mandatory scope declaration format.
- Update session log with commit hash.
- Proceed to all remaining tasks in ${SESSION}.

All TASK-LEVEL VERIFICATION steps (file boundary check, pre-commit
declaration, challenge agent, BCE impact, out of scope observations),
git hygiene, scope boundary, and invariant rules continue to apply
for all remaining tasks."

echo ""
echo "[$(date +%H:%M:%S)] Resuming ${IDENTIFIER} ${SESSION} ${TASK} after findings..."

claude --print "$RESUME_PROMPT" | tee "$OUTPUT_FILE"

echo ""

if grep -q "^  SESSION COMPLETE" "$OUTPUT_FILE" 2>/dev/null; then
  echo "✅  ${IDENTIFIER} ${SESSION} — COMPLETE"
  echo "    Sign off: ${LOG_FILE}"
  exit 0
elif grep -q "^  SESSION BLOCKED" "$OUTPUT_FILE" 2>/dev/null; then
  echo "⚠️   ${IDENTIFIER} ${SESSION} — BLOCKED (test case failed)"
  echo "    Diagnose: ${OUTPUT_FILE}"
  exit 1
elif grep -q "^  CHALLENGE FINDINGS" "$OUTPUT_FILE" 2>/dev/null; then
  echo "⚠️   ${IDENTIFIER} ${SESSION} — further FINDINGS on next task"
  echo "    Resume:   ./tools/resume_challenge.sh ${MODE} ${IDENTIFIER} ${SESSION} <next-task>"
  exit 4
else
  echo "❓  ${IDENTIFIER} ${SESSION} — UNKNOWN OUTCOME"
  echo "    Review: ${OUTPUT_FILE}"
  exit 99
fi
