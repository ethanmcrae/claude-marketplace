#!/usr/bin/env python3
"""Agent Network HTTP Server — peer-to-peer transport for cross-machine messaging.

Standalone HTTP server using stdlib only. Shares the same SQLite DB as the MCP
server. Enables machines to pair and exchange messages over HTTP.

Usage: python3 agent_network_http.py [--port 7777] [--host 0.0.0.0]
"""

import argparse
import atexit
import json
import logging
import os
import signal
import socket
import sqlite3
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from agent_network_bonjour import BonjourBrowser, BonjourRegistrar, resolve_service

DB_PATH = os.environ.get(
    "AGENT_NETWORK_DB", os.path.expanduser("~/.claude/agent_network.db")
)
URL_FILE = os.path.expanduser("~/.claude/agent_network_http.url")
PENDING_CAP_PER_PEER = 20

logger = logging.getLogger("agent-network.http")


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
    if not token:
        return None
    peer = db.execute(
        "SELECT name, url, shared_secret, status, direction FROM peers "
        "WHERE shared_secret = ? AND status = 'approved' AND direction = 'mutual'",
        (token,),
    ).fetchone()
    return dict(peer) if peer else None


def _auto_accept(peer_name: str, peer_url: str, local_port: int):
    """Auto-accept a peer pairing request (runs in a background thread).

    1. Sleeps 500ms to let the inbound pair request transaction commit.
    2. Calls our own /api/pair/accept via loopback to update local state.
    3. POSTs to the remote's /api/pair/accept so they also reach mutual.
    """
    time.sleep(0.5)

    our_name = _get_machine_name()
    our_url = f"http://{socket.gethostname()}.local:{local_port}"

    # Step 1: Accept locally via loopback
    try:
        req_data = json.dumps({"name": peer_name}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{local_port}/api/pair/accept",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"Auto-accept loopback failed for '{peer_name}': {e}")
        return

    # Step 2: Read our stored secret so the remote can sync it
    peer_secret = ""
    db = _get_db()
    try:
        row = db.execute(
            "SELECT shared_secret FROM peers WHERE name = ?", (peer_name,),
        ).fetchone()
        if row:
            peer_secret = row["shared_secret"]
    finally:
        db.close()

    # Step 3: Notify remote so they also reach mutual (include secret for sync)
    try:
        payload = {"name": our_name, "url": our_url}
        if peer_secret:
            payload["secret"] = peer_secret
        req_data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{peer_url}/api/pair/accept",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"Auto-paired with '{peer_name}' via Bonjour")
    except Exception as e:
        logger.warning(f"Auto-accept remote notification failed for '{peer_name}': {e}")


def _on_peer_discovered(name: str, machine_name: str, local_url: str, local_port: int):
    """Called by BonjourBrowser when a new service appears on LAN."""
    if name == machine_name:
        return  # Skip self

    resolved = resolve_service(name)
    if not resolved:
        logger.warning(f"Bonjour: could not resolve '{name}'")
        return

    host, port, txt = resolved
    peer_url = f"http://{host}:{port}"

    # Skip if we already have this peer (any status)
    db = _get_db()
    try:
        existing = db.execute(
            "SELECT status, direction FROM peers WHERE name = ?", (name,),
        ).fetchone()
    finally:
        db.close()

    if existing:
        return

    # New peer: generate shared secret and initiate pairing
    shared_secret = str(uuid.uuid4())
    our_name = _get_machine_name()

    # Insert outbound peer (INSERT OR IGNORE to avoid race conditions)
    db = _get_db()
    try:
        result = db.execute(
            "INSERT OR IGNORE INTO peers (name, url, shared_secret, status, direction) "
            "VALUES (?, ?, ?, 'pending', 'outbound')",
            (name, peer_url, shared_secret),
        )
        if result.rowcount == 0:
            return  # Peer was inserted by another thread
    finally:
        db.close()

    # POST pair request to remote
    try:
        req_data = json.dumps({
            "name": our_name,
            "url": local_url,
            "secret": shared_secret,
        }).encode()
        req = urllib.request.Request(
            f"{peer_url}/api/pair/request",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"Bonjour: sent pair request to '{name}' at {peer_url}")
    except Exception as e:
        logger.warning(f"Bonjour: failed to send pair request to '{name}': {e}")


def _on_peer_removed(name: str):
    """Called by BonjourBrowser when a service disappears from LAN."""
    db = _get_db()
    try:
        db.execute(
            "UPDATE peers SET last_seen = unixepoch('now') WHERE name = ?",
            (name,),
        )
    finally:
        db.close()


class AgentNetworkHandler(BaseHTTPRequestHandler):
    """HTTP request handler for agent network peer endpoints."""

    # Set by main() so handlers can access the port for auto-accept loopback
    local_port: int = 7777

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
                active = (now - r["last_seen"]) < 30
                agents.append({
                    "agent_id": r["agent_id"],
                    "role": r["role"],
                    "is_active": active,
                })

            # Filter to active-only when requested (default: all)
            if qs.get("active", ["0"])[0] == "1":
                agents = [a for a in agents if a["is_active"]]

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

            # Check existing peer status before upserting
            existing = db.execute(
                "SELECT status, direction FROM peers WHERE name = ?",
                (peer_name,),
            ).fetchone()

            # Don't reset an already-approved mutual peer back to pending
            if existing and existing["status"] == "approved" and existing["direction"] == "mutual":
                _json_response(self, 200, {
                    "status": "already_paired",
                    "message": f"Already paired with '{peer_name}'",
                })
                return

            # Skip notifications if this is a duplicate pending/inbound request
            is_duplicate = (
                existing
                and existing["status"] == "pending"
                and existing["direction"] == "inbound"
            )

            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO peers (name, url, shared_secret, status, direction)
                   VALUES (?, ?, ?, 'pending', 'inbound')
                   ON CONFLICT(name) DO UPDATE SET
                       url=excluded.url, shared_secret=excluded.shared_secret,
                       status='pending', direction='inbound'""",
                (peer_name, peer_url, secret),
            )

            auto_pair = os.environ.get("AGENT_NETWORK_AUTO_PAIR") == "1"

            # Only notify local agents on the first request
            if not is_duplicate:
                if auto_pair:
                    # Suppress manual approval notification for auto-pair
                    sessions = db.execute("SELECT agent_id FROM sessions").fetchall()
                    for s in sessions:
                        db.execute(
                            "INSERT INTO messages "
                            "(network_id, sender_id, recipient_id, content) "
                            "VALUES ('_peer_system', '_system', ?, ?)",
                            (
                                s["agent_id"],
                                f"Auto-pairing with '{peer_name}' ({peer_url}) "
                                "via Bonjour LAN discovery...",
                            ),
                        )
                else:
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

            # Trigger auto-accept in a background thread
            if auto_pair and not is_duplicate:
                threading.Thread(
                    target=_auto_accept,
                    args=(peer_name, peer_url, self.local_port),
                    daemon=True,
                ).start()

            _json_response(self, 200, {
                "status": "already_paired" if is_duplicate else "pending",
                "message": "Pairing request received"
                + (" (duplicate suppressed)" if is_duplicate else "")
                + (" (auto-accepting)" if auto_pair and not is_duplicate else ""),
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
            peer_url = data.get("url", "")
            peer_secret = data.get("secret", "")

            if not peer_name:
                _json_response(self, 400, {"error": "name is required"})
                return

            # Try name lookup first, then fall back to URL lookup.
            # The accept payload sends the remote's hostname as "name", but
            # we may have stored the peer under a user-chosen friendly name.
            peer = db.execute(
                "SELECT name, status, direction FROM peers WHERE name = ?",
                (peer_name,),
            ).fetchone()

            if not peer and peer_url:
                peer = db.execute(
                    "SELECT name, status, direction FROM peers WHERE url = ?",
                    (peer_url,),
                ).fetchone()

            if not peer:
                _json_response(self, 404, {
                    "error": f"Peer '{peer_name}' not found"
                    + (f" (also tried URL '{peer_url}')" if peer_url else ""),
                })
                return

            # Use the actual stored name (may differ from payload name
            # when URL fallback was used)
            stored_name = peer["name"]

            db.execute("BEGIN IMMEDIATE")
            if peer_secret:
                db.execute(
                    "UPDATE peers SET status = 'approved', direction = 'mutual', "
                    "shared_secret = ?, last_seen = unixepoch('now') WHERE name = ?",
                    (peer_secret, stored_name),
                )
            else:
                db.execute(
                    "UPDATE peers SET status = 'approved', direction = 'mutual', "
                    "last_seen = unixepoch('now') WHERE name = ?",
                    (stored_name,),
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
                        f"Peer '{stored_name}' pairing confirmed. "
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

    machine_name = _get_machine_name()
    local_url = f"http://{socket.gethostname()}.local:{args.port}"

    # Write URL file for MCP server discovery
    os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
    with open(URL_FILE, "w") as f:
        f.write(local_url)

    # Make the port available to request handlers for auto-accept loopback
    AgentNetworkHandler.local_port = args.port

    server = ThreadingHTTPServer((args.host, args.port), AgentNetworkHandler)
    print(f"Agent Network HTTP server on {args.host}:{args.port}")
    print(f"Machine name: {machine_name}")
    print(f"URL: {local_url}")
    print(f"DB: {DB_PATH}")

    # Start Bonjour registration and browsing
    registrar = BonjourRegistrar(
        machine_name, args.port, {"machine": machine_name, "v": "1"},
    )
    registrar.start()

    def on_add(name):
        _on_peer_discovered(name, machine_name, local_url, args.port)

    def on_remove(name):
        _on_peer_removed(name)

    browser = BonjourBrowser(on_add=on_add, on_remove=on_remove)
    browser.start()

    print("Bonjour: LAN auto-discovery active")

    # Cleanup handler
    _cleanup_done = threading.Event()

    def cleanup():
        if _cleanup_done.is_set():
            return
        _cleanup_done.set()
        browser.stop()
        registrar.stop()
        try:
            os.unlink(URL_FILE)
        except OSError:
            pass

    atexit.register(cleanup)

    def sigterm_handler(signum, frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGTERM, sigterm_handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        cleanup()
        server.shutdown()


if __name__ == "__main__":
    main()
