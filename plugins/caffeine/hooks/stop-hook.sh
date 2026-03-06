#!/bin/bash

# Caffeine Stop Hook
# Prevents session exit when a caffeinate timer is active
# Injects a continuation prompt with remaining time

set -euo pipefail

# Read hook input from stdin
HOOK_INPUT=$(cat)

# Extract session ID from hook input
HOOK_SESSION=$(echo "$HOOK_INPUT" | jq -r '.session_id // ""')

if [[ -z "$HOOK_SESSION" ]]; then
  exit 0
fi

# Check if caffeinate is active for this session
STATE_FILE="/tmp/claude-caffeine-${HOOK_SESSION}"

if [[ ! -f "$STATE_FILE" ]]; then
  exit 0
fi

# Read state
EXPIRY=$(head -1 "$STATE_FILE")
NOW=$(date +%s)

# Validate expiry is numeric
if [[ ! "$EXPIRY" =~ ^[0-9]+$ ]]; then
  rm -f "$STATE_FILE"
  exit 0
fi

# Check if time has expired
REMAINING=$((EXPIRY - NOW))

if [[ $REMAINING -le 0 ]]; then
  # Timer expired - clean up and allow stop
  rm -f "$STATE_FILE"
  exit 0
fi

# Format remaining time for display
if [[ $REMAINING -ge 3600 ]]; then
  HOURS=$((REMAINING / 3600))
  MINS=$(( (REMAINING % 3600) / 60 ))
  TIME_STR="${HOURS}h ${MINS}m"
elif [[ $REMAINING -ge 60 ]]; then
  MINS=$((REMAINING / 60))
  TIME_STR="${MINS}m"
else
  TIME_STR="${REMAINING}s"
fi

# Load continuation prompt (per-project overrides global, fallback to default)
PROMPT=""
if [[ -f ".claude/caffeine-prompt.txt" ]]; then
  PROMPT=$(cat ".claude/caffeine-prompt.txt")
elif [[ -f "$HOME/.claude/caffeine-prompt.txt" ]]; then
  PROMPT=$(cat "$HOME/.claude/caffeine-prompt.txt")
fi

# Default continuation prompt
if [[ -z "$PROMPT" ]]; then
  PROMPT="You have TIME_REMAINING remaining on your caffeinate timer. Continue working on your current task. Proceed with the next logical step without stopping or asking for confirmation."
fi

# Substitute time placeholder
PROMPT="${PROMPT//TIME_REMAINING/$TIME_STR}"

# Format expiry as clock time for system message
EXPIRY_TIME=$(date -r "$EXPIRY" +"%H:%M" 2>/dev/null || date -d "@$EXPIRY" +"%H:%M" 2>/dev/null || echo "unknown")

# Block the stop and inject continuation
jq -n \
  --arg prompt "$PROMPT" \
  --arg msg "☕ Caffeinated until ${EXPIRY_TIME} (${TIME_STR} remaining)" \
  '{
    "decision": "block",
    "reason": $prompt,
    "systemMessage": $msg
  }'

exit 0
