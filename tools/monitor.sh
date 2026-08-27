#!/usr/bin/env bash
# monitor.sh — Multi-session status dashboard
# Usage: ./tools/monitor.sh
# Polls all agent output logs every 10 seconds.
# Display only — takes no actions.

SESSIONS_DIR="sessions"

watch -n 10 "
echo 'DG-Forge Agentic Build Monitor'
echo '================================'
echo \"\$(date)\"
echo ''

found=0

# Greenfield sessions
for log in ${SESSIONS_DIR}/S*_agent_output.log \
           ${SESSIONS_DIR}/S*_resume_output.log \
           ${SESSIONS_DIR}/S*_challenge_resume_output.log; do
  [ -f \"\$log\" ] || continue
  found=1
  session=\$(basename \"\$log\" | grep -o 'S[0-9]*')
  label=\"greenfield \${session}\"

  if grep -q '^  SESSION COMPLETE' \"\$log\" 2>/dev/null; then
    echo \"✅  \${label} — COMPLETE — sign off SESSION_LOG\"
  elif grep -q '^  SESSION BLOCKED' \"\$log\" 2>/dev/null; then
    echo \"⚠️   \${label} — BLOCKED — needs attention\"
  elif grep -q '^  SCOPE VIOLATION' \"\$log\" 2>/dev/null; then
    echo \"🚫  \${label} — SCOPE VIOLATION — needs attention\"
  elif grep -q '^  CHALLENGE FINDINGS' \"\$log\" 2>/dev/null; then
    echo \"⚠️   \${label} — CHALLENGE FINDINGS — needs disposition\"
  elif grep -q '^  LAUNCH ERROR' \"\$log\" 2>/dev/null; then
    echo \"🚫  \${label} — LAUNCH ERROR\"
  else
    echo \"🔄  \${label} — running...\"
  fi
done

# Enhancement sessions
for log in ${SESSIONS_DIR}/SPRINT-*/ENH-*/*_agent_output.log \
           ${SESSIONS_DIR}/SPRINT-*/ENH-*/*_resume_output.log \
           ${SESSIONS_DIR}/SPRINT-*/ENH-*/*_challenge_resume_output.log; do
  [ -f \"\$log\" ] || continue
  found=1
  enh=\$(echo \"\$log\" | grep -o 'ENH-[0-9]*')
  session=\$(basename \"\$log\" | grep -o 'S[0-9]*')
  label=\"\${enh} \${session}\"

  if grep -q '^  SESSION COMPLETE' \"\$log\" 2>/dev/null; then
    echo \"✅  \${label} — COMPLETE — sign off SESSION_LOG\"
  elif grep -q '^  SESSION BLOCKED' \"\$log\" 2>/dev/null; then
    echo \"⚠️   \${label} — BLOCKED — needs attention\"
  elif grep -q '^  SCOPE VIOLATION' \"\$log\" 2>/dev/null; then
    echo \"🚫  \${label} — SCOPE VIOLATION — needs attention\"
  elif grep -q '^  CHALLENGE FINDINGS' \"\$log\" 2>/dev/null; then
    echo \"⚠️   \${label} — CHALLENGE FINDINGS — needs disposition\"
  elif grep -q '^  LAUNCH ERROR' \"\$log\" 2>/dev/null; then
    echo \"🚫  \${label} — LAUNCH ERROR\"
  else
    echo \"🔄  \${label} — running...\"
  fi
done

[ \"\$found\" = '0' ] && echo 'No agent output logs found.'
echo ''
echo 'Refresh: 10s  |  Ctrl+C to exit'
"
