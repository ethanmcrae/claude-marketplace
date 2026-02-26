#!/usr/bin/env python3
"""Agent Network MCP Server — cross-conversation messaging for Claude Code instances.

Single-file MCP server using FastMCP + SQLite (WAL mode). Multiple Claude Code
instances each spawn their own server process; all share the same database.
"""

import asyncio
import json
import logging
import os
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP

# --- Constants ---

DB_PATH = os.environ.get(
    "AGENT_NETWORK_DB", os.path.expanduser("~/.claude/agent_network.db")
)
LOG_PATH = os.path.expanduser("~/.claude/agent_network.log")
SESSIONS_DIR = os.path.expanduser("~/.claude/agent_network/sessions")
AGENT_EXPIRY_SECONDS = 30

# Module-level cache for resolved session ID
_cached_session_id: str | None = None

# Configure logging to stderr (never stdout — that's JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [agent-network] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("agent-network")

mcp = FastMCP("agent-network")


# --- Database ---


def init_db():
    """Create database and tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            network_id TEXT NOT NULL,
            role TEXT DEFAULT '',
            joined_at REAL NOT NULL DEFAULT (unixepoch('now')),
            last_seen REAL NOT NULL DEFAULT (unixepoch('now')),
            UNIQUE(agent_id, network_id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            network_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            content TEXT NOT NULL CHECK(length(content) <= 8000),
            is_broadcast INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at REAL NOT NULL DEFAULT (unixepoch('now')),
            delivered_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_inbox
            ON messages(recipient_id, status) WHERE status = 'pending';
        CREATE INDEX IF NOT EXISTS idx_sessions_network
            ON sessions(network_id);
        CREATE TABLE IF NOT EXISTS peers (
            name TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            shared_secret TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected')),
            direction TEXT NOT NULL DEFAULT 'outbound'
                CHECK(direction IN ('outbound','inbound','mutual')),
            created_at REAL NOT NULL DEFAULT (unixepoch('now')),
            last_seen REAL
        );
    """)
    db.close()


def _get_db() -> sqlite3.Connection:
    """Get a fresh short-lived database connection."""
    db = sqlite3.connect(DB_PATH, isolation_level=None)
    db.execute("PRAGMA busy_timeout=30000")
    db.row_factory = sqlite3.Row
    return db


# --- Session Identity ---


def _resolve_session_id() -> str:
    """Resolve the current session ID via env var or PID ancestry."""
    global _cached_session_id
    if _cached_session_id is not None:
        return _cached_session_id

    # Primary: environment variable
    session_id = os.environ.get("AGENT_NETWORK_SESSION_ID")
    if session_id:
        _cached_session_id = session_id
        return session_id

    # Fallback: scan session state files, match by PID ancestry
    if os.path.isdir(SESSIONS_DIR):
        my_pids = _get_pid_ancestry()
        for fname in os.listdir(SESSIONS_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(SESSIONS_DIR, fname)
            try:
                with open(fpath) as f:
                    state = json.load(f)
                parent_pid = state.get("parent_pid")
                if parent_pid and parent_pid in my_pids:
                    session_id = state["session_id"]
                    _cached_session_id = session_id
                    return session_id
            except (json.JSONDecodeError, OSError, KeyError):
                continue

    raise RuntimeError(
        "Cannot resolve session ID. Set AGENT_NETWORK_SESSION_ID or ensure "
        "the SessionStart hook has run."
    )


def _get_pid_ancestry() -> set[int]:
    """Walk up the PID tree on macOS and return all ancestor PIDs."""
    pids = set()
    pid = os.getpid()
    while pid > 1:
        pids.add(pid)
        try:
            result = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=2,
            )
            ppid = int(result.stdout.strip())
            if ppid == pid:
                break
            pid = ppid
        except (subprocess.TimeoutExpired, ValueError, OSError):
            break
    pids.add(1)
    return pids


