#!/usr/bin/env python3
"""Stop hook — prevents Claude from going idle while connected to an agent network.

Blocks the stop if there are pending messages, or nudges the agent to call
wait_for_message() / leave_network(). Allows stop on second attempt
(stop_hook_active=true) to prevent infinite loops.

No external dependencies — stdlib only.
"""

import json
import os
import sys

DB_PATH = os.environ.get(
    "AGENT_NETWORK_DB", os.path.expanduser("~/.claude/agent_network.db")
)


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

        # Only block if there are actual unread messages
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

        # No pending messages → allow stop (background listener handles idle)

    except sqlite3.Error:
        return
    finally:
        db.close()


if __name__ == "__main__":
    main()
