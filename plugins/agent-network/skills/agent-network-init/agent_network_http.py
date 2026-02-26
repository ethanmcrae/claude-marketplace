#!/usr/bin/env python3
"""Agent Network HTTP Server — peer-to-peer transport for cross-machine messaging.

Standalone HTTP server using stdlib only. Shares the same SQLite DB as the MCP
server. Enables machines to pair and exchange messages over HTTP.

Usage: python3 agent_network_http.py [--port 7777] [--host 0.0.0.0]
"""

import argparse
import json
import os
import socket
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.environ.get(
    "AGENT_NETWORK_DB", os.path.expanduser("~/.claude/agent_network.db")
)
PENDING_CAP_PER_PEER = 20


def _get_machine_name() -> str:
    return os.environ.get("AGENT_NETWORK_MACHINE_NAME", socket.gethostname())


def _get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, isolation_level=None)
    db.execute("PRAGMA busy_timeout=30000")
    db.row_factory = sqlite3.Row
    return db


def _json_response(handler: BaseHTTPRequestHandler, code: int, data: dict):
    body = json.dumps(data).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode())


def _auth_peer(handler: BaseHTTPRequestHandler, db: sqlite3.Connection) -> dict | None:
    """Validate bearer token against peers table. Returns peer row or None."""
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    peer = db.execute(
        "SELECT name, url, shared_secret, status, direction FROM peers "
        "WHERE shared_secret = ? AND status = 'approved' AND direction = 'mutual'",
        (token,),
    ).fetchone()
    return dict(peer) if peer else None


