#!/bin/bash

# Caffeine Stop Hook
# Prevents session exit when a caffeinate timer is active
# Injects a continuation prompt with remaining time

set -euo pipefail

# Read hook input from stdin
HOOK_INPUT=$(cat)

# Extract session ID and stop_hook_active from hook input
HOOK_SESSION=$(echo "$HOOK_INPUT" | jq -r '.session_id // ""')
STOP_HOOK_ACTIVE=$(echo "$HOOK_INPUT" | jq -r '.stop_hook_active // false')

if [[ -z "$HOOK_SESSION" ]]; then
  exit 0
fi

# Check if caffeinate is active for this session
STATE_FILE="/tmp/claude-caffeine-${HOOK_SESSION}"

if [[ ! -f "$STATE_FILE" ]]; then
  exit 0
fi

# Read state (line 1: expiry, line 2: creation timestamp)
EXPIRY=$(sed -n '1p' "$STATE_FILE")
CREATED=$(sed -n '2p' "$STATE_FILE")
CREATED="${CREATED:-0}"
NOW=$(date +%s)

# Validate expiry is numeric
if [[ ! "$EXPIRY" =~ ^[0-9]+$ ]]; then
  rm -f "$STATE_FILE"
  exit 0
fi

# Check if time has expired
REMAINING=$((EXPIRY - NOW))

if [[ $REMAINING -le 0 ]]; then
  rm -f "$STATE_FILE"
  exit 0
fi

# Grace period: within 10s of creation, allow stops so user can provide their task
if [[ "$CREATED" =~ ^[0-9]+$ ]]; then
  ELAPSED_SINCE_CREATION=$((NOW - CREATED))
  if [[ $ELAPSED_SINCE_CREATION -lt 10 ]]; then
    exit 0
  fi
fi

# If in a continuation loop (stop_hook_active), sleep to throttle and give breathing room
if [[ "$STOP_HOOK_ACTIVE" == "true" ]]; then
  sleep 5

  # Recalculate after sleep
  NOW=$(date +%s)
  REMAINING=$((EXPIRY - NOW))
  if [[ $REMAINING -le 0 ]]; then
    rm -f "$STATE_FILE"
    exit 0
  fi
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

# Block the stop and inject continuation
jq -n \
  --arg reason "$PROMPT" \
  '{
    "decision": "block",
    "reason": $reason
  }'

exit 0
