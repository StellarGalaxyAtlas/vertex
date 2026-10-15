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


class _Dial:
    Events = _Events


class _ActionBase:
    def __init__(self, plugin_base=None, settings=None):
        self.plugin_base = plugin_base
        self.action_id = "test"
        self._settings = dict(settings or {})
        self.labels = {}
        self.errors = 0
        self.media = []

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

    def set_background_color(self, color):
        self.background = color

    def set_media(self, media_path=None, **_kwargs):
        self.media.append(media_path)

    def event_callback(self, event, data=None):
        if event == _Events.DOWN:
            self.on_key_down()

    def on_key_down(self):
        pass


class _PluginBase:
    def __init__(self):
        self.holders = []

    def add_action_holder(self, holder):
        self.holders.append(holder)

    def register(self, **kwargs):
        self.registered = kwargs


def _stub_streamcontroller(monkeypatch):
    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    gi = module("gi", require_version=lambda *_: None)
    gi.repository = module("gi.repository", Adw=types.SimpleNamespace(),
                           Gio=types.SimpleNamespace(), Gtk=types.SimpleNamespace())
    module("GtkHelper")
    module("GtkHelper.FileDialogRow", FileDialogRow=object,
           FileDialogFilter=lambda name, patterns: (name, patterns))
    module("loguru", logger=types.SimpleNamespace(debug=print, info=print))
    module("src.backend.PluginManager.ActionBase", ActionBase=_ActionBase)
    module("src.backend.DeckManagement.InputIdentifier",
           Input=types.SimpleNamespace(Key="Key", Touchscreen="Touchscreen", Dial=_Dial))
    module("src.backend.PluginManager.ActionHolder",
           ActionHolder=lambda **kwargs: types.SimpleNamespace(**kwargs))
    module("src.backend.PluginManager.ActionInputSupport",
           ActionInputSupport=types.SimpleNamespace(SUPPORTED=2, UNSUPPORTED=0))
    module("src.backend.PluginManager.PluginBase", PluginBase=_PluginBase)
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
    main = importlib.import_module(PACKAGE + ".main")
    return types.SimpleNamespace(keys=keys, client=client, main=main)


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
        if command == "devices":
            return {"ok": True, "message": "", "data": {"outputs": [], "mics": [
                {"name": "desk_mic", "description": "Desk mic", "connected": True,
                 "excluded": False},
                {"name": "old_mic", "description": "Old mic", "connected": False,
                 "excluded": False}]}}
        if command == "device" and args.get("name") == "gone":
            return {"ok": False, "error": "no_device", "message": "gone isn't plugged in."}
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
    client.prefer_socket = False
    assert client.send("save-clip", seconds=30) == {"ok": True, "message": "did save-clip"}
    assert vertex.received == [("save-clip", {"seconds": 30})]


@pytest.mark.parametrize("relay", [None, []])
def test_not_running(plugin, tmp_path, relay):
    client = plugin.client.Vertex(str(tmp_path / "missing.sock"), relay=relay)
    client.prefer_socket = False
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
    client.prefer_socket = False
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


def test_socket_is_used_once_the_sandbox_can_see_it(plugin, vertex, tmp_path):
    client = plugin.client.Vertex(vertex.sock, relay=["/nonexistent/flatpak-spawn"])
    assert client.send("show")["ok"]                   # the folder is there: no relay
    hidden = plugin.client.Vertex(str(tmp_path / "hidden" / "control.sock"),
                                  relay=["/nonexistent/flatpak-spawn"])
    assert hidden._relay_now() == hidden.relay


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


def test_the_keys_names_and_ids(plugin, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))      # no Vertex to find
    registered = plugin.main.VertexPlugin()
    registered.vertex.stop()
    names = {holder.action_id_suffix: holder.action_name for holder in registered.holders}
    # Ids stay as first published, so keys already set up keep working.
    assert names == {
        "Volume": "Sonar Information", "VolumeStep": "Sonar Volume",
        "Mute": "Sonar Toggle Channel Mute", "NextMic": "Sonar Next Microphone",
        "NextOutput": "Sonar Next Output Device", "MicToggle": "Sonar Toggle Microphone",
        "OutputToggle": "Sonar Toggle Output Device", "Replay": "Replay Buffer Toggle",
        "SaveClip": "Replay Save Clip", "Show": "Show Vertex"}