class AgentNetworkHandler(BaseHTTPRequestHandler):
    """HTTP request handler for agent network peer endpoints."""

    def log_message(self, fmt, *args):
        # Suppress default stderr logging
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/health":
            self._handle_health()
        elif path == "/api/agents":
            self._handle_agents(parsed)
        else:
            _json_response(self, 404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/deliver":
            self._handle_deliver()
        elif path == "/api/pair/request":
            self._handle_pair_request()
        elif path == "/api/pair/accept":
            self._handle_pair_accept()
        else:
            _json_response(self, 404, {"error": "Not found"})

    def _handle_health(self):
        _json_response(self, 200, {
            "status": "ok",
            "machine": _get_machine_name(),
        })

    def _handle_agents(self, parsed):
        db = _get_db()
        try:
            # Auth check
            peer = _auth_peer(self, db)
            if not peer:
                _json_response(self, 401, {"error": "Unauthorized"})
                return

            # Update last_seen for this peer
            db.execute(
                "UPDATE peers SET last_seen = unixepoch('now') WHERE name = ?",
                (peer["name"],),
            )

            qs = parse_qs(parsed.query)
            network_id = qs.get("network_id", [None])[0]

            if network_id:
                rows = db.execute(
                    "SELECT agent_id, role, last_seen FROM sessions "
                    "WHERE network_id = ?",
                    (network_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT agent_id, role, last_seen FROM sessions"
                ).fetchall()

            now = time.time()
            agents = []
            for r in rows:
                agents.append({
                    "agent_id": r["agent_id"],
                    "role": r["role"],
                    "is_active": (now - r["last_seen"]) < 30,
                })

            _json_response(self, 200, {"agents": agents, "count": len(agents)})
        finally:
            db.close()

    def _handle_deliver(self):
        db = _get_db()
        try:
            peer = _auth_peer(self, db)
            if not peer:
                _json_response(self, 401, {"error": "Unauthorized"})
                return

            data = _read_body(self)
            sender_id = data.get("sender_id", "")
            network_id = data.get("network_id", "")
            recipient_id = data.get("recipient_id")
            content = data.get("content", "")
            is_broadcast = data.get("is_broadcast", False)

            if len(content) > 8000:
                _json_response(self, 400, {"error": "Content exceeds 8000 chars"})
                return

            # Pending cap per peer
            pending_count = db.execute(
                "SELECT COUNT(*) as cnt FROM messages "
                "WHERE sender_id = ? AND status = 'pending'",
                (sender_id,),
            ).fetchone()["cnt"]
            if pending_count >= PENDING_CAP_PER_PEER:
                _json_response(self, 429, {
                    "error": f"Too many pending messages from {sender_id}",
                })
                return

            if is_broadcast:
                # Fan out to all local agents in this network
                recipients = db.execute(
                    "SELECT agent_id FROM sessions WHERE network_id = ?",
                    (network_id,),
                ).fetchall()

                db.execute("BEGIN IMMEDIATE")
                delivered = 0
                for r in recipients:
                    db.execute(
                        "INSERT INTO messages "
                        "(network_id, sender_id, recipient_id, content, is_broadcast) "
                        "VALUES (?, ?, ?, ?, 1)",
                        (network_id, sender_id, r["agent_id"], content),
                    )
                    delivered += 1
                db.execute("COMMIT")

                _json_response(self, 200, {
                    "status": "delivered",
                    "delivered_count": delivered,
                })
            else:
                # Single recipient
                if not recipient_id:
                    _json_response(self, 400, {"error": "recipient_id required"})
                    return

                local = db.execute(
                    "SELECT agent_id FROM sessions "
                    "WHERE agent_id = ? AND network_id = ?",
                    (recipient_id, network_id),
                ).fetchone()
                if not local:
                    _json_response(self, 404, {
                        "error": f"Agent '{recipient_id}' not found locally",
                    })
                    return

                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO messages "
                    "(network_id, sender_id, recipient_id, content) "
                    "VALUES (?, ?, ?, ?)",
                    (network_id, sender_id, recipient_id, content),
                )
                db.execute("COMMIT")

                _json_response(self, 200, {
                    "status": "delivered",
                    "delivered_count": 1,
                })
        except Exception:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
            _json_response(self, 500, {"error": "Internal server error"})
        finally:
            db.close()

    def _handle_pair_request(self):
        db = _get_db()
        try:
            data = _read_body(self)
            peer_name = data.get("name", "")
            peer_url = data.get("url", "")
            secret = data.get("secret", "")

            if not peer_name or not peer_url:
                _json_response(self, 400, {
                    "error": "name and url are required",
                })
                return

            # Insert as pending/inbound
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO peers (name, url, shared_secret, status, direction)
                   VALUES (?, ?, ?, 'pending', 'inbound')
                   ON CONFLICT(name) DO UPDATE SET
                       url=excluded.url, shared_secret=excluded.shared_secret,
                       status='pending', direction='inbound'""",
                (peer_name, peer_url, secret),
            )

            # Write system notification for local agents
            sessions = db.execute("SELECT agent_id FROM sessions").fetchall()
            for s in sessions:
                db.execute(
                    "INSERT INTO messages "
                    "(network_id, sender_id, recipient_id, content) "
                    "VALUES ('_peer_system', '_system', ?, ?)",
                    (
                        s["agent_id"],
                        f"Pairing request from '{peer_name}' ({peer_url}). "
                        f"Use approve_peer('{peer_name}') to accept.",
                    ),
                )
            db.execute("COMMIT")

            _json_response(self, 200, {
                "status": "pending",
                "message": "Pairing request received",
            })
        except Exception:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
            _json_response(self, 500, {"error": "Internal server error"})
        finally:
            db.close()

    def _handle_pair_accept(self):
        db = _get_db()
        try:
            data = _read_body(self)
            peer_name = data.get("name", "")

            if not peer_name:
                _json_response(self, 400, {"error": "name is required"})
                return

            peer = db.execute(
                "SELECT name, status, direction FROM peers WHERE name = ?",
                (peer_name,),
            ).fetchone()

            if not peer:
                _json_response(self, 404, {
                    "error": f"Peer '{peer_name}' not found",
                })
                return

            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE peers SET status = 'approved', direction = 'mutual', "
                "last_seen = unixepoch('now') WHERE name = ?",
                (peer_name,),
            )

            # Write system notification
            sessions = db.execute("SELECT agent_id FROM sessions").fetchall()
            for s in sessions:
                db.execute(
                    "INSERT INTO messages "
                    "(network_id, sender_id, recipient_id, content) "
                    "VALUES ('_peer_system', '_system', ?, ?)",
                    (
                        s["agent_id"],
                        f"Peer '{peer_name}' pairing confirmed. "
                        "Cross-machine messaging is now active.",
                    ),
                )
            db.execute("COMMIT")

            _json_response(self, 200, {
                "status": "approved",
                "message": "Pairing confirmed",
            })
        except Exception:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
            _json_response(self, 500, {"error": "Internal server error"})
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description="Agent Network HTTP Server")
    parser.add_argument("--port", type=int, default=7777, help="Port (default: 7777)")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AgentNetworkHandler)
    print(f"Agent Network HTTP server on {args.host}:{args.port}")
    print(f"Machine name: {_get_machine_name()}")
    print(f"DB: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
