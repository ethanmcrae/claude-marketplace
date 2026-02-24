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

## Step 4 — Re-run init if needed

After updating, the hooks and MCP server config may need refreshing if paths changed (the new cache directory has a different version in its path).

Ask the user:

> Updated Agent Network from v{old} to v{new}. Would you like to re-run setup to ensure hooks and MCP config point to the new version?

If yes, run `/agent-network-init`. If no, tell the user:

> Restart Claude Code to use the new version.
