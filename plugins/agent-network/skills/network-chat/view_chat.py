#!/usr/bin/env python3
"""View agent network message history as a formatted chat log."""

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".claude" / "agent_network.db"


def parse_duration(s: str) -> float:
    """Parse a duration string like '30m', '2h', '1d' into seconds."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if not s:
        return 0
    unit = s[-1].lower()
    if unit in units:
        try:
            return float(s[:-1]) * units[unit]
        except ValueError:
            pass
    raise ValueError(f"Invalid duration: {s!r} (use e.g. 30m, 2h, 1d)")


def format_timestamp(unix_ts: float) -> str:
    """Format a unix timestamp as a readable local time string."""
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone()
    return dt.strftime("%b %d, %I:%M %p").replace(" 0", " ")


def list_networks() -> list[dict]:
    """List all networks with agent counts and last activity."""
    if not DB_PATH.exists():
        print("No agent network database found at", DB_PATH, file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT
                network_id,
                GROUP_CONCAT(agent_id, ', ') AS agents,
                COUNT(*) AS agent_count,
                MAX(last_seen) AS last_active
            FROM sessions
            GROUP BY network_id
            ORDER BY last_active DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def render_network_list(networks: list[dict]) -> str:
    """Render the network list as markdown."""
    if not networks:
        return "No active networks found."

    lines = ["### Active Networks", ""]
    for net in networks:
        name = net["network_id"]
        count = net["agent_count"]
        agents = net["agents"]
        last = format_timestamp(net["last_active"])
        agent_word = "agent" if count == 1 else "agents"
        lines.append(f"- **{name}** — {count} {agent_word} ({agents}) — last active {last}")

    return "\n".join(lines)


def fetch_messages(
    network_id: str,
    since_seconds: float = 0,
    agent_filter: str | None = None,
) -> list[dict]:
    """Fetch messages from the DB for a given network."""
    if not DB_PATH.exists():
        print("No agent network database found at", DB_PATH, file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT sender_id, recipient_id, content, is_broadcast, created_at
            FROM messages
            WHERE network_id = ?
        """
        params: list = [network_id]

        if since_seconds > 0:
            cutoff = time.time() - since_seconds
            query += " AND created_at >= ?"
            params.append(cutoff)

        if agent_filter:
            query += " AND (sender_id = ? OR recipient_id = ?)"
            params.extend([agent_filter, agent_filter])

        query += " ORDER BY created_at ASC"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def render_chat(messages: list[dict], network_id: str) -> str:
    """Render messages as a markdown chat log."""
    if not messages:
        return f"No messages found in network **{network_id}**."

    lines = [f"### Chat: {network_id}", ""]

    for msg in messages:
        ts = format_timestamp(msg["created_at"])
        sender = msg["sender_id"]
        recipient = msg["recipient_id"]
        content = msg["content"]
        is_broadcast = msg["is_broadcast"]

        if is_broadcast:
            header = f"**{sender}** (broadcast) — {ts}"
        else:
            header = f"**{sender}** -> {recipient} — {ts}"

        lines.append(header)
        # Indent message content for visual separation
        for line in content.strip().splitlines():
            lines.append(f"> {line}")
        lines.append("")

    # Summary
    agents = sorted(set(m["sender_id"] for m in messages))
    lines.append("---")
    lines.append(f"_{len(messages)} messages from {len(agents)} agents: {', '.join(agents)}_")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="View agent network chat history")
    parser.add_argument("network", nargs="?", default=None, help="Network ID to view (omit to list all networks)")
    parser.add_argument("--since", help="Time filter (e.g. 30m, 2h, 1d)", default="")
    parser.add_argument("--agent", help="Filter to a specific agent", default=None)
    parser.add_argument("--list", action="store_true", help="List all active networks")
    args = parser.parse_args()

    if args.list or args.network is None:
        networks = list_networks()
        print(render_network_list(networks))
        return

    since_seconds = 0.0
    if args.since:
        try:
            since_seconds = parse_duration(args.since)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    messages = fetch_messages(args.network, since_seconds, args.agent)
    print(render_chat(messages, args.network))


if __name__ == "__main__":
    main()
