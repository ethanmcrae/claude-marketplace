---
name: agent-network-update
description: Update the Agent Network plugin to the latest version. Use when the user says "update agent network", "update plugin", "get latest version", or "agent-network-update".
allowed-tools: Bash(rm -rf *), Bash(git -C *), Bash(claude plugin *)
---

# Agent Network — Update

Update the Agent Network plugin to the latest published version.

## Communication Style

Tell the user what's happening in plain language. One-line status updates between steps. Do not dump raw command output — only surface errors.

---

## Step 1 — Detect current installation

Read `~/.claude/plugins/installed_plugins.json` and look for a key matching `agent-network@*`. Extract:
- The marketplace name (e.g., `ethanmcrae-marketplace`)
- The current version or git SHA
- The install path

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

## Step 3 — Apply update

Due to known Claude Code cache bugs, the most reliable update path is uninstall → clear cache → reinstall:

```bash
claude plugin uninstall agent-network@<marketplace-name>
```

```bash
rm -rf ~/.claude/plugins/cache/<marketplace-name>/agent-network/
```

```bash
claude plugin install agent-network@<marketplace-name>
```

Tell the user:

> Updated Agent Network to v{new_version}. Restart Claude Code to use the new version.

---

## Step 4 — Re-run init if needed

After updating, the hooks and MCP server config may need refreshing if paths changed. Ask the user:

> The plugin has been updated. Would you like to re-run setup to ensure hooks and MCP config are current?

If yes, run `/agent-network-init`. If no, done.