def test_information_key(plugin, vertex):
    key, _client = _key(plugin, vertex, plugin.keys.SonarInformation, channel="game")
    key.show(_state(volume=55))
    assert key.labels == {"top": "Game", "center": "", "bottom": "55%"}
    key.show(_state(muted=True))
    assert key.labels["bottom"] == "Muted"
    key.show(_state(active=False))
    assert key.labels["bottom"] == "Sonar off"
    key.show(None)
    assert key.labels["bottom"] == "Vertex off"
    key.on_key_down()                                   # only shows
    threading.Event().wait(0.2)
    assert vertex.received == []


def test_volume_key_steps_by_its_setting(plugin, vertex):
    down, _ = _key(plugin, vertex, plugin.keys.SonarVolume, channel="game",
                   direction="down", step=10)
    down.show(_state(volume=55))
    assert down.labels == {"top": "Game", "center": "-10%", "bottom": "55%"}
    down.on_key_down()
    assert _wait(lambda: vertex.received == [
        ("volume", {"channel": "game", "action": "down", "step": 10})])
    up, _ = _key(plugin, vertex, plugin.keys.SonarVolume)       # the defaults
    up.show(_state(volume=55))
    assert up.labels["center"] == "+5%"
    up.on_key_down()
    assert _wait(lambda: len(vertex.received) == 2)
    assert vertex.received[1] == ("volume", {"channel": "game", "action": "up", "step": 5})


def test_volume_key_on_a_dial(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.keys.SonarVolume, channel="chat", step=2)
    key.event_callback(_Events.TURN_CCW)
    assert _wait(lambda: vertex.received == [
        ("volume", {"channel": "chat", "action": "down", "step": 2})])
    key.event_callback(_Events.DOWN)
    assert _wait(lambda: vertex.received[-1] == ("mute", {"channel": "chat"}))


def test_next_device_keys(plugin, vertex):
    output, _ = _key(plugin, vertex, plugin.keys.SonarNextOutput)
    mic, _ = _key(plugin, vertex, plugin.keys.SonarNextMic)
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
    key, _ = _key(plugin, vertex, plugin.keys.ReplaySaveClip, seconds=30)
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


def test_mic_toggle_faces(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.keys.SonarToggleMic, first="desk_mic",
                  second="headset_mic")
    key.show(_state(mic="Desk mic"))
    assert key.labels == {"top": "Mic 1", "center": "", "bottom": "Desk mic"}
    key.show(_state(mic="Headset mic"))
    assert key.labels == {"top": "Mic 2", "center": "", "bottom": "Headset mic"}
    key.show(_state(mic="Webcam"))                      # neither: the neutral face
    assert key.labels == {"top": "Mic", "center": "No mic", "bottom": "Webcam"}
    key.show(_state(active=False))
    assert key.labels["center"] == "Sonar off"
    key.show(None)
    assert key.labels["center"] == "Vertex off"


def _pressed(plugin, vertex, current, **picks):
    key, client = _key(plugin, vertex, plugin.keys.SonarToggleMic, **picks)
    client.state = _state(mic=current)
    key.on_key_down()
    return key


def test_mic_toggle_switches_to_the_other_pick(plugin, vertex):
    _pressed(plugin, vertex, "Desk mic", first="desk_mic", second="headset_mic")
    assert _wait(lambda: vertex.received == [
        ("device", {"action": "set", "name": "headset_mic", "channel": "mic"})])


def test_mic_toggle_from_neither_goes_to_the_first_plugged_in(plugin, vertex):
    key = _pressed(plugin, vertex, "Webcam", first="gone", second="desk_mic")
    assert _wait(lambda: [args["name"] for _c, args in vertex.received] == ["gone", "desk_mic"])
    threading.Event().wait(0.1)
    assert key.errors == 0


