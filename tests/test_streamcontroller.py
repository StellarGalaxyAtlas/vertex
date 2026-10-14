"""The StreamController plugin: its client against a real control socket,
and its keys with StreamController itself stubbed out."""

import importlib
import sys
import threading
import types
from pathlib import Path

import pytest

from vertex import ipc

PLUGIN = Path(__file__).resolve().parents[1] / "streamcontroller"
PACKAGE = "plugins.com_stellargalaxyatlas_Vertex"


def _wait(condition, seconds=5.0):
    for _ in range(int(seconds / 0.02)):
        if condition():
            return True
        threading.Event().wait(0.02)
    return condition()


# --- StreamController, stubbed -----------------------------------------------------

class _Events:
    DOWN, UP, TURN_CW, TURN_CCW = "Down", "Up", "Turn CW", "Turn CCW"


class _ActionBase:
    def __init__(self, plugin_base=None, settings=None):
        self.plugin_base = plugin_base
        self.action_id = "test"
        self._settings = dict(settings or {})
        self.labels = {}
        self.errors = 0

    def get_settings(self):
        return dict(self._settings)

    def set_settings(self, settings):
        self._settings = dict(settings)

    def set_top_label(self, text):
        self.labels["top"] = text

    def set_center_label(self, text):
        self.labels["center"] = text

    def set_bottom_label(self, text):
        self.labels["bottom"] = text

    def show_error(self, duration=-1):
        self.errors += 1

    def event_callback(self, event, data=None):
        if event == _Events.DOWN:
            self.on_key_down()


def _stub_streamcontroller(monkeypatch):
    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    gi = module("gi", require_version=lambda *_: None)
    gi.repository = module("gi.repository", Adw=types.SimpleNamespace(),
                           Gtk=types.SimpleNamespace())
    module("loguru", logger=types.SimpleNamespace(debug=print, info=print))
    module("src.backend.PluginManager.ActionBase", ActionBase=_ActionBase)
    module("src.backend.DeckManagement.InputIdentifier",
           Input=types.SimpleNamespace(Dial=types.SimpleNamespace(Events=_Events)))
    plugins = module("plugins")
    plugins.__path__ = []
    package = module(PACKAGE)
    package.__path__ = [str(PLUGIN)]


@pytest.fixture
def plugin(monkeypatch):
    _stub_streamcontroller(monkeypatch)
    for name in [n for n in sys.modules if n.startswith(PACKAGE + ".")]:
        monkeypatch.delitem(sys.modules, name)
    keys = importlib.import_module(PACKAGE + ".actions.keys")
    client = importlib.import_module(PACKAGE + ".vertex_client")
    return types.SimpleNamespace(keys=keys, client=client)


# --- A Vertex that answers ----------------------------------------------------------

def _state(volume=55, muted=False, mic="Headset mic", active=True, replay=True):
    def device(description):
        return {"name": description.lower().replace(" ", "_"), "description": description}
    return {"api": 1,
            "replay": {"state": "running" if replay else "stopped", "running": replay,
                       "seconds": 60},
            "sonar": {"enabled": active, "active": active, "linked": True,
                      "output": device("Headset") if active else None,
                      "mic": device(mic) if active else None,
                      "channels": {"game": {"name": "Game", "volume": volume, "muted": muted,
                                            "device": None}}}}


@pytest.fixture
def vertex(tmp_path):
    sock = tmp_path / "control.sock"
    subscribers = ipc.Subscribers()
    received = []
    box = {"state": _state()}

    def dispatch(command, args):
        received.append((command, args))
        if command == "state":
            return {"ok": True, "message": "", "data": box["state"]}
        return {"ok": command != "fail", "message": f"did {command}"}

    server = ipc.ControlServer(dispatch, sock, subscribers=subscribers)
    assert server.start()

    def publish(state):
        box["state"] = state
        subscribers.publish({"event": "state", "data": state})

    yield types.SimpleNamespace(sock=str(sock), server=server, received=received,
                                subscribers=subscribers, publish=publish)
    server.stop()


# --- The client ---------------------------------------------------------------------

@pytest.mark.parametrize("relay", [None, []])
def test_send_over_socket_and_relay(plugin, vertex, relay):
    client = plugin.client.Vertex(vertex.sock, relay=relay)
    assert client.send("save-clip", seconds=30) == {"ok": True, "message": "did save-clip"}
    assert vertex.received == [("save-clip", {"seconds": 30})]


