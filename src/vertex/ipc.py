"""The control socket: how `vertex save-clip` and outside software reach the
running app.

Desktop environments bind global shortcuts to commands, not to applications,
so a hotkey for "save the last minute" is simply `vertex save-clip` bound in
the desktop's keyboard settings. That command connects to a Unix socket the
running Vertex listens on, sends one JSON line and reads one back:

    → {"command": "save-clip", "args": {"seconds": 60}}
    ← {"ok": true, "message": "Saving the last 60 seconds…"}

The commands, replies and events are the control API, described in
`vertex.control`. A `subscribe` request keeps its connection open and gets
one line per event.

The socket also makes Vertex single-instance: launching it again just asks
the running one to show its window.
"""

from __future__ import annotations

import json
import os
import queue
import select
import socket
import socketserver
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from vertex import __version__, control, paths

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


def follow(socket_path: str | os.PathLike | None = None) -> Iterator[dict]:
    """Subscribe: the first reply (the state), then every event, as they come,
    until Vertex stops or the caller stops iterating."""
    path = str(socket_path or paths.control_socket())
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(path)
    except OSError as exc:
        raise NotRunning() from exc
    with client, client.makefile("rb") as lines:
        client.sendall(json.dumps({"command": "subscribe", "args": {}}).encode() + b"\n")
        for line in lines:
            try:
                yield json.loads(line.decode())
            except ValueError:
                continue


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
                reply = {"ok": True, "message": "pong", "pid": os.getpid(),
                         "data": {"api": control.API_VERSION, "version": __version__}}
            elif command == "subscribe" and self.server.subscribers is not None:
                self._stream()
                return
            else:
                reply = self.server.dispatch(command, args)
        except Exception as exc:     # the client gets the error; we keep serving
            reply = control.error(control.FAILED, f"Error: {exc}")
        try:
            self._send(reply)
        except OSError:
            pass   # the client hung up

    def _send(self, message: dict) -> None:
        self.wfile.write(json.dumps(message).encode() + b"\n")
        self.wfile.flush()

    def _stream(self) -> None:
        """The state now, then every event, until the client hangs up."""
        subscribers = self.server.subscribers
        events = subscribers.add()
        try:
            self._send(self.server.dispatch("state", {}))
            while not self.server.stopping.is_set():
                try:
                    event = events.get(timeout=0.5)
                except queue.Empty:
                    if self._hung_up():
                        return
                    continue
                self._send(event)
        except OSError:
            pass     # the client hung up
        finally:
            subscribers.remove(events)

    def _hung_up(self) -> bool:
        readable, _w, _x = select.select([self.connection], [], [], 0)
        if not readable:
            return False
        try:
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True


class Subscribers:
    """The clients following events, each with its own queue. Thread-safe:
    the UI publishes, the socket's threads read."""

    LIMIT = 1000         # events kept for a client that has stopped reading

    def __init__(self):
        self._lock = threading.Lock()
        self._queues: list[queue.Queue] = []

    def add(self) -> queue.Queue:
        events: queue.Queue = queue.Queue(self.LIMIT)
        with self._lock:
            self._queues.append(events)
        return events

    def remove(self, events: queue.Queue) -> None:
        with self._lock:
            if events in self._queues:
                self._queues.remove(events)

    def publish(self, event: dict) -> None:
        with self._lock:
            for events in self._queues:
                try:
                    events.put_nowait(event)
                except queue.Full:
                    pass     # it isn't reading; it misses this one

    def __len__(self) -> int:
        with self._lock:
            return len(self._queues)


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path: str, dispatch: Handler, subscribers: Subscribers | None):
        self.dispatch = dispatch
        self.subscribers = subscribers
        self.stopping = threading.Event()
        super().__init__(path, _RequestHandler)


class ControlServer:
    """Serves the control socket on a background thread.

    `dispatch(command, args) -> reply` runs on the server's threads; the UI
    hands it on to its own thread.
    """

    def __init__(self, dispatch: Handler, socket_path: str | os.PathLike | None = None,
                 subscribers: Subscribers | None = None):
        self.path = Path(socket_path or paths.control_socket())
        self.dispatch = dispatch
        self.subscribers = subscribers
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
        self._server = _Server(str(self.path), self.dispatch, self.subscribers)
        os.chmod(self.path, 0o600)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True,
                                        name="vertex-control")
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.stopping.set()
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        try:
            self.path.unlink()
        except OSError:
            pass