def test_mic_toggle_shows_an_error_when_the_other_is_unplugged(plugin, vertex):
    key = _pressed(plugin, vertex, "Desk mic", first="desk_mic", second="gone")
    assert _wait(lambda: key.errors == 1)


def test_mic_toggle_lists_sonars_mics(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.keys.SonarToggleMic, first="usb_mic")
    choices, note = key._choices()
    assert choices == [("", "None"), ("desk_mic", "Desk mic"),
                       ("old_mic", "Old mic (not plugged in)"), ("usb_mic", "usb_mic")]
    assert note == ""


def test_output_toggle(plugin, vertex):
    key, client = _key(plugin, vertex, plugin.keys.SonarToggleOutput, first="headset",
                       second="speakers")
    key.show(_state())
    assert key.labels == {"top": "Output 1", "center": "", "bottom": "Headset"}
    client.state = _state()
    key.on_key_down()
    assert _wait(lambda: vertex.received == [("device", {"action": "set",
                                                         "name": "speakers"})])


def test_mute_and_replay_keys(plugin, vertex):
    mute, _ = _key(plugin, vertex, plugin.keys.SonarToggleChannelMute, channel="game")
    mute.show(_state(muted=True))
    assert mute.labels == {"top": "Game", "center": "Muted", "bottom": ""}
    mute.show(_state())
    assert mute.labels["center"] == "On"
    replay, _ = _key(plugin, vertex, plugin.keys.ReplayToggle)
    replay.show(_state(replay=False))
    assert replay.labels["center"] == "Off"
    replay.show(_state())
    assert replay.labels["center"] == "On"
    mute.on_key_down()
    replay.on_key_down()
    assert _wait(lambda: len(vertex.received) == 2)
    assert ("replay", {"action": "toggle"}) in vertex.received
    assert ("mute", {"channel": "game"}) in vertex.received


def test_save_clip_key_flashes_when_a_clip_lands(plugin, vertex, monkeypatch):
    monkeypatch.setattr(plugin.keys, "FLASH_SECONDS", 0.05)
    key, _ = _key(plugin, vertex, plugin.keys.ReplaySaveClip)
    key.on_notice({"kind": "clip_saved"})
    assert key.background == list(plugin.keys.FLASH)
    assert _wait(lambda: key.background == [0, 0, 0, 0])
    key.on_notice({"kind": "clip_not_saved"})
    assert key.errors == 1


def test_toggle_shows_the_picture_picked_for_each_face(plugin, vertex, tmp_path):
    first, second = tmp_path / "desk.png", tmp_path / "headset.png"
    first.write_bytes(b"png")
    second.write_bytes(b"png")
    key, _ = _key(plugin, vertex, plugin.keys.SonarToggleMic, first="desk_mic",
                  second="headset_mic",
                  images={"mic-1": str(first), "mic-2": str(second)})
    key.show(_state(mic="Desk mic"))
    key.show(_state(mic="Desk mic"))                    # unchanged: not drawn again
    key.show(_state(mic="Headset mic"))
    key.show(_state(mic="Webcam"))                      # no picture for "No mic"
    assert key.media == [str(first), str(second), None]
    key.show(_state(mic="Webcam"))
    assert len(key.media) == 3


def test_keys_without_pictures_keep_their_image(plugin, vertex):
    key, _ = _key(plugin, vertex, plugin.keys.SonarToggleMic, first="desk_mic")
    key.show(_state(mic="Desk mic"))
    key.show(_state(mic="Webcam"))
    assert key.media == []


def test_picking_and_unpicking_a_picture(plugin, vertex, tmp_path):
    picture = tmp_path / "muted.png"
    picture.write_bytes(b"png")
    key, client = _key(plugin, vertex, plugin.keys.SonarToggleChannelMute, channel="game")
    client.state = _state()
    key.show(client.state)
    key.set_image("unmuted", str(picture))
    assert key.get_settings()["images"] == {"unmuted": str(picture)}
    key.set_image("unmuted", "")
    assert key.get_settings()["images"] == {}
    assert key.media == [str(picture), None]
