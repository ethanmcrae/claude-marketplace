#!/bin/bash

# Install caffeine plugin hooks into ~/.claude/settings.json

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SETTINGS_FILE="$HOME/.claude/settings.json"

# Ensure settings file exists
if [[ ! -f "$SETTINGS_FILE" ]]; then
  mkdir -p "$HOME/.claude"
  echo '{}' > "$SETTINGS_FILE"
fi

# Check if already installed
if grep -q "$PLUGIN_ROOT/hooks" "$SETTINGS_FILE" 2>/dev/null; then
  echo "Caffeine hooks already installed in $SETTINGS_FILE"
  echo "To reinstall, first run /caffeine-uninstall or manually remove the entries."
  exit 0
fi

# Add hooks to settings.json using jq
TEMP_FILE=$(mktemp)
jq --arg session_start "$PLUGIN_ROOT/hooks/session-start.sh" \
   --arg stop_hook "$PLUGIN_ROOT/hooks/stop-hook.sh" \
  '
  .hooks //= {} |
  .hooks.SessionStart //= [] |
  .hooks.Stop //= [] |
  .hooks.SessionStart += [{"hooks": [{"type": "command", "command": $session_start, "timeout": 5}]}] |
  .hooks.Stop += [{"hooks": [{"type": "command", "command": $stop_hook, "timeout": 10}]}]
  ' "$SETTINGS_FILE" > "$TEMP_FILE"

mv "$TEMP_FILE" "$SETTINGS_FILE"

echo "Caffeine hooks installed successfully!"
echo ""
echo "Added to $SETTINGS_FILE:"
echo "  - SessionStart hook: $PLUGIN_ROOT/hooks/session-start.sh"
echo "  - Stop hook: $PLUGIN_ROOT/hooks/stop-hook.sh"
echo ""
echo "Restart Claude Code for hooks to take effect."
