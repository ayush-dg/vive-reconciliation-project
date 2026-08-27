#!/usr/bin/env bash
# challenge.sh — Independent Challenge Agent invocation
# Usage: ./tools/challenge.sh <session-id> <task-id>
# Example: ./tools/challenge.sh S02 T-03
#
# Invoked by the build agent as step 8 in the per-task execution order.
# Assembles an evidence-only package and invokes a separate Claude instance.
# The challenge agent receives NO build session context — only evidence.

set -euo pipefail

SESSION="${1:?Usage: challenge.sh <session-id> <task-id>}"
TASK="${2:?Usage: challenge.sh <session-id> <task-id>}"

# ── Locate planning artifacts ────────────────────────────────────────────────
CLAUDE_MD="docs/Claude.md"
INVARIANTS="docs/INVARIANTS.md"

# Try greenfield path first, then enhancement path
if [ -f "docs/EXECUTION_PLAN.md" ]; then
  EXEC_PLAN="docs/EXECUTION_PLAN.md"
  VR_FILE="sessions/${SESSION}_VERIFICATION_RECORD.md"
else
  # Enhancement — find the plan from any matching ENH directory
  EXEC_PLAN=$(find enhancements -name "*_EXECUTION_PLAN.md" | head -1)
  VR_FILE=$(find sessions -name "${SESSION}_VERIFICATION_RECORD.md" | head -1)
fi

for f in "$CLAUDE_MD" "$INVARIANTS" "$EXEC_PLAN"; do
  if [ ! -f "$f" ]; then
    echo "CHALLENGE ERROR — required file not found: $f"
    exit 1
  fi
done

# ── Assemble evidence package ────────────────────────────────────────────────
ESCAPED_TASK=$(echo "$TASK" | sed 's/\./\\./g')
TASK_SECTION=$(awk "/^### ${ESCAPED_TASK}[^0-9]/,/^### T[0-9]/" "$EXEC_PLAN" \
  | head -80 || echo "[Task section not found in execution plan]")

CODE_DIFF=$(git diff HEAD 2>/dev/null \
  || echo "[No prior commit — first task in session]")

VR_SECTION=""
# NOTE: VR results may be blank at challenge time — the agent writes results
# at step 4 but challenge runs at step 8. This is expected; the challenge
# agent assesses the code diff and task spec independently of VR results.
if [ -f "$VR_FILE" ]; then
  VR_SECTION=$(awk "/## \[${TASK}/,/### Verification Verdict/" "$VR_FILE" \
    2>/dev/null | head -60 || echo "[Task not yet in verification record]")
fi

# ── Challenge prompt ─────────────────────────────────────────────────────────
CHALLENGE_PROMPT="You are an independent challenge agent.

You have no knowledge of how or why this code was built.
You did not participate in this build session.
You see only evidence: the execution contract, the task specification,
the invariants, the code diff, and the verification record for this task.

Your job: identify what is not tested, not covered, or assumed without
verification — based solely on the evidence below.

Do not explain what the code does.
Do not summarise the verification record.
Do not infer intent from the code.
Surface gaps only. Be specific. Be concise.

Only flag findings that are testable within the current task's scope
using already-modified files. Gaps requiring different sessions, external
state, or human interaction are recorded as known untested scenarios —
they are NOT findings that require engineer disposition.

═══════════════════════════════════════════
EXECUTION CONTRACT (Claude.md):
$(cat "$CLAUDE_MD")

═══════════════════════════════════════════
TASK SPECIFICATION (from EXECUTION_PLAN.md):
${TASK_SECTION}

═══════════════════════════════════════════
INVARIANTS (INVARIANTS.md):
$(cat "$INVARIANTS")

═══════════════════════════════════════════
CODE DIFF (this task only):
${CODE_DIFF}

═══════════════════════════════════════════
VERIFICATION RECORD (this task):
${VR_SECTION}

═══════════════════════════════════════════

Produce output in exactly this structure:

## CC Challenge — ${TASK} — Challenge Agent

**Challenger:** Independent agent — no build session context
**Session:** ${SESSION}

### Untested Scenarios
| # | Scenario | Why it matters | Invariant at risk |
|---|----------|----------------|-------------------|
| 1 | [gap] | [consequence] | [INV-XX or NONE] |

Write NONE if no untested scenarios identified.

### Unverified Assumptions
| # | Assumption in code | Basis | Testable within task scope |
|---|--------------------|-------|---------------------------|
| 1 | [assumption] | [inferred from code] | YES / NO |

Write NONE if no unverified assumptions identified.

### Invariant Coverage Gaps
| Invariant | Enforcement point touched | Tested in verification record |
|-----------|--------------------------|-------------------------------|
| [INV-XX]  | YES / NO                  | YES / NO                      |

Write NONE if no invariant coverage gaps identified.

### Known Untested Scenarios (out of scope — not findings)
| Scenario | Reason out of scope |
|----------|---------------------|
| [scenario] | [requires different session / external state / human] |

Write NONE if none.

### Challenge Verdict

CLEAN — no in-scope findings requiring engineer disposition.
  or
FINDINGS — [N] item(s) require engineer disposition before commit.
  Finding 1: [specific description]
  Finding 2: [specific description]
"

# ── Invoke challenge agent ───────────────────────────────────────────────────
echo "Running challenge agent for ${SESSION} ${TASK}..."
claude --print "$CHALLENGE_PROMPT"
