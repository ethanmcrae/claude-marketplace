#!/bin/bash

# Caffeinate Setup Script
# Parses duration argument and creates state file for the stop hook

set -euo pipefail

SESSION_ID="${CLAUDE_CODE_SESSION_ID:-}"

if [[ -z "$SESSION_ID" ]]; then
  echo "Error: No session ID available. Are you running inside Claude Code?" >&2
  exit 1
fi

STATE_FILE="/tmp/claude-caffeine-${SESSION_ID}"

# Parse arguments
if [[ $# -eq 0 ]]; then
  cat <<'HELP'
Usage: /caffeinate <duration>

DURATION FORMATS:
  30m              30 minutes
  1h               1 hour
  2h30m            2 hours 30 minutes
  90m              90 minutes
  3:00pm           until 3:00 PM
  15:00            until 15:00 (24h format)
  17:30            until 5:30 PM

EXAMPLES:
  /caffeinate 2h
  /caffeinate 45m
  /caffeinate 1h30m
  /caffeinate 5:00pm

CANCEL:
  /decaffeinate

STATUS:
  /caffeinate-status
HELP
  exit 0
fi

DURATION_ARG="$*"

# Handle "stop" / "cancel" as alias
if [[ "$DURATION_ARG" == "stop" ]] || [[ "$DURATION_ARG" == "cancel" ]]; then
  if [[ -f "$STATE_FILE" ]]; then
    rm -f "$STATE_FILE"
    echo "Caffeinate cancelled."
  else
    echo "No active caffeinate timer."
  fi
  exit 0
fi

NOW=$(date +%s)
EXPIRY=""

# Try parsing as absolute time (HH:MM or H:MMam/pm)
if echo "$DURATION_ARG" | grep -qiE '^[0-9]{1,2}:[0-9]{2}\s*(am|pm)?$'; then
  # Absolute time
  TARGET_TIME=$(echo "$DURATION_ARG" | tr -d ' ')

  # Use date to parse - macOS date syntax
  if date -j -f "%I:%M%p" "$TARGET_TIME" "+%s" &>/dev/null; then
    # 12h format (e.g., 3:00pm)
    TARGET_TS=$(date -j -f "%I:%M%p" "$TARGET_TIME" "+%s" 2>/dev/null)
  elif date -j -f "%H:%M" "$TARGET_TIME" "+%s" &>/dev/null; then
    # 24h format (e.g., 15:00)
    TARGET_TS=$(date -j -f "%H:%M" "$TARGET_TIME" "+%s" 2>/dev/null)
  else
    echo "Error: Could not parse time '$DURATION_ARG'" >&2
    echo "Examples: 3:00pm, 15:00, 5:30pm" >&2
    exit 1
  fi

  # If target is in the past, assume tomorrow
  if [[ $TARGET_TS -le $NOW ]]; then
    TARGET_TS=$((TARGET_TS + 86400))
  fi

  EXPIRY=$TARGET_TS
else
  # Parse as relative duration (e.g., 2h30m, 45m, 1h)
  TOTAL_SECONDS=0

  # Extract hours
  if echo "$DURATION_ARG" | grep -qiE '[0-9]+h'; then
    HOURS=$(echo "$DURATION_ARG" | grep -oiE '[0-9]+h' | grep -oE '[0-9]+')
    TOTAL_SECONDS=$((TOTAL_SECONDS + HOURS * 3600))
  fi

  # Extract minutes
  if echo "$DURATION_ARG" | grep -qiE '[0-9]+m'; then
    MINS=$(echo "$DURATION_ARG" | grep -oiE '[0-9]+m' | grep -oE '[0-9]+')
    TOTAL_SECONDS=$((TOTAL_SECONDS + MINS * 60))
  fi

  # If just a bare number, treat as minutes
  if [[ $TOTAL_SECONDS -eq 0 ]] && [[ "$DURATION_ARG" =~ ^[0-9]+$ ]]; then
    TOTAL_SECONDS=$((DURATION_ARG * 60))
  fi

  if [[ $TOTAL_SECONDS -eq 0 ]]; then
    echo "Error: Could not parse duration '$DURATION_ARG'" >&2
    echo "Examples: 30m, 1h, 2h30m, 3:00pm" >&2
    exit 1
  fi

  EXPIRY=$((NOW + TOTAL_SECONDS))
fi

# Write state file (line 1: expiry, line 2: creation timestamp)
# Grace period: stops within 10s of creation are allowed so user can provide their task
echo "$EXPIRY" > "$STATE_FILE"
echo "$NOW" >> "$STATE_FILE"

# Calculate display values
REMAINING=$((EXPIRY - NOW))
if [[ $REMAINING -ge 3600 ]]; then
  HOURS=$((REMAINING / 3600))
  MINS=$(( (REMAINING % 3600) / 60 ))
  TIME_STR="${HOURS}h ${MINS}m"
else
  MINS=$((REMAINING / 60))
  TIME_STR="${MINS}m"
fi

EXPIRY_TIME=$(date -r "$EXPIRY" +"%H:%M" 2>/dev/null || date -d "@$EXPIRY" +"%H:%M" 2>/dev/null || echo "unknown")

cat <<EOF
☕ Caffeinated!

Duration: ${TIME_STR}
Expires at: ${EXPIRY_TIME}
Session: ${SESSION_ID:0:8}...

Claude will continue working until the timer expires.
To cancel early: /decaffeinate
EOF
