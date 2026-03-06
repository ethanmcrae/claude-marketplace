---
description: "Set a custom continuation prompt for caffeinate (global or per-project)"
argument-hint: "<message> [--global | --project]"
allowed-tools: ["Bash(mkdir *)", "Write"]
hide-from-slash-command-tool: "true"
---

# Caffeinate Prompt

Set the continuation message that Claude receives when the caffeinate timer keeps it working.

## Instructions

Parse the arguments from: $ARGUMENTS

**Flags:**
- `--global` (default): Save to `~/.claude/caffeine-prompt.txt` (applies to all projects)
- `--project`: Save to `.claude/caffeine-prompt.txt` (overrides global for this project only)

**Special variable:** Use `TIME_REMAINING` in the message - it will be replaced with the actual remaining time (e.g., "1h 23m").

**If no message is provided**, show the current prompt configuration:
1. Check if `.claude/caffeine-prompt.txt` exists (project-level)
2. Check if `~/.claude/caffeine-prompt.txt` exists (global)
3. Show the default: "You have TIME_REMAINING remaining on your caffeinate timer. Continue working on your current task. Proceed with the next logical step without stopping or asking for confirmation."

**If a message is provided**, write it to the appropriate file. Ensure the parent directory exists.

Report what was saved and where.