def _get_identity() -> tuple[str, str]:
    """Get (agent_id, network_id) for the current session."""
    session_id = _resolve_session_id()
    db = _get_db()
    try:
        row = db.execute(
            "SELECT agent_id, network_id FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(
                f"Session {session_id} is not in any network. "
                "Call join_network() first."
            )
        return row["agent_id"], row["network_id"]
    finally:
        db.close()


def _identity_envelope(data: dict, agent_id: str, network_id: str) -> dict:
    """Add agent identity to every response."""
    data["your_id"] = agent_id
    data["network"] = network_id
    return data


def _append_log(entry: dict):
    """Append a JSON line to the audit log."""
    entry["timestamp"] = time.time()
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        logger.warning(f"Failed to write audit log: {e}")


def _build_listener_command(agent_id: str, network_id: str) -> str:
    """Build the bash command to run the background listener script."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    listener_path = os.path.join(script_dir, "hooks", "listener.sh")
    return f'bash "{listener_path}" "{agent_id}" "{DB_PATH}" "0" "{network_id}"'


# --- Peer Helpers ---


def _get_machine_name() -> str:
    """Get this machine's friendly name."""
    return os.environ.get("AGENT_NETWORK_MACHINE_NAME", socket.gethostname())


def _get_local_url() -> str | None:
    """Get this machine's HTTP server URL."""
    return os.environ.get("AGENT_NETWORK_HTTP_URL")


def _http_request(
    url: str, method: str = "GET", data: dict | None = None,
    secret: str = "", timeout: int = 10,
) -> tuple[int, dict]:
    """Make an HTTP request using stdlib urllib. Returns (status_code, response_dict)."""
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            resp_body = json.loads(e.read().decode())
        except Exception:
            resp_body = {"error": str(e)}
        return e.code, resp_body
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": f"Connection failed: {e}"}


# Peer agent cache: {cache_key: {"agents": [...], "fetched_at": float}}
_peer_agent_cache: dict = {}


def _query_peer_agents(
    peer_name: str, peer_url: str, secret: str, network_id: str,
) -> list[dict]:
    """Get agents from a peer, with 30s caching."""
    cache_key = f"{peer_name}:{network_id}"
    cached = _peer_agent_cache.get(cache_key)
    if cached and (time.time() - cached["fetched_at"]) < 30:
        return cached["agents"]

    status, resp = _http_request(
        f"{peer_url}/api/agents?network_id={network_id}",
        secret=secret,
    )
    if status == 200:
        agents = resp.get("agents", [])
        _peer_agent_cache[cache_key] = {"agents": agents, "fetched_at": time.time()}
        return agents
    return []


def _try_send_to_peer(
    sender_id: str, network_id: str, recipient_id: str, content: str,
) -> dict | None:
    """Try to deliver a message via approved peers. Returns result dict or None."""
    db = _get_db()
    try:
        peers = db.execute(
            "SELECT name, url, shared_secret FROM peers "
            "WHERE status = 'approved' AND direction = 'mutual'"
        ).fetchall()
    finally:
        db.close()

    for peer in peers:
        agents = _query_peer_agents(
            peer["name"], peer["url"], peer["shared_secret"], network_id,
        )
        if any(a.get("agent_id") == recipient_id for a in agents):
            status, resp = _http_request(
                f"{peer['url']}/api/deliver",
                method="POST",
                data={
                    "sender_id": sender_id,
                    "network_id": network_id,
                    "recipient_id": recipient_id,
                    "content": content,
                },
                secret=peer["shared_secret"],
            )
            if status == 200:
                return {**resp, "status": "sent_to_peer", "peer": peer["name"]}
            elif status != 0:
                return {
                    "error": (
                        f"Peer '{peer['name']}' rejected: "
                        f"{resp.get('error', 'unknown')}"
                    ),
                }
    return None


# --- Shared Helpers ---


