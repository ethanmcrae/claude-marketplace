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

The caffeinate timer is now active. Report the result to the user and wait for their next instruction. The stop hook will automatically keep you working on subsequent tasks until the timer expires.
