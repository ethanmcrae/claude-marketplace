---
description: "Keep Claude working for a specified duration without going idle"
argument-hint: "<duration> (e.g., 30m, 2h, 1h30m, 3:00pm)"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/scripts/setup-caffeinate.sh:*)"]
hide-from-slash-command-tool: "true"
---

# Caffeinate

Execute the setup script to start the caffeinate timer:

```!
"${CLAUDE_PLUGIN_ROOT}/scripts/setup-caffeinate.sh" $ARGUMENTS
```

The caffeinate timer is now active. Continue working on whatever task is at hand. When you would normally stop, the stop hook will keep you going until the timer expires. Work naturally and don't rush - you have the full duration to think deeply and produce quality work.
