---
name: agent-network-init
description: Initialize the Agent Network system. Use when the user says "set up agent network", "install agent network", "configure agent messaging", or "agent-network-init".
---

# Agent Network — Install & Setup

You are setting up the Agent Network: a cross-conversation messaging system that lets independent Claude Code instances communicate in real time via shared SQLite + MCP tools + hooks.

Follow each step below. Use `AskUserQuestion` when choices are needed. Report progress after each step.

---

## Step A — Detect skill directory

Resolve the skill base directory. All source files live here:

```
SKILL_DIR = ~/.claude/skills/agent-network-init
```

Expand `~` to the absolute home path. Confirm the directory exists and contains `agent_network_server.py` and `hooks/`. If missing, tell the user the skill is not installed correctly and stop.

---

## Step B — Check prerequisites

1. Verify `python3` is available (`python3 --version`). If missing, guide the user to install it.
2. Verify `sqlite3` is available (`sqlite3 --version`). If missing, suggest Homebrew on macOS.
3. Check if already installed:
   - MCP server registered in `~/.claude.json` under the `mcpServers` key with key `agent-network`
   - Hooks present in `~/.claude/settings.json` for SessionStart, PreToolUse, and Stop
4. If already installed, ask the user: **Repair/Reinstall** or **Skip setup**.

> **Migration note**: If an old config exists at `~/.claude/.mcp.json`, delete that file — it was the wrong location and Claude Code never reads it. The correct location is `~/.claude.json`.

---

## Step C — Create venv & install dependencies

1. Create a Python venv inside the skill directory if it doesn't already exist:
   ```bash
   python3 -m venv "$SKILL_DIR/.venv"
   ```
2. Install the runtime dependency:
   ```bash
   "$SKILL_DIR/.venv/bin/pip" install -r "$SKILL_DIR/requirements.txt"
   ```
3. Confirm `mcp` is importable:
   ```bash
   "$SKILL_DIR/.venv/bin/python3" -c "import mcp; print('OK')"
   ```

---

## Step D — Register MCP server

Merge into `~/.claude.json` (the file at `$HOME/.claude.json`, **not** inside `~/.claude/`). Read the existing file, add or update the `mcpServers.agent-network` key, and write back. Preserve all other keys in the file.

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

Replace `<SKILL_DIR>` with the absolute expanded path (no `~`).

**Important**: The file `~/.claude.json` contains many other Claude Code settings — always read it first, merge the `mcpServers` key, and write back. Never overwrite the file.

If the old (incorrect) file `~/.claude/.mcp.json` exists, delete it after migrating.

---

## Step E — Install hooks

Merge into `~/.claude/settings.json` under the `hooks` key. **Preserve all existing hooks** — append to arrays, never overwrite.

### SessionStart hook
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
    ]
  }
}
```

### PreToolUse hook
```json
{
  "hooks": {
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
    ]
  }
}
```

### Stop hook
```json
{
  "hooks": {
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
  }
}
```

Replace `<SKILL_DIR>` with the absolute expanded path. Read existing `~/.claude/settings.json` first, merge the hook arrays (don't duplicate if already present), and write back.

---

## Step F — Set permissions

Merge the following into the `permissions.allow` array in `~/.claude/settings.json` (same file as hooks). Do not duplicate if already present.

```json
{
  "permissions": {
    "allow": [
      "mcp__agent-network__*",
      "Bash(bash *agent-network-init/hooks/listener.sh*)"
    ]
  }
}
```

This allows the MCP tools and background listener to run without prompting the user each time.

---

## Step G — Initialize database

Run the server's `init_db()` to create `~/.claude/agent_network.db`:

```bash
"$SKILL_DIR/.venv/bin/python3" -c "
import sys; sys.path.insert(0, '$SKILL_DIR')
from agent_network_server import init_db
init_db()
print('DB initialized')
"
```

Verify with a test query:

```bash
sqlite3 ~/.claude/agent_network.db "SELECT name FROM sqlite_master WHERE type='table';"
```

Expect `sessions` and `messages` tables.

---

## Step H — Show quick start

Print this to the user:

```
Agent Network setup complete!

To use it, tell any Claude Code session:

  "Join network PROJECT-123 as dev-agent and work on the auth feature"

In another terminal:

  "Join network PROJECT-123 as reviewer and review the auth changes"

Agents will automatically receive messages from each other in real time.

Available commands (via MCP tools):
  join_network()      — Join a named network with an agent ID
  send_message()      — Send a direct message to another agent
  broadcast()         — Message all agents in your network
  check_inbox()       — Check for new messages
  wait_for_message()  — Block until a message arrives
  list_agents()       — See who's in your network
  leave_network()     — Leave the network when done

This skill is available globally via /agent-network-init.
```