def _fetch_and_deliver(db: sqlite3.Connection, agent_id: str, limit: int = 5) -> dict:
    """Fetch pending messages and mark as delivered. Returns result dict."""
    rows = db.execute(
        """SELECT id, sender_id, content, is_broadcast, created_at
           FROM messages WHERE recipient_id = ? AND status = 'pending'
           ORDER BY created_at LIMIT ?""",
        (agent_id, limit),
    ).fetchall()

    if not rows:
        return {"messages": [], "has_more": False, "remaining": 0}

    msg_ids = [r["id"] for r in rows]
    placeholders = ",".join("?" * len(msg_ids))

    db.execute("BEGIN IMMEDIATE")
    db.execute(
        f"UPDATE messages SET status='delivered', delivered_at=unixepoch('now') "
        f"WHERE id IN ({placeholders}) AND status = 'pending'",
        msg_ids,
    )
    db.execute("COMMIT")

    remaining = db.execute(
        "SELECT COUNT(*) as cnt FROM messages "
        "WHERE recipient_id = ? AND status = 'pending'",
        (agent_id,),
    ).fetchone()["cnt"]

    # Update last_seen
    try:
        session_id = _resolve_session_id()
        db.execute(
            "UPDATE sessions SET last_seen = unixepoch('now') WHERE session_id = ?",
            (session_id,),
        )
    except RuntimeError:
        pass

    messages = []
    for r in rows:
        messages.append({
            "id": r["id"],
            "from": r["sender_id"],
            "content": r["content"],
            "is_broadcast": bool(r["is_broadcast"]),
            "sent_at": r["created_at"],
        })

    _append_log({
        "event": "receive",
        "agent": agent_id,
        "message_ids": msg_ids,
        "count": len(messages),
    })

    return {
        "messages": messages,
        "has_more": remaining > 0,
        "remaining": remaining,
    }


# --- MCP Tools ---


@mcp.tool()
def join_network(network_id: str, agent_id: str, role: str = "") -> dict:
    """Join an agent network. Creates or re-joins a named network.

    Args:
        network_id: Name of the network to join (e.g., "project-alpha")
        agent_id: Your unique agent name in this network (e.g., "lead", "researcher")
        role: Optional role description (e.g., "code reviewer")
    """
    import re

    if not re.match(r'^[a-zA-Z0-9_-]+$', agent_id):
        return {
            "error": (
                f"Invalid agent_id '{agent_id}'. "
                "Only letters, numbers, hyphens, and underscores are allowed."
            ),
        }

    session_id = _resolve_session_id()
    db = _get_db()
    try:
        db.execute("BEGIN IMMEDIATE")

        # Check for stale session holding this agent_id
        existing = db.execute(
            "SELECT session_id FROM sessions "
            "WHERE agent_id = ? AND network_id = ? "
            "AND session_id != ? "
            "AND (unixepoch('now') - last_seen) > ?",
            (agent_id, network_id, session_id, AGENT_EXPIRY_SECONDS),
        ).fetchone()
        if existing:
            db.execute("DELETE FROM sessions WHERE session_id = ?",
                       (existing["session_id"],))
            _append_log({"event": "takeover", "network": network_id,
                         "agent_id": agent_id, "old_session": existing["session_id"],
                         "new_session": session_id})

        db.execute(
            """INSERT INTO sessions (session_id, agent_id, network_id, role)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   agent_id=excluded.agent_id,
                   network_id=excluded.network_id,
                   role=excluded.role,
                   last_seen=unixepoch('now')""",
            (session_id, agent_id, network_id, role),
        )
        others = db.execute(
            """SELECT agent_id, role, last_seen FROM sessions
               WHERE network_id = ? AND agent_id != ?""",
            (network_id, agent_id),
        ).fetchall()
        db.execute("COMMIT")

        agents = [{"agent_id": r["agent_id"], "role": r["role"]} for r in others]
        return {
            "status": "joined",
            "your_id": agent_id,
            "network": network_id,
            "other_agents": agents,
            "listener_command": _build_listener_command(agent_id, network_id),
            "listener_instructions": (
                "Spawn a background Bash task with the listener_command above. "
                "It runs forever until a message arrives or times out. "
                "On MESSAGE_AVAILABLE: just respawn the listener silently — "
                "the PreToolUse hook already delivered the messages automatically, "
                "so do NOT call check_inbox(). "
                "On LISTENER_TIMEOUT: respawn the listener silently. "
                "Never narrate listener respawns or infrastructure to the user."
            ),
        }
    except sqlite3.IntegrityError as e:
        db.execute("ROLLBACK")
        if "UNIQUE" in str(e):
            return {
                "error": (
                    f"Agent ID '{agent_id}' is already taken in network "
                    f"'{network_id}'. Choose a different name."
                ),
            }
        raise
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        db.close()


