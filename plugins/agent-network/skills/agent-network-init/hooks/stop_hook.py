#!/usr/bin/env python3
"""Stop hook — prevents Claude from going idle while connected to an agent network.

Two checks at every turn boundary:
1. Blocks if there are pending messages (nudges agent to call check_inbox())
2. Blocks if the background listener isn't running (provides re-spawn command)

No external dependencies — stdlib only.
"""

import json
import os
import subprocess
import sys

DB_PATH = os.environ.get(
    "AGENT_NETWORK_DB", os.path.expanduser("~/.claude/agent_network.db")
)


def _is_listener_running(agent_id: str) -> bool:
    """Check if a background listener.sh process is running for this agent.

    Matches 'listener.sh {agent_id} ' to avoid substring false positives
    (e.g. agent "al" matching agent "alice"'s listener). The agent_id is
    always followed by the db_path argument, so trailing space is safe.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-fl", "listener.sh"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return f"listener.sh {agent_id} " in result.stdout
    except (subprocess.SubprocessError, OSError):
        return True  # Assume running if we can't check


def main():
    # Fast-exit: no DB means agent network has never been used
    if not os.path.exists(DB_PATH):
        return

    import sqlite3

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    session_id = data.get("session_id")
    if not session_id:
        return

    try:
        db = sqlite3.connect(DB_PATH, isolation_level=None)
        db.execute("PRAGMA busy_timeout=5000")
        db.row_factory = sqlite3.Row
    except sqlite3.Error:
        return

    try:
        # Look up agent identity
        row = db.execute(
            "SELECT agent_id, network_id FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return
        agent_id = row["agent_id"]
        network_id = row["network_id"]

        # Priority 1: block if there are unread messages
        pending = db.execute(
            "SELECT COUNT(*) as cnt FROM messages "
            "WHERE recipient_id = ? AND status = 'pending'",
            (agent_id,),
        ).fetchone()["cnt"]

        if pending > 0:
            output = {
                "decision": "block",
                "reason": (
                    f"You have {pending} unread agent network message(s). "
                    "Call check_inbox() to receive them."
                ),
            }
            print(json.dumps(output))
            return

        # Priority 2: block if background listener isn't running
        if not _is_listener_running(agent_id):
            hooks_dir = os.path.dirname(os.path.abspath(__file__))
            listener_path = os.path.join(hooks_dir, "listener.sh")
            listener_cmd = (
                f'bash "{listener_path}" "{agent_id}" '
                f'"{DB_PATH}" "0" "{network_id}"'
            )
            output = {
                "decision": "block",
                "reason": (
                    "Your background listener has stopped. "
                    "Re-spawn it now as a background Bash task "
                    f"(run_in_background=true):\n{listener_cmd}"
                ),
            }
            print(json.dumps(output))
            return

    except sqlite3.Error:
        return
    finally:
        db.close()


if __name__ == "__main__":
    main()
