"""Talks to the running Vertex over its control socket.

The commands, replies and events are Vertex's control API (`vertex.control`
in the Vertex source): one JSON object per line each way, and a `subscribe`
request that keeps the connection open and gets the state, then one line
per change.

Standard library only: this runs in StreamController's Python, not Vertex's.
StreamController's Flatpak can't see the socket (it lives in
`$XDG_RUNTIME_DIR/vertex`, outside the sandbox) unless it was given that
folder (`xdg-run/vertex`, in Flatseal or with `flatpak override`). Without
it, every connection goes through a small relay that `flatpak-spawn --host`
runs on the host.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import weakref
from collections.abc import Callable

TIMEOUT = 5.0
RETRY = 3.0          # seconds between attempts to reach a Vertex that isn't running

# Run on the host by `flatpak-spawn --host python3 -c RELAY`: connects to the
# socket (the host's own, or the path given), sends the request from stdin and
# copies every reply line to stdout.
RELAY = r"""
import os, socket, sys
base = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    client.connect(sys.argv[1] if len(sys.argv) > 1 else
                   os.path.join(base, "vertex", "control.sock"))
except OSError:
    sys.exit(3)
client.sendall(sys.stdin.buffer.readline())
for line in client.makefile("rb"):
    sys.stdout.buffer.write(line)
    sys.stdout.buffer.flush()
"""
NOT_RUNNING_EXIT = 3


class NotRunning(RuntimeError):
    def __init__(self):
        super().__init__("Vertex is not running.")


def default_socket() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(base, "vertex", "control.sock")


def in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


def _request(command: str, args: dict) -> bytes:
    return json.dumps({"command": command, "args": args}).encode() + b"\n"


def _parse(line: bytes) -> dict | None:
    try:
        data = json.loads(line.decode())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class _Connection:
    """One request and the lines that answer it, over the socket or the relay."""

    def __init__(self, line: bytes, socket_path: str, relay: list[str] | None,
                 timeout: float | None):
        self._sock = self._proc = None
        if relay is None:
            try:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._sock.settimeout(timeout)
                self._sock.connect(socket_path)
                self._sock.sendall(line)
            except OSError as exc:
                self.close()
                raise NotRunning() from exc
            self._lines = self._sock.makefile("rb")
        else:
            try:
                self._proc = subprocess.Popen(relay,
                                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL)
                self._proc.stdin.write(line)
                self._proc.stdin.close()
            except OSError as exc:
                self.close()
                raise NotRunning() from exc
            self._lines = self._proc.stdout

    def __iter__(self):
        try:
            for line in self._lines:
                data = _parse(line)
                if data is not None:
                    yield data
        except OSError:
            return

    def not_running(self) -> bool:
        """After the lines ran out: did the relay find no Vertex?"""
        return self._proc is not None and self._proc.wait() == NOT_RUNNING_EXIT

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()       # flatpak-spawn passes it on to the relay
            try:
                self._proc.wait(2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()


Listener = Callable[[str, dict | None], None]


class Vertex:
    """The running Vertex, as the plugin's actions see it.

    `state` is the latest state (see `vertex.control.state`), or None while
    Vertex can't be reached. Listeners are called on a background thread with
    ("state", state-or-None) whenever it changes and ("notice", notice) for
    each notification. They are held weakly, so an action StreamController
    has thrown away stops getting calls.
    """

    def __init__(self, socket_path: str | None = None, relay: list[str] | bool | None = True):
        self.socket_path = socket_path or default_socket()
        # True: pick by whether we are in the Flatpak; a list: the relay's
        # command prefix; None: always the socket.
        if relay is True:
            relay = ["flatpak-spawn", "--host"] if in_flatpak() else None
        # The sandbox's runtime dir is the host's own path, so the relay is
        # told the same socket.
        self.relay = None if relay is None else \
            [*relay, "python3", "-c", RELAY, self.socket_path]
        self.prefer_socket = True     # use the socket when the sandbox can see it
        self.state: dict | None = None
        self._listeners: list[weakref.ref] = []
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._following: _Connection | None = None
        self._thread: threading.Thread | None = None

    def _relay_now(self) -> list[str] | None:
        """The relay, unless the socket's folder is in sight (given to the
        Flatpak); it is there whenever Vertex has run since login."""
        if self.relay is None or (self.prefer_socket and
                                  os.path.isdir(os.path.dirname(self.socket_path))):
            return None
        return self.relay

    # --- Requests -------------------------------------------------------------------

    def send(self, command: str, timeout: float = TIMEOUT, **args) -> dict:
        """Send one command and return the reply. Raises NotRunning."""
        connection = _Connection(_request(command, args), self.socket_path,
                                 self._relay_now(), timeout)
        timer = threading.Timer(timeout, connection.close)      # the relay has no timeout
        timer.start()
        try:
            for reply in connection:
                return reply
            if connection.not_running():
                raise NotRunning()
            return {"ok": False, "message": "Vertex sent no reply."}
        finally:
            timer.cancel()
            connection.close()

    def request(self, command: str, callback: Callable[[dict], None] | None = None,
                **args) -> None:
        """`send` on a thread of its own, so a key press never waits on Vertex.
        The callback gets the reply; when Vertex isn't running, a failed one."""
        def run():
            try:
                reply = self.send(command, **args)
            except NotRunning as exc:
                reply = {"ok": False, "error": "not_running", "message": str(exc)}
            if callback is not None:
                callback(reply)
        threading.Thread(target=run, daemon=True, name=f"vertex-{command}").start()

    # --- Following changes ---------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        ref = weakref.WeakMethod(listener) if hasattr(listener, "__self__") else \
            weakref.ref(listener)
        with self._lock:
            self._listeners.append(ref)

    def remove_listener(self, listener: Listener) -> None:
        with self._lock:
            self._listeners = [ref for ref in self._listeners
                               if ref() is not None and ref() != listener]

    def _emit(self, event: str, data: dict | None) -> None:
        with self._lock:
            self._listeners = [ref for ref in self._listeners if ref() is not None]
            listeners = [ref() for ref in self._listeners]
        for listener in listeners:
            if listener is None:
                continue
            try:
                listener(event, data)
            except Exception:     # one broken key must not stop the others
                pass

    def _set_state(self, state: dict | None) -> None:
        if state != self.state:
            self.state = state
            self._emit("state", state)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._follow, daemon=True,
                                            name="vertex-follow")
            self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        connection = self._following
        if connection is not None:
            connection.close()

    def _follow(self) -> None:
        while not self._stopping.is_set():
            try:
                self._following = _Connection(_request("subscribe", {}), self.socket_path,
                                              self._relay_now(), None)
            except NotRunning:
                self._following = None
            if self._following is not None:
                try:
                    for message in self._following:
                        # The first reply has no "event": it is the state too.
                        if message.get("event", "state") == "state":
                            self._set_state(message.get("data"))
                        elif message["event"] == "notice":
                            self._emit("notice", message.get("data"))
                finally:
                    self._following.close()
                    self._following = None
            self._set_state(None)
            self._stopping.wait(RETRY)


# --- Reading the state --------------------------------------------------------------

def sonar(state: dict | None) -> dict:
    return (state or {}).get("sonar") or {}


def channel(state: dict | None, channel_id: str) -> dict | None:
    return (sonar(state).get("channels") or {}).get(channel_id)


def device_name(device: dict | None) -> str:
    """What a key shows for a device: its description, as Vertex shows it."""
    if not device:
        return ""
    return device.get("description") or device.get("name") or ""
