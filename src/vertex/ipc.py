"""The control socket: how `vertex save-clip` reaches the running app.

Desktop environments bind global shortcuts to commands, not to applications,
so a hotkey for "save the last minute" is simply `vertex save-clip` bound in
the desktop's keyboard settings. That command connects to a Unix socket the
running Vertex listens on, sends one JSON line and reads one back:

    → {"command": "save-clip", "args": {"seconds": 60}}
    ← {"ok": true, "message": "Saving the last 60 seconds…"}

The socket also makes Vertex single-instance: launching it again just asks
the running one to show its window.
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
from collections.abc import Callable
from pathlib import Path

from vertex import paths

TIMEOUT = 10.0
Handler = Callable[[str, dict], dict]


class NotRunning(RuntimeError):
    def __init__(self):
        super().__init__("Vertex is not running.")


def send(command: str, socket_path: str | os.PathLike | None = None,
         timeout: float = TIMEOUT, **args) -> dict:
    """Send one command to the running Vertex and return its reply."""
    path = str(socket_path or paths.control_socket())
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(path)
            client.sendall(json.dumps({"command": command, "args": args}).encode() + b"\n")
            reply = b""
            while not reply.endswith(b"\n"):
                chunk = client.recv(65536)
                if not chunk:
                    break
                reply += chunk
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        raise NotRunning() from exc
    except OSError as exc:
        raise NotRunning() from exc
    try:
        data = json.loads(reply.decode() or "{}")
    except ValueError:
        return {"ok": False, "message": "Vertex sent an unreadable reply."}
    return data if isinstance(data, dict) else {"ok": False, "message": "Bad reply."}


def is_running(socket_path: str | os.PathLike | None = None) -> bool:
    try:
        send("ping", socket_path, timeout=2)
    except NotRunning:
        return False
    return True


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(65536)
            request = json.loads(line.decode() or "{}")
            command = str(request.get("command", ""))
            args = request.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            if command == "ping":
                reply = {"ok": True, "message": "pong", "pid": os.getpid()}
            else:
                reply = self.server.dispatch(command, args)
        except Exception as exc:     # the client gets the error; we keep serving
            reply = {"ok": False, "message": f"Error: {exc}"}
        try:
            self.wfile.write(json.dumps(reply).encode() + b"\n")
        except OSError:
            pass   # the client hung up


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path: str, dispatch: Handler):
        self.dispatch = dispatch
        super().__init__(path, _RequestHandler)


class ControlServer:
    """Serves the control socket on a background thread.

    `dispatch(command, args) -> reply` runs on the server's threads; the UI
    hands it on to its own thread.
    """

    def __init__(self, dispatch: Handler, socket_path: str | os.PathLike | None = None):
        self.path = Path(socket_path or paths.control_socket())
        self.dispatch = dispatch
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Listen. Returns False if another Vertex already owns the socket."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        if self.path.exists():
            if is_running(self.path):
                return False
            self.path.unlink()       # left behind by a crash
        self._server = _Server(str(self.path), self.dispatch)
        os.chmod(self.path, 0o600)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True,
                                        name="vertex-control")
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        try:
            self.path.unlink()
        except OSError:
            pass
