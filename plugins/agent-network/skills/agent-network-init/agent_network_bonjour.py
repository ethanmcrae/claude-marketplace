#!/usr/bin/env python3
"""Bonjour (mDNS) auto-discovery for Agent Network cross-machine messaging.

Uses dns-sd subprocesses (macOS built-in) to register, browse, and resolve
services on the local network. Stdlib only — no external dependencies.

Service type: _agent-network._tcp
TXT records: machine=<name> v=1
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time

logger = logging.getLogger("agent-network.bonjour")

SERVICE_TYPE = "_agent-network._tcp"
DOMAIN = "local"
RESOLVE_TIMEOUT = 5


def parse_browse_line(line: str) -> tuple[str, str] | None:
    """Parse a dns-sd -B output line into (action, service_name).

    Returns ("Add", name) or ("Rmv", name) on match, None otherwise.
    Example input:
      " 0:00:00.001  Add        3   4 local.  _agent-network._tcp. MacBookPro"
    """
    m = re.match(
        r"\s*\d+:\d+:\d+\.\d+\s+(Add|Rmv)\s+\d+\s+\d+\s+\S+\s+\S+\s+(.+)",
        line,
    )
    if m:
        return m.group(1), m.group(2).strip()
    return None


def resolve_service(
    name: str, timeout: float = RESOLVE_TIMEOUT,
) -> tuple[str, int, dict] | None:
    """Resolve a Bonjour service name to (host, port, txt_dict).

    Spawns dns-sd -L, parses the first result, and kills the process.
    Returns None on timeout or parse failure.
    """
    try:
        proc = subprocess.Popen(
            ["dns-sd", "-L", name, SERVICE_TYPE, DOMAIN],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as e:
        logger.warning(f"Failed to spawn dns-sd -L: {e}")
        return None

    host = None
    port = None
    txt: dict[str, str] = {}
    deadline = time.monotonic() + timeout

    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            line_result: list[str | None] = [None]

            def _read_line():
                try:
                    line_result[0] = proc.stdout.readline()
                except Exception:
                    pass

            reader = threading.Thread(target=_read_line, daemon=True)
            reader.start()
            reader.join(timeout=max(remaining, 0.1))

            line = line_result[0]
            if line is None or line == "":
                break

            # Parse resolve line: "... can be reached at host.local.:port ..."
            reach_match = re.search(
                r"can be reached at\s+(\S+):(\d+)", line,
            )
            if reach_match:
                host = reach_match.group(1).rstrip(".")
                port = int(reach_match.group(2))

                # Try to read the next line for TXT records
                txt_result: list[str | None] = [None]

                def _read_txt():
                    try:
                        txt_result[0] = proc.stdout.readline()
                    except Exception:
                        pass

                txt_reader = threading.Thread(target=_read_txt, daemon=True)
                txt_reader.start()
                txt_reader.join(timeout=2)

                txt_line = txt_result[0]
                if txt_line:
                    for kv in re.findall(r"(\w+)=(\S+)", txt_line):
                        txt[kv[0]] = kv[1]
                break
    finally:
        proc.kill()
        proc.wait()

    if host and port:
        return host, port, txt
    return None


class BonjourRegistrar:
    """Register a Bonjour service via dns-sd -R.

    The dns-sd process must stay alive for the registration to persist.
    Call .stop() to unregister.
    """

    def __init__(self, name: str, port: int, txt: dict[str, str] | None = None):
        self.name = name
        self.port = port
        self.txt = txt or {}
        self._proc: subprocess.Popen | None = None

    def start(self):
        """Start the dns-sd -R process to register the service."""
        cmd = [
            "dns-sd", "-R", self.name, SERVICE_TYPE, DOMAIN, str(self.port),
        ]
        for k, v in self.txt.items():
            cmd.append(f"{k}={v}")

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"Bonjour: registered '{self.name}' on port {self.port}")
        except OSError as e:
            logger.warning(f"Failed to start Bonjour registration: {e}")

    def stop(self):
        """Stop the dns-sd process, unregistering the service."""
        if self._proc:
            self._proc.kill()
            self._proc.wait()
            self._proc = None
            logger.info(f"Bonjour: unregistered '{self.name}'")

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


class BonjourBrowser:
    """Browse for Bonjour services via dns-sd -B on a daemon thread.

    Calls on_add(name) and on_remove(name) callbacks as services
    appear/disappear.
    """

    def __init__(
        self,
        on_add: callable | None = None,
        on_remove: callable | None = None,
    ):
        self.on_add = on_add
        self.on_remove = on_remove
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        """Start browsing for services."""
        try:
            self._proc = subprocess.Popen(
                ["dns-sd", "-B", SERVICE_TYPE, DOMAIN],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as e:
            logger.warning(f"Failed to start Bonjour browser: {e}")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        logger.info("Bonjour: browsing for services")

    def _read_loop(self):
        """Read dns-sd -B stdout and fire callbacks."""
        while not self._stop_event.is_set():
            try:
                line = self._proc.stdout.readline()
                if not line:
                    break

                result = parse_browse_line(line)
                if result:
                    action, name = result
                    try:
                        if action == "Add" and self.on_add:
                            self.on_add(name)
                        elif action == "Rmv" and self.on_remove:
                            self.on_remove(name)
                    except Exception as e:
                        logger.warning(f"Bonjour callback error: {e}")
            except Exception:
                break

    def stop(self):
        """Stop browsing."""
        self._stop_event.set()
        if self._proc:
            self._proc.kill()
            self._proc.wait()
            self._proc = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Bonjour: stopped browsing")

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
