"""A stand-in OBS Studio for the tests: obs-websocket 5 on a local port, with
just enough of OBS behind it (profiles, scene collections, inputs, the replay
buffer) to check what Vertex sets up and how it reacts."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import socket
import socketserver
import struct
import threading

from vertex.recorder.obsws import auth_string

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FakeObs:
    def __init__(self, password: str = "secret", replay_file: str = ""):
        self.password = password
        self.replay_file = replay_file      # what a save "records"
        self.profiles = ["Untitled"]
        self.profile = "Untitled"
        self.params: dict[tuple[str, str, str], str] = {}
        self.switches: list[str] = []
        self.collections = ["Untitled"]
        self.collection = "Untitled"
        self.inputs: dict[str, dict] = {}       # name -> {"kind", "settings", "tracks"}
        self.special = {"desktop1": "Desktop Audio", "desktop2": None, "mic1": "Mic/Aux",
                        "mic2": None, "mic3": None, "mic4": None}
        for name in ("Desktop Audio", "Mic/Aux"):
            self.inputs[name] = {"kind": "wasapi_output_capture", "settings": {},
                                 "tracks": {str(n): True for n in range(1, 7)}}
        self.video: dict = {}
        self.transforms: dict = {}
        self.replay_active = False
        self.start_fails = False
        self.monitor_items = [
            {"itemName": "Generic: 1920x1080 @ 0,0 (Primary Monitor)", "itemEnabled": True,
             "itemValue": "mon-1"},
            {"itemName": "DELL: 2560x1440 @ 1920,0", "itemEnabled": True,
             "itemValue": "mon-2"}]
        self.requests: list[str] = []
        self.clients: list[socket.socket] = []
        self.save_dir = ""
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                fake._serve(self.request)

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        for client in self.clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.server.shutdown()
        self.server.server_close()

    # --- WebSocket ------------------------------------------------------------

    @staticmethod
    def _send(sock, payload: dict) -> None:
        data = json.dumps(payload).encode()
        if len(data) < 126:
            head = struct.pack("!BB", 0x81, len(data))
        else:
            head = struct.pack("!BBH", 0x81, 126, len(data))
        sock.sendall(head + data)

    @staticmethod
    def _recv(stream) -> tuple[int, bytes]:
        first, second = stream.read(2)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", stream.read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", stream.read(8))[0]
        mask = stream.read(4)
        data = stream.read(length)
        return first & 0x0F, bytes(b ^ mask[i % 4] for i, b in enumerate(data))

    def _serve(self, sock) -> None:
        stream = sock.makefile("rb")
        head = b""
        while not head.endswith(b"\r\n\r\n"):
            head += stream.read(1)
        key = next(line.split(":", 1)[1].strip() for line in head.decode().split("\r\n")
                   if line.lower().startswith("sec-websocket-key"))
        accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        hello = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {"challenge": "chal", "salt": "salt"}
        self._send(sock, {"op": 0, "d": hello})
        try:
            _op, data = self._recv(stream)
            identify = json.loads(data)["d"]
            if self.password and identify.get("authentication") != auth_string(
                    self.password, "salt", "chal"):
                sock.sendall(struct.pack("!BBH", 0x88, 2, 4009))
                return
            self._send(sock, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
            self.clients.append(sock)
            while True:
                op, data = self._recv(stream)
                if op == 0x8:
                    return
                body = json.loads(data)["d"]
                result, response = self.handle(body["requestType"], body.get("requestData", {}),
                                               sock)
                status = {"result": result is None, "code": 100 if result is None else 600}
                if result is not None:
                    status["comment"] = result
                self._send(sock, {"op": 7, "d": {"requestType": body["requestType"],
                                                 "requestId": body["requestId"],
                                                 "requestStatus": status,
                                                 "responseData": response}})
        except (OSError, ValueError, struct.error):
            return

    def event(self, kind: str, data: dict) -> None:
        for sock in list(self.clients):
            try:
                self._send(sock, {"op": 5, "d": {"eventType": kind, "eventData": data}})
            except OSError:
                pass

    # --- OBS ------------------------------------------------------------------

    def handle(self, kind: str, data: dict, _sock) -> tuple[str | None, dict]:
        self.requests.append(kind)
        if kind == "GetProfileList":
            return None, {"currentProfileName": self.profile, "profiles": list(self.profiles)}
        if kind == "CreateProfile":
            self.profiles.append(data["profileName"])
            self.profile = data["profileName"]
            self.switches.append(self.profile)
            return None, {}
        if kind == "SetCurrentProfile":
            self.profile = data["profileName"]
            self.switches.append(self.profile)
            return None, {}
        if kind == "GetProfileParameter":
            key = (self.profile, data["parameterCategory"], data["parameterName"])
            return None, {"parameterValue": self.params.get(key)}
        if kind == "SetProfileParameter":
            key = (self.profile, data["parameterCategory"], data["parameterName"])
            self.params[key] = data["parameterValue"]
            if data["parameterName"] == "FilePath":
                self.save_dir = data["parameterValue"]
            return None, {}
        if kind == "SetVideoSettings":
            self.video = dict(data)
            return None, {}
        if kind == "GetSceneCollectionList":
            return None, {"currentSceneCollectionName": self.collection,
                          "sceneCollections": list(self.collections)}
        if kind == "CreateSceneCollection":
            self.collections.append(data["sceneCollectionName"])
            self.collection = data["sceneCollectionName"]
            return None, {}
        if kind == "SetCurrentSceneCollection":
            self.collection = data["sceneCollectionName"]
            return None, {}
        if kind == "GetCurrentProgramScene":
            return None, {"currentProgramSceneName": "Scene", "sceneName": "Scene"}
        if kind == "GetInputList":
            return None, {"inputs": [{"inputName": name, "inputKind": item["kind"]}
                                     for name, item in self.inputs.items()]}
        if kind == "CreateInput":
            self.inputs[data["inputName"]] = {"kind": data["inputKind"],
                                              "settings": dict(data["inputSettings"]),
                                              "tracks": {str(n): True for n in range(1, 7)}}
            return None, {"sceneItemId": len(self.inputs)}
        if kind == "SetInputSettings":
            self.inputs[data["inputName"]]["settings"].update(data["inputSettings"])
            return None, {}
        if kind == "RemoveInput":
            del self.inputs[data["inputName"]]
            return None, {}
        if kind == "GetInputPropertiesListPropertyItems":
            return None, {"propertyItems": self.monitor_items}
        if kind == "GetSceneItemId":
            return None, {"sceneItemId": 1}
        if kind == "SetSceneItemTransform":
            self.transforms = data["sceneItemTransform"]
            return None, {}
        if kind == "SetInputAudioTracks":
            self.inputs[data["inputName"]]["tracks"] = dict(data["inputAudioTracks"])
            return None, {}
        if kind == "SetInputMute":
            return None, {}
        if kind == "GetSpecialInputs":
            return None, dict(self.special)
        if kind == "GetReplayBufferStatus":
            return None, {"outputActive": self.replay_active}
        if kind == "StartReplayBuffer":
            self.replay_active = not self.start_fails
            return None, {}
        if kind == "StopReplayBuffer":
            if not self.replay_active:
                return "Replay buffer is not active.", {}
            self.replay_active = False
            return None, {}
        if kind == "SaveReplayBuffer":
            if not self.replay_active:
                return "Replay buffer is not active.", {}
            raw = f"{self.save_dir}/Replay 2026-10-20 10-00-00.mp4"
            shutil.copy(self.replay_file, raw)
            threading.Timer(0.05, self.event, ("ReplayBufferSaved",
                                               {"savedReplayPath": raw})).start()
            return None, {}
        return f"{kind} isn't faked", {}
