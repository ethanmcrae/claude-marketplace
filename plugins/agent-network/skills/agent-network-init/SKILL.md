---
name: agent-network-init
description: Initialize the Agent Network system. Use when the user says "set up agent network", "install agent network", "configure agent messaging", or "agent-network-init".
allowed-tools: Bash(python3 *), Bash(sqlite3 *), Bash(*/.venv/bin/pip *), Bash(*/.venv/bin/python3 *)
---

# Agent Network — Install & Setup

You are setting up the Agent Network: a cross-conversation messaging system that lets independent Claude Code instances communicate in real time.

## Communication Style

**This install should feel seamless.** Before starting, give the user a brief overview:

> Setting up Agent Network. This will:
> 1. Create a Python environment and install dependencies
> 2. Register the MCP server and message hooks
> 3. Initialize the message database
>
> This takes about 30 seconds.

Then proceed through the steps below. Print a **one-line status** before each phase (e.g., "Installing dependencies..."). Do NOT dump raw command output to the user — only surface errors if something fails.

---

## Step 1 — Detect skill directory & check prerequisites

Resolve the skill base directory:

```
SKILL_DIR = ~/.claude/skills/agent-network-init
```

Expand `~` to the absolute home path. Confirm it exists and contains `agent_network_server.py` and `hooks/`. If missing, tell the user the skill is not installed correctly and stop.

Run prerequisite checks in a single command:

```bash
python3 --version && sqlite3 --version
```

If either is missing, guide the user to install it and stop.

Check if already installed:
- MCP server registered in `~/.claude.json` under `mcpServers.agent-network`
- Hooks present in `~/.claude/settings.json` for SessionStart, PreToolUse, and Stop

If already installed, ask the user: **Repair/Reinstall** or **Skip setup**.

> **Migration note**: If an old config exists at `~/.claude/.mcp.json`, delete that file — it was the wrong location and Claude Code never reads it.

---

## Step 2 — Create venv & install dependencies

Run as a single chained command:

```bash
python3 -m venv "$SKILL_DIR/.venv" && "$SKILL_DIR/.venv/bin/pip" install -q -r "$SKILL_DIR/requirements.txt" && "$SKILL_DIR/.venv/bin/python3" -c "import mcp; print('OK')"
```

The `-q` flag keeps pip output minimal. If the final `import mcp` prints `OK`, dependencies are good. Only surface output to the user if something fails.

---

## Step 3 — Register MCP server & configure hooks

This step edits two config files. Read each file first, merge the new keys, and write back. **Preserve all existing content** — never overwrite.

### 3a. Register MCP server

Merge into `~/.claude.json` (the file at `$HOME/.claude.json`, **not** inside `~/.claude/`):

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

### 3b. Install hooks & permissions

Merge into `~/.claude/settings.json` under the `hooks` key. **Append to arrays, never overwrite existing hooks.**

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

Replace `<SKILL_DIR>` with the absolute expanded path. Do not duplicate entries if already present.

---

## Step 4 — Initialize database

Run the server's `init_db()` and verify in one command:

```bash
"$SKILL_DIR/.venv/bin/python3" -c "import sys; sys.path.insert(0, '$SKILL_DIR'); from agent_network_server import init_db; init_db(); print('DB initialized')" && sqlite3 ~/.claude/agent_network.db "SELECT name FROM sqlite_master WHERE type='table';"
```

Expect `sessions` and `messages` tables. Only tell the user if it fails.

---

## Step 5 — Done

Print this to the user:

```
Agent Network is ready!

Open two terminals and try it:

  Terminal 1: "Join network my-project as alice"
  Terminal 2: "Join network my-project as bob"

Then in Terminal 1: "Send bob a message: hello!"

Messages are delivered automatically — no polling needed.
```
