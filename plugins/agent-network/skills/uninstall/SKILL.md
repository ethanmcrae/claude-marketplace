---
name: agent-network-uninstall
description: Cleanly uninstall the Agent Network system. Use when the user says "uninstall agent network", "remove agent network", "clean up agent network", or "agent-network-uninstall".
allowed-tools: Bash(rm -rf *), Bash(rm *)
---

# Agent Network — Uninstall

Cleanly remove all Agent Network components: hooks, MCP server registration, permissions, database, and venv.

## Communication Style

Tell the user what you're removing in plain language. One-line status per phase. Do NOT dump raw output. Be careful — read before you edit, and only remove agent-network entries, never other config.

---

## Step 1 — Discover what's installed

Build a picture of what exists before removing anything.

### Find all Claude root locations

Check for agent-network hooks in these locations:
1. `~/.claude/settings.json` (default root)
2. Any other `settings.json` files that contain `agent-network` hook commands — ask the user if they installed to custom `CLAUDE_CONFIG_DIR` locations

Use `AskUserQuestion`:

> **Where did you install Agent Network?**
>
> 1. **Default only** — Just `~/.claude/`
> 2. **Custom location(s)** — I used custom `CLAUDE_CONFIG_DIR` paths
> 3. **Not sure** — Search for me

For **Custom**: ask for the paths.
For **Not sure**: check `~/.claude/settings.json` and report what you find. That covers most cases.

Collect all roots into `ROOTS` list.

### Inventory

For each root, note what's present:
- [ ] Hooks in `<root>/settings.json` (SessionStart, PreToolUse, Stop)
- [ ] Permissions in `<root>/settings.json` (`mcp__agent-network__*`, listener)

Also check shared resources:
- [ ] MCP server in `~/.claude.json`
- [ ] Database at `~/.claude/agent_network.db` (+ `.db-wal`, `.db-shm`)
- [ ] Session state files at `~/.claude/agent_network/sessions/`
- [ ] Audit log at `~/.claude/agent_network.log`
- [ ] Venv at `<SKILL_DIR>/.venv/`

Present the inventory to the user:

> Found Agent Network installed in N location(s):
> - ~/.claude/settings.json — hooks + permissions
> - ~/.claude.json — MCP server
> - ~/.claude/agent_network.db — message database (N messages)
> - ~/.claude/agent_network/ — session state files
> - <SKILL_DIR>/.venv/ — Python virtual environment
>
> **Remove everything?** Or keep the database (message history)?

Use `AskUserQuestion` with options:
1. **Remove everything** — Full clean uninstall
2. **Keep database** — Remove config but preserve message history
3. **Cancel** — Abort

---

## Step 2 — Remove hooks & permissions (per root)

**For each root in `ROOTS`:**

Read `<root>/settings.json`. Remove **only** Agent Network entries:

**Hooks to remove** — Remove any hook entry where the `command` contains `agent-network-init/hooks/` or `agent_network`. Check all three hook types:
- `hooks.SessionStart` array — remove matching entries
- `hooks.PreToolUse` array — remove matching entries
- `hooks.Stop` array — remove matching entries

If a hook array becomes empty after removal, remove the entire key. If the `hooks` object becomes empty, remove it.

**Permissions to remove** — From `permissions.allow` array, remove:
- `"mcp__agent-network__*"`
- Any entry matching `*agent-network-init/hooks/listener.sh*`

If the `allow` array becomes empty, remove it. If `permissions` becomes empty, remove it.

Write the cleaned file back. **Never remove non-agent-network entries.**

---

## Step 3 — Remove MCP server registration

Read `~/.claude.json`. Remove the `mcpServers.agent-network` key. If `mcpServers` becomes empty, remove it. Write back. **Preserve all other keys.**

---

## Step 4 — Remove shared resources

Based on the user's choice in Step 1:

**If "Remove everything":**

```bash
rm -rf ~/.claude/agent_network.db ~/.claude/agent_network.db-wal ~/.claude/agent_network.db-shm
rm -rf ~/.claude/agent_network/
rm -rf ~/.claude/agent_network.log
```

**If "Keep database":** skip the DB files, still remove session state and log:

```bash
rm -rf ~/.claude/agent_network/
rm -rf ~/.claude/agent_network.log
```

---

## Step 5 — Remove venv

Find the skill directory (same logic as install — check `CLAUDE_PLUGIN_ROOT` first, then `~/.claude/skills/agent-network-init`).

```bash
rm -rf "$SKILL_DIR/.venv"
```

Do NOT remove the skill files themselves — the plugin manager owns those. Only remove the venv that the install created.

---

## Step 6 — Confirm

Tell the user what was removed:

```
Agent Network uninstalled.

Removed:
  - Hooks from N settings file(s)
  - MCP server registration
  - Python virtual environment
  - Database and session files (or "Database preserved" if kept)

You may need to restart Claude Code for changes to take effect.

To reinstall later: /agent-network-init
```
