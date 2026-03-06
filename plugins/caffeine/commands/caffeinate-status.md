---
description: "Check the status of the current caffeinate timer"
allowed-tools: ["Bash(test *)", "Bash(cat /tmp/claude-caffeine-*)", "Bash(date *)"]
hide-from-slash-command-tool: "true"
---

# Caffeinate Status

Check if a caffeinate timer is active for this session:

1. Run: `test -f "/tmp/claude-caffeine-${CLAUDE_CODE_SESSION_ID}" && cat "/tmp/claude-caffeine-${CLAUDE_CODE_SESSION_ID}" || echo "NONE"`
2. **If NONE**: Say "No active caffeinate timer."
3. **If a timestamp is returned**:
   - Get current time: `date +%s`
   - Calculate remaining seconds: expiry - now
   - If remaining <= 0: "Timer has expired." and clean up the file
   - Otherwise: Report "☕ Caffeinated - X remaining (expires at HH:MM)"
   - Use `date -r <timestamp> +"%H:%M"` to format the expiry time
