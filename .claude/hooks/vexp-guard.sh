#!/bin/bash
# vexp-guard: block Grep/Glob when the vexp daemon is running AND the index is healthy.
# Shipped by the vexp-context-engine standard (crzynet/homelab-configs). Copy to
# .claude/hooks/vexp-guard.sh in the adopting repo and register it via settings.vexp.json.
#
# Fast path: if the socket or healthy marker is absent, allow immediately (no daemon =
#   safe to fall back to direct search).
# PID check: verify the daemon process is actually alive (handles stale files after kill -9).
VEXP_DIR="${CLAUDE_PROJECT_DIR:-.}/.vexp"
SOCK="$VEXP_DIR/daemon.sock"
HEALTHY="$VEXP_DIR/healthy"
PID_FILE="$VEXP_DIR/daemon.pid"
if [ -S "$SOCK" ] && [ -f "$HEALTHY" ] && [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"vexp daemon is running. Use run_pipeline instead of Grep/Glob."}}'
else
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"vexp index not ready, allowing direct search fallback."}}'
fi
exit 0
