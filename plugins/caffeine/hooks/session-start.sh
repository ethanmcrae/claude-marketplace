#!/bin/bash

# Caffeine SessionStart Hook
# Captures session_id from stdin JSON and persists it via CLAUDE_ENV_FILE
# so that setup-caffeinate.sh can access it as CLAUDE_CODE_SESSION_ID

SESSION_ID=$(jq -r '.session_id' < /dev/stdin)
if [ -n "$CLAUDE_ENV_FILE" ] && [ -n "$SESSION_ID" ]; then
  echo "export CLAUDE_CODE_SESSION_ID='$SESSION_ID'" >> "$CLAUDE_ENV_FILE"
fi
exit 0
