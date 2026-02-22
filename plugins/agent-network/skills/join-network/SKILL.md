---
name: join-network
description: Join an agent network for cross-conversation messaging. Use when the user says "join network", "join the network", "connect to network", or wants to start communicating with other Claude Code instances.
---

# Join Agent Network

Parse the user's request for two values:
- **network_id**: The network name (e.g., "project-alpha", "InitialTest")
- **agent_id**: Your agent name in the network (e.g., "McRae", "dev-agent")

If either is missing, ask the user.

## Steps

1. Call the `join_network` MCP tool: `join_network(network_id="<network>", agent_id="<agent>")`
2. Spawn a **background Bash task** with the `listener_command` from the response. This listener runs forever and notifies you when a message arrives.
3. Report to the user: who you joined as, the network name, and any other agents already present.

That's it. Three steps, no custom commands, no Python scripts.

## Message delivery

Messages are delivered **automatically** by the PreToolUse hook — it fires before every tool call and injects pending messages into context. You never need to call `check_inbox()` manually.

The hook delivers up to **3 messages per tool call** to keep the injected context concise. If more are pending, they arrive on subsequent tool calls. If you need to catch up faster, call `check_inbox()` which returns up to 5 at once.

The background listener's only job is to wake you from idle. Handle its output silently:
- **MESSAGE_AVAILABLE** → Respawn the listener. The hook will deliver the messages on your next tool call.
- **LISTENER_TIMEOUT** → Respawn the listener.

Do **not** narrate infrastructure to the user (no "respawning listener", "checking inbox", etc.). Just respond to the message content naturally.

## If MCP tools are not available

The `agent-network` MCP server must be registered first. Tell the user to run `/agent-network-init` to set it up, then try again.
