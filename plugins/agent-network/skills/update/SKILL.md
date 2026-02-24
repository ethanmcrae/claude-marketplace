---
name: agent-network-update
description: Update the Agent Network plugin to the latest version. Use when the user says "update agent network", "update plugin", "get latest version", or "agent-network-update".
allowed-tools: Bash(rm -rf *), Bash(git -C *), Bash(cp -R *)
---

# Agent Network — Update

Update the Agent Network plugin to the latest published version.

> **Important**: You cannot call `claude` CLI commands from within Claude Code. This skill updates the plugin by directly manipulating the marketplace repo and plugin cache on disk.

## Communication Style

Tell the user what's happening in plain language. One-line status updates between steps. Do not dump raw command output — only surface errors.

---

## Step 1 — Detect current installation

Read `~/.claude/plugins/installed_plugins.json` and look for a key matching `agent-network@*`. Extract:
- The marketplace name (e.g., `ethanmcrae-marketplace`)
- The current version or git SHA
- The install path (the cache directory)

If not found, tell the user the plugin isn't installed and suggest `/agent-network-init` instead.

---

## Step 2 — Check for updates

Pull the latest marketplace:

```bash
git -C ~/.claude/plugins/marketplaces/<marketplace-name> pull --ff-only
```

Read the updated `marketplace.json` from the marketplace repo and compare the advertised version against the installed version.

If they match, tell the user they're already on the latest version and stop.

---

## Step 3 — Update the cache

The plugin cache lives at `~/.claude/plugins/cache/<marketplace-name>/agent-network/<version>/`. Claude Code reads plugin files from this cache.

1. **Find the current cache directory** from the install path detected in Step 1.

2. **Read the new `plugin.json`** from the marketplace repo to get the new version:
   ```
   ~/.claude/plugins/marketplaces/<marketplace-name>/plugins/agent-network/.claude-plugin/plugin.json
   ```

3. **Create the new cache version directory and copy updated files**:
   ```bash
   rm -rf ~/.claude/plugins/cache/<marketplace-name>/agent-network/<new-version>
   cp -R ~/.claude/plugins/marketplaces/<marketplace-name>/plugins/agent-network ~/.claude/plugins/cache/<marketplace-name>/agent-network/<new-version>
   ```

4. **Update `installed_plugins.json`** — read the file, update the agent-network entry:
   - Set `version` to the new version string
   - Set `installPath` to the new cache directory path
   - Set `lastUpdated` to the current ISO-8601 timestamp
   - Preserve all other fields (`scope`, `installedAt`, `gitCommitSha`, etc.)
   - Write back

5. **Clean up old cache** — remove the previous version's cache directory if it differs from the new one:
   ```bash
   rm -rf ~/.claude/plugins/cache/<marketplace-name>/agent-network/<old-version>
   ```

---

## Step 4 — Discover Claude root locations

The plugin cache path changed (new version directory), so hooks and MCP config pointing to the old path need updating. Use `AskUserQuestion`:

> **Where is Agent Network installed?**
>
> 1. **Default only** — Just `~/.claude/`
> 2. **Custom location** — I use `CLAUDE_CONFIG_DIR` for a different path
> 3. **Multiple locations** — I have multiple Claude accounts with different config dirs

Based on the answer, build a list of **Claude root paths** (`ROOTS`):

- **Default**: `ROOTS = ["~/.claude"]` (expand to absolute path)
- **Custom**: Ask for the path. `ROOTS = ["<custom-path>"]`
- **Multiple**: Ask for all paths. `ROOTS = ["~/.claude", "<path2>", ...]`

---

## Step 5 — Update MCP server registration (once)

The new cache path means the MCP server command path changed. Read `~/.claude.json`, update the `mcpServers.agent-network` entry to point to the new `SKILL_DIR` (the `skills/agent-network-init` directory inside the new cache version directory):

```json
{
  "mcpServers": {
    "agent-network": {
      "command": "<NEW_SKILL_DIR>/.venv/bin/python3",
      "args": ["<NEW_SKILL_DIR>/agent_network_server.py"]
    }
  }
}
```

Where `<NEW_SKILL_DIR>` is `<new-cache-path>/skills/agent-network-init`.

**Note**: If the venv doesn't exist at the new path yet, copy it from the old cache or tell the user to re-run `/agent-network-init` to recreate it.

---

## Step 6 — Update hooks & permissions (per root)

**For each root in `ROOTS`**, read `<root>/settings.json` and update any hook commands that reference the old cache path to use the new one. The hooks to update:

- `hooks.SessionStart` — command containing `agent-network-init/hooks/session_start.py`
- `hooks.PreToolUse` — command containing `agent-network-init/hooks/check_inbox.py`
- `hooks.Stop` — command containing `agent-network-init/hooks/stop_hook.py`

Also update any permission entries that reference the old path (the `listener.sh` pattern).

Write back each file. **Preserve all non-agent-network entries.**

---

## Step 7 — Confirm

Tell the user:

```
Updated Agent Network from v{old} to v{new}.

Updated:
  - Plugin cache
  - MCP server registration
  - Hooks in N settings file(s)

Restart Claude Code to use the new version.
```
