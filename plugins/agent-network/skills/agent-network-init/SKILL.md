---
name: agent-network-init
description: Initialize the Agent Network system. Use when the user says "set up agent network", "install agent network", "configure agent messaging", or "agent-network-init".
allowed-tools: Bash(python3 *), Bash(sqlite3 *), Bash(*/.venv/bin/pip *), Bash(*/.venv/bin/python3 *)
---

# Agent Network — Install & Setup

You are setting up the Agent Network: a cross-conversation messaging system that lets independent Claude Code instances communicate in real time.

## Communication Style

**This install should feel seamless.** Print a **one-line status** before each phase (e.g., "Installing dependencies..."). Do NOT dump raw command output — only surface errors if something fails.

---

## Step 1 — Detect skill directory & check prerequisites

Resolve the skill base directory. Check two locations in order:

1. If the env var `CLAUDE_PLUGIN_ROOT` is set, use `$CLAUDE_PLUGIN_ROOT/skills/agent-network-init`
2. Otherwise fall back to `~/.claude/skills/agent-network-init`

```
SKILL_DIR = <resolved path>
```

Expand `~` to the absolute home path. Confirm it exists and contains `agent_network_server.py` and `hooks/`. If missing, tell the user the skill is not installed correctly and stop.

Run prerequisite checks in a single command:

```bash
python3 --version && sqlite3 --version
```

If either is missing, guide the user to install it and stop.

> **Migration note**: If an old config exists at `~/.claude/.mcp.json`, delete that file — it was the wrong location and Claude Code never reads it.

---

## Step 2 — Choose install mode

Use `AskUserQuestion` to ask:

> **How is your Claude Code configured?**
>
> 1. **Default** — Single Claude install at `~/.claude/` (most common)
> 2. **Custom location** — You use `CLAUDE_CONFIG_DIR` to put Claude's config elsewhere
> 3. **Multiple locations** — You run multiple Claude accounts with different config dirs

Based on the answer, build a list of **Claude root paths** to configure:

- **Default**: `ROOTS = ["~/.claude"]` (expand to absolute path)
- **Custom**: Ask for the path. `ROOTS = ["<custom-path>"]`
- **Multiple**: Ask for all paths (comma-separated or one at a time). `ROOTS = ["~/.claude", "<path2>", ...]`

For all modes, also set:
```
MCP_CONFIG = ~/.claude.json
```

The MCP server config always goes in `$HOME/.claude.json` — this file is shared across all roots.

Check if already installed in any root:
- MCP server registered in `$MCP_CONFIG` under `mcpServers.agent-network`
- Hooks present in any `<root>/settings.json`

If already installed, ask: **Repair/Reinstall** or **Skip setup**.

---

## Step 3 — Create venv & install dependencies

This is a one-time setup regardless of how many roots exist.

```bash
python3 -m venv "$SKILL_DIR/.venv" && "$SKILL_DIR/.venv/bin/pip" install -q -r "$SKILL_DIR/requirements.txt" && "$SKILL_DIR/.venv/bin/python3" -c "import mcp; print('OK')"
```

The `-q` flag keeps pip output minimal. Only surface output if something fails.

---

## Step 4 — Register MCP server (once)

Merge into `~/.claude.json` (the file at `$HOME/.claude.json`, **not** inside any root). Read the existing file, merge the key, and write back. **Preserve all existing content.**

```json
{
  "mcpServers": {
    "agent-network": {
      "command": "<SKILL_DIR>/.venv/bin/python3",
      "args": ["<SKILL_DIR>/agent_network_server.py"]
    }
  }
}
```

Replace `<SKILL_DIR>` with the absolute expanded path.

---

## Step 5 — Install hooks & permissions (per root)

**Repeat this step for each path in `ROOTS`.**

For each root, merge into `<root>/settings.json`. Read existing file first. **Append to arrays, never overwrite existing hooks.** Do not duplicate entries if already present.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 <SKILL_DIR>/hooks/session_start.py"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 <SKILL_DIR>/hooks/check_inbox.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 <SKILL_DIR>/hooks/stop_hook.py"
          }
        ]
      }
    ]
  },
  "permissions": {
    "allow": [
      "mcp__agent-network__*",
      "Bash(bash *agent-network-init/hooks/listener.sh*)"
    ]
  }
}
```

Replace `<SKILL_DIR>` with the absolute expanded path. Ensure the `<root>/` directory exists before writing (create with `mkdir -p` if needed).

After configuring all roots, tell the user which locations were set up:

> Hooks installed for N location(s): ~/.claude, /path/to/other, ...

---

## Step 6 — Initialize database (once)

The message database is shared across all roots.

```bash
"$SKILL_DIR/.venv/bin/python3" -c "import sys; sys.path.insert(0, '$SKILL_DIR'); from agent_network_server import init_db; init_db(); print('DB initialized')" && sqlite3 ~/.claude/agent_network.db "SELECT name FROM sqlite_master WHERE type='table';"
```

Expect `sessions` and `messages` tables. Only tell the user if it fails.

---

## Step 7 — Done

Print this to the user:

```
Agent Network is ready!

Open two terminals and try it:

  Terminal 1: "Join network my-project as alice"
  Terminal 2: "Join network my-project as bob"

Then in Terminal 1: "Send bob a message: hello!"

Messages are delivered automatically — no polling needed.
```
