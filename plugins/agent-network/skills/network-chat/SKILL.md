---
name: network-chat
description: View a network's message history as a chat log. Use when the user says "show chat", "network chat", "view messages", "message history", or wants to see what agents said in a network.
---

# Network Chat Viewer

Parse the user's request for:
- **network_id** (optional): The network name to view (e.g., "project-alpha", "TKT-42")
- **--since** (optional): Time filter like "30m", "2h", "1d" — defaults to showing all messages
- **--agent** (optional): Filter to a specific agent's messages

If no network_id is provided, list all active networks.

## Steps

1. Run the viewer script from this skill's directory:
   `python3 <this skill's directory>/view_chat.py`

   - **List networks** (no network name given): `python3 view_chat.py`
   - **View a network**: `python3 view_chat.py <network_id> [--since <duration>] [--agent <agent_id>]`

2. Present the output to the user as-is — it's already formatted as markdown.

3. If the output says "No messages found", let the user know and suggest checking the network name.

## Notes

- This reads directly from `~/.claude/agent_network.db` — no MCP tools or venv needed.
- Uses only Python stdlib (sqlite3, argparse).