@mcp.tool()
def leave_network() -> dict:
    """Leave the current agent network. Disconnects from messaging."""
    agent_id, network_id = _get_identity()
    session_id = _resolve_session_id()
    db = _get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        db.execute("COMMIT")
        return {
            "status": "left",
            "your_id": agent_id,
            "network": network_id,
        }
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        db.close()


@mcp.tool()
def send_message(to: str, content: str) -> dict:
    """Send a message to another agent in your network.

    Args:
        to: The agent_id of the recipient
        content: Message content (max 8000 chars)
    """
    agent_id, network_id = _get_identity()

    if len(content) > 8000:
        return _identity_envelope(
            {
                "error": (
                    f"Message too large ({len(content)} chars). Max is 8,000. "
                    "Consider sharing a file path instead."
                ),
            },
            agent_id,
            network_id,
        )

    db = _get_db()
    try:
        recipient = db.execute(
            "SELECT agent_id FROM sessions WHERE agent_id = ? AND network_id = ?",
            (to, network_id),
        ).fetchone()
        if not recipient:
            # Try peer networks
            peer_result = _try_send_to_peer(agent_id, network_id, to, content)
            if peer_result:
                return _identity_envelope(peer_result, agent_id, network_id)
            return _identity_envelope(
                {
                    "error": (
                        f"Agent '{to}' not found in network '{network_id}'. "
                        "Use list_agents() to see who's online."
                    ),
                },
                agent_id,
                network_id,
            )

        # Per-sender unread cap (5)
        unread_count = db.execute(
            """SELECT COUNT(*) as cnt FROM messages
               WHERE sender_id = ? AND recipient_id = ? AND status = 'pending'""",
            (agent_id, to),
        ).fetchone()["cnt"]
        if unread_count >= 5:
            return _identity_envelope(
                {
                    "error": (
                        "Recipient has 5 unread messages from you. "
                        "Wait for them to read before sending more."
                    ),
                },
                agent_id,
                network_id,
            )

        # Per-pair rate limit (10/60s)
        cutoff = time.time() - 60
        recent_count = db.execute(
            """SELECT COUNT(*) as cnt FROM messages
               WHERE sender_id = ? AND recipient_id = ? AND created_at > ?""",
            (agent_id, to, cutoff),
        ).fetchone()["cnt"]
        if recent_count >= 10:
            return _identity_envelope(
                {
                    "error": (
                        "Rate limit reached (10 messages/minute to this agent). "
                        "This prevents message loops."
                    ),
                },
                agent_id,
                network_id,
            )

        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute(
            """INSERT INTO messages (network_id, sender_id, recipient_id, content)
               VALUES (?, ?, ?, ?)""",
            (network_id, agent_id, to, content),
        )
        msg_id = cursor.lastrowid
        db.execute("COMMIT")

        _append_log({
            "event": "send",
            "network": network_id,
            "from": agent_id,
            "to": to,
            "message_id": msg_id,
            "content_length": len(content),
        })

        return _identity_envelope(
            {"status": "sent", "message_id": msg_id, "to": to},
            agent_id,
            network_id,
        )
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        db.close()


