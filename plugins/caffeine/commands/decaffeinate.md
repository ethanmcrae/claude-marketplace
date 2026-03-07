---
description: "Cancel an active caffeinate timer"
allowed-tools: ["Bash(test *)", "Bash(rm /tmp/claude-caffeine-*)"]
hide-from-slash-command-tool: "true"
---

# Decaffeinate

Cancel the caffeinate timer by removing the state file:

1. Check if a timer is active: `test -f "/tmp/claude-caffeine-${CLAUDE_CODE_SESSION_ID}" && echo "ACTIVE" || echo "NONE"`
2. **If NONE**: Say "No active caffeinate timer."
3. **If ACTIVE**: Remove the file: `rm -f "/tmp/claude-caffeine-${CLAUDE_CODE_SESSION_ID}"` and say "Caffeinate timer cancelled."
