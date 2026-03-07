---
description: "Install caffeine plugin hooks into Claude Code settings"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/scripts/install.sh)"]
hide-from-slash-command-tool: "true"
---

# Install Caffeine

Run the install script to register hooks in ~/.claude/settings.json:

```!
"${CLAUDE_PLUGIN_ROOT}/scripts/install.sh"
```

Report the result to the user. If successful, remind them to restart Claude Code for the hooks to take effect.