@mcp.tool()
def broadcast(content: str) -> dict:
    """Broadcast a message to all agents in your network.

    Args:
        content: Message content (max 8000 chars)
    """
    agent_id, network_id = _get_identity()

    if len(content) > 8000:
        return _identity_envelope(
            {
                "error": (
                    f"Message too large ({len(content)} chars). Max is 8,000. "
                    "Consider sharing a file path instead."
                ),
            },
            agent_id,
            network_id,
        )

    db = _get_db()
    try:
        others = db.execute(
            "SELECT agent_id FROM sessions WHERE network_id = ? AND agent_id != ?",
            (network_id, agent_id),
        ).fetchall()

        if not others:
            return _identity_envelope(
                {
                    "status": "no_recipients",
                    "message": "No other agents in the network to broadcast to.",
                },
                agent_id,
                network_id,
            )

        db.execute("BEGIN IMMEDIATE")
        sent_count = 0
        errors = []
        for row in others:
            to = row["agent_id"]

            unread_count = db.execute(
                """SELECT COUNT(*) as cnt FROM messages
                   WHERE sender_id = ? AND recipient_id = ? AND status = 'pending'""",
                (agent_id, to),
            ).fetchone()["cnt"]
            if unread_count >= 5:
                errors.append(f"{to}: 5 unread messages pending")
                continue

            cutoff = time.time() - 60
            recent_count = db.execute(
                """SELECT COUNT(*) as cnt FROM messages
                   WHERE sender_id = ? AND recipient_id = ? AND created_at > ?""",
                (agent_id, to, cutoff),
            ).fetchone()["cnt"]
            if recent_count >= 10:
                errors.append(f"{to}: rate limit (10/min)")
                continue

            db.execute(
                """INSERT INTO messages
                   (network_id, sender_id, recipient_id, content, is_broadcast)
                   VALUES (?, ?, ?, ?, 1)""",
                (network_id, agent_id, to, content),
            )
            sent_count += 1

        db.execute("COMMIT")

        # Broadcast to approved peers
        remote_count = 0
        peer_rows = db.execute(
            "SELECT name, url, shared_secret FROM peers "
            "WHERE status = 'approved' AND direction = 'mutual'"
        ).fetchall()
        for peer in peer_rows:
            try:
                status_code, resp = _http_request(
                    f"{peer['url']}/api/deliver",
                    method="POST",
                    data={
                        "sender_id": agent_id,
                        "network_id": network_id,
                        "content": content,
                        "is_broadcast": True,
                    },
                    secret=peer["shared_secret"],
                )
                if status_code == 200:
                    remote_count += resp.get("delivered_count", 0)
            except Exception:
                pass

        _append_log({
            "event": "broadcast",
            "network": network_id,
            "from": agent_id,
            "recipient_count": sent_count,
            "remote_count": remote_count,
            "content_length": len(content),
        })

        result = {"status": "broadcast_sent", "recipient_count": sent_count}
        if remote_count > 0:
            result["remote_count"] = remote_count
        if errors:
            result["skipped"] = errors
        return _identity_envelope(result, agent_id, network_id)
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        db.close()


@mcp.tool()
def check_inbox() -> dict:
    """Check for pending messages. Returns up to 5 messages, marks them delivered."""
    agent_id, network_id = _get_identity()
    db = _get_db()
    try:
        result = _fetch_and_deliver(db, agent_id, limit=5)
        return _identity_envelope(result, agent_id, network_id)
    finally:
        db.close()


