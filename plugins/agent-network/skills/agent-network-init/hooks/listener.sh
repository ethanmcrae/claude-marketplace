#!/usr/bin/env bash
# Background listener — polls SQLite for incoming agent network messages.
#
# Designed to run inside a Claude Code background Task. When a message arrives,
# exits with a notification string that wakes the parent agent.
#
# Usage: bash listener.sh <agent_id> [db_path] [timeout_seconds] [network_id]
#
# Exit codes:
#   0 — message detected or timeout (normal)
#   2 — error (missing args, bad DB, etc.)

set -euo pipefail

AGENT_ID="${1:-}"
DB_PATH="${2:-$HOME/.claude/agent_network.db}"
TIMEOUT="${3:-0}"  # 0 = loop forever (default)
NETWORK_ID="${4:-}"

if [ -z "$AGENT_ID" ]; then
    echo "LISTENER_ERROR: agent_id is required (arg 1)"
    exit 2
fi

if [ ! -f "$DB_PATH" ]; then
    echo "LISTENER_ERROR: database not found at $DB_PATH"
    exit 2
fi

# Track parent PID for orphan detection.
# Process chain: Claude Code → zsh wrapper (Task shell) → listener.sh
# When Claude exits, the zsh wrapper's PPID changes to 1 (launchd/init).
# We detect this and self-terminate to prevent zombie accumulation.
PARENT_PID=$PPID

# Escape single quotes for safe SQL interpolation
SAFE_ID="${AGENT_ID//\'/\'\'}"
SAFE_NETWORK_ID="${NETWORK_ID//\'/\'\'}"

ELAPSED=0
POLL_INTERVAL=2

while true; do
    # Orphan detection: exit if parent shell has been reparented to init/launchd (PID 1)
    GRANDPARENT_PID=$(ps -o ppid= -p "$PARENT_PID" 2>/dev/null | tr -d ' ') || true
    if [ -z "$GRANDPARENT_PID" ] || [ "$GRANDPARENT_PID" = "1" ]; then
        exit 0
    fi

    COUNT=$(sqlite3 -cmd ".timeout 3000" "$DB_PATH" "SELECT COUNT(*) FROM messages WHERE recipient_id = '${SAFE_ID}' AND status = 'pending';" 2>/dev/null) || {
        echo "LISTENER_ERROR: failed to query database"
        exit 2
    }

    if [ "$COUNT" -gt 0 ]; then
        echo "MESSAGE_AVAILABLE: $COUNT pending message(s) for $AGENT_ID"
        exit 0
    fi

    # Heartbeat: update last_seen every ~14s (must be < AGENT_EXPIRY_SECONDS=30s in server)
    if [ -n "$NETWORK_ID" ] && [ "$ELAPSED" -gt 0 ] && [ $((ELAPSED % 14)) -eq 0 ]; then
        sqlite3 -cmd ".timeout 3000" "$DB_PATH" \
            "UPDATE sessions SET last_seen = unixepoch('now') WHERE agent_id = '${SAFE_ID}' AND network_id = '${SAFE_NETWORK_ID}';" \
            2>/dev/null || true
    fi

    # If a finite timeout was requested, check it
    if [ "$TIMEOUT" -gt 0 ] && [ "$ELAPSED" -ge "$TIMEOUT" ]; then
        echo "LISTENER_TIMEOUT: No messages after ${TIMEOUT}s"
        exit 0
    fi

    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done