@pytest.mark.parametrize("relay", [None, []])
def test_not_running(plugin, tmp_path, relay):
    client = plugin.client.Vertex(str(tmp_path / "missing.sock"), relay=relay)
    with pytest.raises(plugin.client.NotRunning):
        client.send("show")
    replies = []
    client.request("show", replies.append)
    assert _wait(lambda: replies)
    assert replies[0]["ok"] is False and replies[0]["error"] == "not_running"


@pytest.mark.parametrize("relay", [None, []])
def test_follow_state_changes_and_vertex_stopping(plugin, vertex, relay, monkeypatch):
    monkeypatch.setattr(plugin.client, "RETRY", 0.1)
    client = plugin.client.Vertex(vertex.sock, relay=relay)
    seen = []
    listener = lambda event, data: seen.append((event, data))  # noqa: E731
    client.add_listener(listener)
    client.start()
    try:
        assert _wait(lambda: client.state == _state())
        assert _wait(lambda: len(vertex.subscribers))
        vertex.publish(_state(volume=20))
        assert _wait(lambda: client.state == _state(volume=20))
        vertex.subscribers.publish({"event": "notice", "data": {"kind": "clip_saved"}})
        assert _wait(lambda: ("notice", {"kind": "clip_saved"}) in seen)
        vertex.server.stop()
        assert _wait(lambda: client.state is None)
        assert seen[-1] == ("state", None)
    finally:
        client.stop()


def test_listeners_are_held_weakly(plugin):
    client = plugin.client.Vertex("unused", relay=None)

    class Key:
        calls = 0

        def heard(self, event, data):
            Key.calls += 1

    key = Key()
    client.add_listener(key.heard)
    client._set_state({"a": 1})
    del key
    client._set_state({"a": 2})
    assert Key.calls == 1


# --- The keys -----------------------------------------------------------------------

class _Plugin:
    def __init__(self, client):
        self.vertex = client


def _key(plugin, vertex, cls, **settings):
    client = plugin.client.Vertex(vertex.sock, relay=None)
    key = cls(_Plugin(client), settings)
    return key, client


def test_volume_key(plugin, vertex):
    key, _client = _key(plugin, vertex, plugin.keys.Volume, channel="game", press="mute")
    key.show(_state(volume=55))
    assert key.labels == {"top": "Game", "center": "55%"}
    key.show(_state(muted=True))
    assert key.labels["center"] == "Muted"
    key.show(_state(active=False))
    assert key.labels["center"] == "Sonar off"
    key.show(None)
    assert key.labels["center"] == "Vertex off"
    key.on_key_down()
    key.event_callback(_Events.TURN_CW)
    assert _wait(lambda: len(vertex.received) == 2)
    assert sorted(vertex.received, key=str) == sorted(
        [("mute", {"channel": "game"}), ("volume", {"channel": "game", "action": "up",
                                                    "step": 5})], key=str)


def test_volume_key_press_does_nothing_by_default(plugin, vertex):
    key, _client = _key(plugin, vertex, plugin.keys.Volume)
    key.on_key_down()
    threading.Event().wait(0.2)
    assert vertex.received == []


def test_next_device_keys(plugin, vertex):
    output, _ = _key(plugin, vertex, plugin.keys.NextOutput)
    mic, _ = _key(plugin, vertex, plugin.keys.NextMic)
    output.show(_state())
    mic.show(_state(mic="Desk mic"))
    assert output.labels == {"top": "Output", "bottom": "Headset"}
    assert mic.labels == {"top": "Mic", "bottom": "Desk mic"}
    output.on_key_down()
    mic.on_key_down()
    assert _wait(lambda: len(vertex.received) == 2)
    assert {("device", "channel" in args) for _c, args in vertex.received} == \
        {("device", True), ("device", False)}


def test_save_clip_key(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.keys.SaveClip, seconds=30)
    key.show(_state())
    assert key.labels["bottom"] == "30 s"
    key.show(_state(replay=False))
    assert key.labels["bottom"] == "Replay off"
    key.on_key_down()
    assert _wait(lambda: vertex.received == [("save-clip", {"seconds": 30})])


def test_failed_command_shows_an_error(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.keys.ShowVertex)
    key.send("fail")
    assert _wait(lambda: key.errors == 1)
