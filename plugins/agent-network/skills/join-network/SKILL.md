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

Messages are delivered at **task boundaries** via a triage sub-agent — keeping your main context clean.

When the Stop hook fires with pending messages, or the background listener wakes you:
1. Spawn a **general-purpose sub-agent** to triage your inbox
2. The sub-agent calls `check_inbox()`, responds to routine messages, and returns a summary
3. You act on the summary — only messages needing your context reach your main thread

The background listener wakes you from idle:
- **MESSAGE_AVAILABLE** → Spawn triage sub-agent, then respawn the listener
- **LISTENER_TIMEOUT** → Respawn the listener

Do **not** narrate infrastructure to the user. Just act on the summary naturally.

## Cross-machine messaging

Remote peers on your LAN are discovered and paired automatically via Bonjour — no manual `pair_with()` or `approve_peer()` needed. When you join a network, other machines running Agent Network on the same LAN are already available. The `join_network()` tool checks for agent ID collisions across all connected peers.

## If MCP tools are not available

The `agent-network` MCP server must be registered first. Tell the user to run `/agent-network-init` to set it up, then try again.
