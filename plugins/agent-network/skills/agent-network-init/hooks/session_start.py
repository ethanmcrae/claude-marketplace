#!/usr/bin/env python3
"""SessionStart hook — bridges Claude Code session identity to the agent network.

Writes the session_id to the env file and a fallback state file so the MCP
server can resolve which agent "this session" is.

No external dependencies — stdlib only.
"""

import json
import os
import sys
import time

SESSIONS_DIR = os.path.expanduser("~/.claude/agent_network/sessions")
DB_PATH = os.environ.get(
    "AGENT_NETWORK_DB", os.path.expanduser("~/.claude/agent_network.db")
)
MESSAGE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    session_id = data.get("session_id")
    if not session_id:
        return

    source = data.get("source", "startup")
    if source in ("clear", "compact"):
        return

    # Write env file if available
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        try:
            with open(env_file, "a") as f:
                f.write(f"AGENT_NETWORK_SESSION_ID={session_id}\n")
        except OSError:
            pass

    # Write fallback state file
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    state = {
        "session_id": session_id,
        "parent_pid": os.getppid(),
        "created_at": time.time(),
    }
    state_path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    try:
        with open(state_path, "w") as f:
            json.dump(state, f)
    except OSError:
        pass

    # Clean stale state files (PIDs that no longer exist)
    try:
        for fname in os.listdir(SESSIONS_DIR):
            if not fname.endswith(".json") or fname == f"{session_id}.json":
                continue
            fpath = os.path.join(SESSIONS_DIR, fname)
            try:
                with open(fpath) as f:
                    old_state = json.load(f)
                pid = old_state.get("parent_pid")
                if pid:
                    os.kill(pid, 0)  # Check if process exists
            except (ProcessLookupError, PermissionError):
                # PID doesn't exist or we can't signal it — stale
                try:
                    os.remove(fpath)
                except OSError:
                    pass
            except (json.JSONDecodeError, OSError, TypeError):
                pass
    except OSError:
        pass

    # Purge delivered messages older than 7 days
    if os.path.exists(DB_PATH):
        try:
            import sqlite3
            db = sqlite3.connect(DB_PATH, isolation_level=None)
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM messages WHERE status = 'delivered' "
                "AND delivered_at < (unixepoch('now') - ?)",
                (MESSAGE_TTL_SECONDS,),
            )
            db.execute("COMMIT")
            db.close()
        except Exception:
            pass

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "Agent network session initialized.",
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