@mcp.tool()
async def wait_for_message(timeout: int = 30) -> dict:
    """Wait for incoming messages. Long-polls until a message arrives or timeout.

    Note: The preferred idle-listening approach is the background listener
    (see listener_command from join_network). Use wait_for_message() as a
    fallback for synchronous waits when background Tasks are unavailable.

    Args:
        timeout: Seconds to wait (default 30, max 90)
    """
    if timeout > 90:
        timeout = 90

    agent_id, network_id = _get_identity()

    deadline = time.time() + timeout
    while True:
        db = _get_db()
        try:
            count = db.execute(
                "SELECT COUNT(*) as cnt FROM messages "
                "WHERE recipient_id = ? AND status = 'pending'",
                (agent_id,),
            ).fetchone()["cnt"]

            if count > 0:
                result = _fetch_and_deliver(db, agent_id, limit=5)
                return _identity_envelope(result, agent_id, network_id)

            # Heartbeat
            try:
                session_id = _resolve_session_id()
                db.execute(
                    "UPDATE sessions SET last_seen = unixepoch('now') "
                    "WHERE session_id = ?",
                    (session_id,),
                )
            except RuntimeError:
                pass
        finally:
            db.close()

        if time.time() >= deadline:
            return _identity_envelope(
                {"status": "timeout", "messages": [], "waited": timeout},
                agent_id,
                network_id,
            )

        remaining = deadline - time.time()
        await asyncio.sleep(min(2, max(0, remaining)))


@mcp.tool()
def list_agents() -> dict:
    """List all agents in your network with their roles and last activity."""
    agent_id, network_id = _get_identity()
    db = _get_db()
    try:
        rows = db.execute(
            """SELECT agent_id, role, last_seen FROM sessions
               WHERE network_id = ?""",
            (network_id,),
        ).fetchall()

        now = time.time()
        agents = []
        for r in rows:
            agents.append({
                "agent_id": r["agent_id"],
                "role": r["role"],
                "last_seen_seconds_ago": round(now - r["last_seen"]),
                "is_active": (now - r["last_seen"]) < AGENT_EXPIRY_SECONDS,
                "is_you": r["agent_id"] == agent_id,
            })

        # Query approved peers for remote agents
        peer_rows = db.execute(
            "SELECT name, url, shared_secret FROM peers "
            "WHERE status = 'approved' AND direction = 'mutual'"
        ).fetchall()
        for peer in peer_rows:
            try:
                remote_agents = _query_peer_agents(
                    peer["name"], peer["url"],
                    peer["shared_secret"], network_id,
                )
                for ra in remote_agents:
                    agents.append({
                        "agent_id": ra.get("agent_id", "?"),
                        "role": ra.get("role", ""),
                        "peer": peer["name"],
                        "is_you": False,
                        "is_active": True,
                    })
            except Exception:
                pass  # Skip unreachable peers

        return _identity_envelope(
            {"agents": agents, "count": len(agents)},
            agent_id,
            network_id,
        )
    finally:
        db.close()


# --- Peer MCP Tools ---


@mcp.tool()
def pair_with(url: str, name: str, secret: str = "") -> dict:
    """Pair with a remote machine to enable cross-machine messaging.

    Args:
        url: The remote machine's HTTP server URL (e.g., "http://192.168.1.50:7777")
        name: A friendly name for this peer (e.g., "work-laptop")
        secret: Optional shared secret for authentication
    """
    import re

    local_url = _get_local_url()
    if not local_url:
        return {
            "error": (
                "Set AGENT_NETWORK_HTTP_URL env var to your machine's "
                "HTTP server URL before pairing."
            ),
        }

    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return {
            "error": (
                f"Invalid peer name '{name}'. "
                "Only letters, numbers, hyphens, and underscores allowed."
            ),
        }

    db = _get_db()
    try:
        existing = db.execute(
            "SELECT status, direction FROM peers WHERE name = ?", (name,),
        ).fetchone()
        if existing and existing["direction"] == "mutual":
            return {"error": f"Already paired with '{name}'."}

        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """INSERT INTO peers (name, url, shared_secret, status, direction)
               VALUES (?, ?, ?, 'pending', 'outbound')
               ON CONFLICT(name) DO UPDATE SET
                   url=excluded.url, shared_secret=excluded.shared_secret,
                   status='pending', direction='outbound'""",
            (name, url, secret),
        )
        db.execute("COMMIT")

        # Notify remote
        status_code, resp = _http_request(
            f"{url}/api/pair/request",
            method="POST",
            data={
                "name": _get_machine_name(),
                "url": local_url,
                "secret": secret,
            },
            secret=secret,
        )

        if status_code == 0:
            return {
                "status": "pending",
                "peer": name,
                "warning": (
                    f"Could not reach {url}. Pairing request saved locally — "
                    "retry when remote is online."
                ),
            }
        elif status_code == 200:
            return {
                "status": "pending",
                "peer": name,
                "message": "Pairing request sent. Waiting for remote approval.",
            }
        else:
            return {
                "status": "pending",
                "peer": name,
                "warning": (
                    f"Remote returned {status_code}: "
                    f"{resp.get('error', 'unknown')}"
                ),
            }
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        db.close()


