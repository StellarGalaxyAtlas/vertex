"""Talking to OBS Studio over obs-websocket (protocol 5), with nothing but the
standard library.

OBS listens on a local port for WebSocket clients. This module does the
little of WebSocket that is needed (the handshake, text frames, ping and
close) and the obs-websocket handshake on top: Hello, Identify with the
password, Identified. After that every request gets its response, and events
arrive on a reader thread through a callback. No Qt here.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
import socket
import struct
import threading
from collections.abc import Callable

# obs-websocket's opcodes.
HELLO, IDENTIFY, IDENTIFIED, EVENT, REQUEST, REQUEST_RESPONSE = 0, 1, 2, 5, 6, 7

# The events Vertex listens to: General (OBS quitting) and Outputs (the
# replay buffer starting, stopping and saving).
EVENTS_GENERAL, EVENTS_OUTPUTS = 1 << 0, 1 << 6

# WebSocket's frame opcodes.
_CONTINUATION, _TEXT, _BINARY, _CLOSE, _PING, _PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# obs-websocket closes with this code when the password is wrong.
AUTH_FAILED = 4009


class ObsError(RuntimeError):
    """OBS refused a request, or the connection failed."""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


def auth_string(password: str, salt: str, challenge: str) -> str:
    """The answer to OBS's challenge, as obs-websocket defines it."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class _Socket:
    """A WebSocket client connection: text messages in and out."""

    def __init__(self, host: str, port: int, timeout: float):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._send_lock = threading.Lock()
        self._buffer = b""
        try:
            self._handshake(host, port)
        except BaseException:
            self.sock.close()
            raise

    def _handshake(self, host: str, port: int) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                   f"Sec-WebSocket-Version: 13\r\n"
                   f"Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n")
        self.sock.sendall(request.encode())
        while b"\r\n\r\n" not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ObsError("OBS closed the connection while connecting.")
            self._buffer += chunk
        head, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in f"{lines[0]} ":
            raise ObsError(f"OBS didn't accept the connection: {lines[0]}")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expected:
            raise ObsError("OBS answered the connection wrongly.")

    def _read(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("OBS closed the connection.")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _frame(self) -> tuple[bool, int, bytes]:
        first, second = self._read(2)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read(8))[0]
        mask = self._read(4) if second & 0x80 else b""
        payload = self._read(length)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return bool(first & 0x80), first & 0x0F, payload

    def send(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            head = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length < 1 << 16:
            head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self.sock.sendall(head + mask + masked)

    def receive(self) -> str:
        """The next text message. Raises ConnectionError when the connection
        closes, with OBS's close code as `code` when it gave one."""
        parts: list[bytes] = []
        while True:
            final, opcode, payload = self._frame()
            if opcode == _PING:
                self.send(_PONG, payload)
            elif opcode == _CLOSE:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1000
                reason = payload[2:].decode("utf-8", "replace")
                error = ConnectionError(reason or "OBS closed the connection.")
                error.code = code           # type: ignore[attr-defined]
                raise error
            elif opcode in (_TEXT, _BINARY, _CONTINUATION):
                parts.append(payload)
                if final:
                    return b"".join(parts).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.send(_CLOSE, struct.pack("!H", 1000))
        except OSError:
            pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class Client:
    """A connection to OBS: `request()` from any thread, events and the
    connection closing reported through the callbacks, on the reader thread."""

    def __init__(self, on_event: Callable[[str, dict], None] | None = None,
                 on_close: Callable[[str], None] | None = None):
        self.on_event = on_event
        self.on_close = on_close
        self._ws: _Socket | None = None
        self._ids = itertools.count(1)
        self._waiting: dict[str, list] = {}
        self._lock = threading.Lock()
        self._closing = False

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def connect(self, host: str, port: int, password: str = "", timeout: float = 5.0,
                events: int = EVENTS_GENERAL | EVENTS_OUTPUTS) -> None:
        try:
            ws = _Socket(host, port, timeout)
        except OSError as exc:
            raise ObsError(f"Couldn't reach OBS on port {port}: {exc}") from exc
        try:
            hello = json.loads(ws.receive())
            if hello.get("op") != HELLO:
                raise ObsError("OBS didn't greet the connection.")
            identify: dict = {"rpcVersion": 1, "eventSubscriptions": events}
            challenge = hello.get("d", {}).get("authentication")
            if challenge:
                if not password:
                    raise ObsError("OBS's WebSocket server wants a password.", AUTH_FAILED)
                identify["authentication"] = auth_string(
                    password, challenge["salt"], challenge["challenge"])
            ws.send(_TEXT, json.dumps({"op": IDENTIFY, "d": identify}).encode())
            try:
                reply = json.loads(ws.receive())
            except ConnectionError as exc:
                code = getattr(exc, "code", 0)
                if code == AUTH_FAILED:
                    raise ObsError("OBS's WebSocket password is wrong.", code) from exc
                raise ObsError(f"OBS refused the connection: {exc}", code) from exc
            if reply.get("op") != IDENTIFIED:
                raise ObsError("OBS didn't accept Vertex's connection.")
        except ObsError:
            ws.close()
            raise
        except (OSError, ValueError, KeyError) as exc:
            ws.close()
            raise ObsError(f"Couldn't talk to OBS: {exc}") from exc
        ws.sock.settimeout(None)
        self._ws, self._closing = ws, False
        threading.Thread(target=self._reader, args=(ws,), daemon=True,
                         name="obs-websocket").start()

    def request(self, kind: str, data: dict | None = None, timeout: float = 15.0) -> dict:
        """Send one request and wait for its answer: the response's data, or
        ObsError with OBS's reason."""
        ws = self._ws
        if ws is None:
            raise ObsError("Not connected to OBS.")
        request_id = str(next(self._ids))
        done = threading.Event()
        slot: list = [done, None]
        with self._lock:
            self._waiting[request_id] = slot
        message = {"op": REQUEST, "d": {"requestType": kind, "requestId": request_id,
                                        "requestData": data or {}}}
        try:
            ws.send(_TEXT, json.dumps(message).encode())
        except OSError as exc:
            with self._lock:
                self._waiting.pop(request_id, None)
            raise ObsError(f"Lost the connection to OBS: {exc}") from exc
        if not done.wait(timeout):
            with self._lock:
                self._waiting.pop(request_id, None)
            raise ObsError(f"OBS didn't answer {kind}.")
        answer = slot[1]
        if answer is None:
            raise ObsError("Lost the connection to OBS.")
        status = answer.get("requestStatus", {})
        if not status.get("result"):
            reason = status.get("comment") or f"code {status.get('code')}"
            raise ObsError(f"OBS refused {kind}: {reason}", int(status.get("code") or 0))
        return answer.get("responseData") or {}

    def close(self) -> None:
        ws, self._ws = self._ws, None
        self._closing = True
        if ws is not None:
            ws.close()

    def _reader(self, ws: _Socket) -> None:
        reason = ""
        try:
            while True:
                message = json.loads(ws.receive())
                op, body = message.get("op"), message.get("d") or {}
                if op == REQUEST_RESPONSE:
                    with self._lock:
                        slot = self._waiting.pop(str(body.get("requestId")), None)
                    if slot is not None:
                        slot[1] = body
                        slot[0].set()
                elif op == EVENT and self.on_event is not None:
                    self.on_event(body.get("eventType", ""), body.get("eventData") or {})
        except (OSError, ValueError, ConnectionError) as exc:
            reason = str(exc) or "OBS closed the connection."
        finally:
            with self._lock:
                waiting, self._waiting = list(self._waiting.values()), {}
            for slot in waiting:
                slot[0].set()
            closing = self._closing or self._ws is not ws
            if self._ws is ws:
                self._ws = None
            if not closing and self.on_close is not None:
                self.on_close(reason)