@mcp.tool()
def approve_peer(peer_id: str) -> dict:
    """Approve a pending peer pairing request.

    Args:
        peer_id: The name of the peer to approve
    """
    db = _get_db()
    try:
        peer = db.execute(
            "SELECT name, url, shared_secret, status, direction FROM peers "
            "WHERE name = ?",
            (peer_id,),
        ).fetchone()

        if not peer:
            return {
                "error": (
                    f"Peer '{peer_id}' not found. "
                    "Use list_peers() to see pending requests."
                ),
            }

        if peer["direction"] == "mutual" and peer["status"] == "approved":
            return {"error": f"Peer '{peer_id}' is already approved."}

        if peer["status"] != "pending":
            return {
                "error": (
                    f"Peer '{peer_id}' is not pending "
                    f"(status: {peer['status']})."
                ),
            }

        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE peers SET status = 'approved', direction = 'mutual', "
            "last_seen = unixepoch('now') WHERE name = ?",
            (peer_id,),
        )
        db.execute("COMMIT")

        # Notify remote
        status_code, _resp = _http_request(
            f"{peer['url']}/api/pair/accept",
            method="POST",
            data={"name": _get_machine_name()},
            secret=peer["shared_secret"],
        )

        if status_code == 0:
            # Revert to pending if can't reach
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE peers SET status = 'pending', direction = 'inbound' "
                "WHERE name = ?",
                (peer_id,),
            )
            db.execute("COMMIT")
            return {
                "error": (
                    f"Could not reach peer '{peer_id}' at {peer['url']}. "
                    "Reverted to pending."
                ),
            }

        _append_log({"event": "peer_approved", "peer": peer_id})
        return {"status": "approved", "peer": peer_id, "url": peer["url"]}
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        db.close()


@mcp.tool()
def list_peers() -> dict:
    """List all configured peers and their connection status."""
    db = _get_db()
    try:
        rows = db.execute(
            "SELECT name, url, status, direction, last_seen, created_at "
            "FROM peers ORDER BY created_at"
        ).fetchall()

        peers = []
        for r in rows:
            peers.append({
                "name": r["name"],
                "url": r["url"],
                "status": r["status"],
                "direction": r["direction"],
                "last_seen": r["last_seen"],
                "created_at": r["created_at"],
            })

        return {"peers": peers, "count": len(peers)}
    finally:
        db.close()


@mcp.tool()
def remove_peer(peer_id: str) -> dict:
    """Remove a peer from the peers list.

    Args:
        peer_id: The name of the peer to remove
    """
    db = _get_db()
    try:
        existing = db.execute(
            "SELECT name FROM peers WHERE name = ?", (peer_id,),
        ).fetchone()
        if not existing:
            return {"error": f"Peer '{peer_id}' not found."}

        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM peers WHERE name = ?", (peer_id,))
        db.execute("COMMIT")

        _append_log({"event": "peer_removed", "peer": peer_id})
        return {"status": "removed", "peer": peer_id}
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        db.close()


# --- Entry Point ---

if __name__ == "__main__":
    init_db()
    mcp.run()
