"""OBS Studio as the recorder on Windows: the WebSocket client, what Vertex
sets up in OBS, and the replay buffer run against a stand-in OBS."""

import json
import os
import time

import pytest

from fake_obs import FakeObs
from vertex import platform
from vertex.config import Config, RecorderConfig
from vertex.media import probe
from vertex.platform import windows
from vertex.recorder import backend, gsr, obs
from vertex.recorder.obs_replay import ObsRecorder, finish
from vertex.recorder.obsws import AUTH_FAILED, Client, ObsError
from vertex.recorder.replay import State


def wait_for(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


@pytest.fixture(autouse=True)
def no_sonar(monkeypatch):
    """OBS records where there is no Sonar, so the tracks' defaults are the
    system's own devices."""
    monkeypatch.setattr(platform.here(), "SONAR", False)


@pytest.fixture
def fake():
    server = FakeObs()
    yield server
    server.close()


@pytest.fixture
def connected(fake, monkeypatch):
    """OBS running, with its WebSocket server on and the fake's password."""
    monkeypatch.setattr(obs, "running", lambda: True)
    monkeypatch.setattr(obs, "websocket_settings", lambda: obs.WebSocketSettings(
        True, fake.port, fake.password, True, True))
    monkeypatch.setattr(obs, "monitor_rects", lambda: [
        obs.MonitorRect("\\\\.\\DISPLAY1", 0, 0, 1920, 1080),
        obs.MonitorRect("\\\\.\\DISPLAY2", 1920, 0, 2560, 1440)])
    return fake


def a_plan(tmp_path, capture="\\\\.\\DISPLAY2", **settings):
    rec = RecorderConfig(capture=capture, game_audio="default_output",
                         chat_audio="device:{0.0.0.00000000}.{chat-guid}",
                         mic_audio="device:{0.0.1.00000000}.{mic-guid}", **settings)
    config = Config()
    config.recorder = rec
    return obs.plan(rec, gsr.audio_tracks(config), str(tmp_path / "obs"), (2560, 1440),
                    (1920, 1080), "nvidia", 200 << 20)


class TestClient:
    def test_the_password_answers_obs_challenge(self, fake):
        client = Client()
        client.connect("127.0.0.1", fake.port, "secret")
        assert client.request("GetProfileList")["profiles"] == ["Untitled"]
        with pytest.raises(ObsError, match="isn't faked"):
            client.request("Nonsense")
        client.close()

    def test_a_wrong_password_says_so(self, fake):
        with pytest.raises(ObsError) as caught:
            Client().connect("127.0.0.1", fake.port, "wrong")
        assert caught.value.code == AUTH_FAILED and "password" in str(caught.value)

    def test_nothing_listening(self):
        with pytest.raises(ObsError, match="Couldn't reach OBS"):
            Client().connect("127.0.0.1", 9, "x", timeout=1)


class TestSetup:
    def test_tracks_record_the_devices_picked(self, tmp_path):
        setup = a_plan(tmp_path)
        assert [(a.name, a.kind, a.device, a.track) for a in setup.inputs] == [
            ("Vertex Game", "wasapi_output_capture", "default", 1),
            ("Vertex Chat", "wasapi_output_capture", "{0.0.0.00000000}.{chat-guid}", 2),
            ("Vertex Mic", "wasapi_input_capture", "{0.0.1.00000000}.{mic-guid}", 3)]
        assert setup.titles == {0: "Vertex Game", 1: "Vertex Chat", 2: "Vertex Mic"}
        values = {key: value for _section, key, value in setup.profile}
        assert values["RecTracks"] == "7" and values["RecRB"] == "true"
        assert values["RecEncoder"] == "nvenc" and values["RecQuality"] == "Small"
        assert values["FilePath"] == str(tmp_path / "obs")
        assert "Track 2: Vertex Chat" in obs.describe(setup)

    def test_encoders(self):
        assert obs.encoder(RecorderConfig(video_codec="hevc"), "amd") == "amd_hevc"
        assert obs.encoder(RecorderConfig(video_codec="av1"), "intel") == "qsv_av1"
        assert obs.encoder(RecorderConfig(encoder="cpu"), "nvidia") == "x264"
        assert obs.encoder(RecorderConfig(), "") == "x264"
        assert obs.vendor_of(["Microsoft Basic Display", "AMD Radeon RX 7800 XT"]) == "amd"

    def test_what_obs_cant_record(self):
        assert obs.validate(RecorderConfig()) == []
        assert obs.validate(RecorderConfig(video_codec="vp9"))
        assert obs.validate(RecorderConfig(encoder="cpu", video_codec="hevc"))
        assert obs.validate(RecorderConfig(chat_audio="app:Discord"))
        assert obs.validate(RecorderConfig(replay_seconds=99999))

    def test_the_monitor_is_found_in_obs_list(self):
        items = [{"itemName": "A: 1920x1080 @ 0,0 (Primary Monitor)", "itemValue": "a"},
                 {"itemName": "B: 2560x1440 @ -2560,0", "itemValue": "b"}]
        left = obs.MonitorRect("\\\\.\\DISPLAY2", -2560, 0, 2560, 1440)
        assert obs.pick_monitor(items, left, (2560, 1440)) == "b"
        assert obs.pick_monitor(items, None, (2560, 1440)) == "b"
        assert obs.pick_monitor(items, None, (800, 600)) == "a"
        assert obs.pick_monitor([], None, (800, 600)) == ""

    def test_devices_are_sorted_into_outputs_and_inputs(self):
        assert obs.is_output("{0.0.0.00000000}.{guid}") and obs.is_output("default_output")
        assert not obs.is_output("{0.0.1.00000000}.{guid}")
        assert obs.list_audio_devices()[:2] == [("default_output", "Default output"),
                                                ("default_input", "Default input")]

    def test_the_websocket_server_is_switched_on(self):
        assert not obs.websocket_settings().found
        settings = obs.enable_websocket()
        assert settings.enabled and settings.found and settings.password
        assert settings.port == obs.DEFAULT_PORT
        with open(obs.websocket_file(), encoding="utf-8") as handle:
            assert json.load(handle)["first_load"] is False
        # One already set up keeps its password and port.
        with open(obs.websocket_file(), "w", encoding="utf-8") as handle:
            json.dump({"server_enabled": False, "server_port": 4460,
                       "server_password": "kept", "auth_required": True}, handle)
        again = obs.enable_websocket()
        assert again.enabled and (again.port, again.password) == (4460, "kept")

    def test_obs_is_the_recorder_on_windows(self, monkeypatch, tmp_path):
        monkeypatch.setattr(platform, "WINDOWS", True)
        monkeypatch.setattr(obs, "gpu_vendor", lambda: "nvidia")
        assert backend.name() == "OBS Studio" and not backend.has_notifier()
        assert isinstance(backend.recorder(), ObsRecorder)
        config = Config()
        config.recorder.command = ""
        plan = backend.launch_plan(config, [], gsr.audio_tracks(config))
        assert isinstance(plan, obs.Plan) and plan.output == (1920, 1080)
        assert plan.save_dir == os.path.join(config.resolved_cache_dir(), "obs")
        assert backend.detect(str(tmp_path / "nowhere.exe")).missing


class TestReplayBuffer:
    def test_start_sets_up_vertex_own_profile_and_scene(self, connected, tmp_path):
        states = []
        recorder = ObsRecorder(lambda state, _error: states.append(state))
        recorder.start(a_plan(tmp_path), str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.RUNNING), recorder.error
        fake = connected
        assert fake.profile == "Vertex" and fake.collection == "Vertex"
        # Its settings changed, so the profile was loaded again by way of another.
        assert fake.switches == ["Vertex", "Untitled", "Vertex"]
        assert fake.params[("Vertex", "SimpleOutput", "RecRBTime")] == "60"
        assert (fake.video["baseWidth"], fake.video["outputWidth"]) == (2560, 1920)
        assert fake.inputs["Vertex Display"]["settings"]["monitor_id"] == "mon-2"
        assert fake.transforms["boundsWidth"] == 2560
        tracks = {name: [n for n, on in item["tracks"].items() if on]
                  for name, item in fake.inputs.items()}
        assert tracks["Vertex Game"] == ["1"] and tracks["Vertex Mic"] == ["3"]
        assert tracks["Desktop Audio"] == [] and tracks["Mic/Aux"] == []
        assert fake.inputs["Vertex Mic"]["settings"]["device_id"] == \
            "{0.0.1.00000000}.{mic-guid}"
        assert states == [State.STARTING, State.RUNNING] and fake.replay_active

        recorder.stop()
        assert recorder.state == State.STOPPED and not fake.replay_active

        # Started again with the same settings: nothing to reload, and a track
        # switched off goes.
        fake.switches.clear()
        recorder.start(a_plan(tmp_path), str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.RUNNING), recorder.error
        assert fake.switches == []
        recorder.stop()
        setup = a_plan(tmp_path)
        recorder.start(obs.Plan(**{**setup.__dict__, "inputs": setup.inputs[:2]}),
                       str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.RUNNING), recorder.error
        assert "Vertex Mic" not in fake.inputs
        recorder.stop()

    def test_media_is_a_fourth_track_and_each_records_at_its_volume(self, connected, tmp_path):
        recorder = ObsRecorder()
        setup = a_plan(tmp_path, media_audio="device:{0.0.0.00000000}.{media-guid}",
                       chat_volume=80, mic_volume=0)
        assert [a.name for a in setup.inputs] == ["Vertex Game", "Vertex Chat", "Vertex Media",
                                                  "Vertex Mic"]
        assert "Track 2: Vertex Chat ({0.0.0.00000000}.{chat-guid}, at 80%)" in \
            obs.describe(setup)
        recorder.start(setup, str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.RUNNING), recorder.error
        fake = connected
        assert {name: item["volume"] for name, item in fake.inputs.items() if "volume" in item} \
            == {"Vertex Game": 1.0, "Vertex Chat": 0.8, "Vertex Media": 1.0, "Vertex Mic": 0.0}
        assert [n for n, on in fake.inputs["Vertex Media"]["tracks"].items() if on] == ["3"]
        assert fake.params[("Vertex", "SimpleOutput", "RecTracks")] == "15"
        recorder.stop()

    def test_a_save_becomes_a_clip_with_named_tracks(self, connected, tmp_path, sample_clip):
        connected.replay_file = str(sample_clip)
        saved = []
        recorder = ObsRecorder(on_saved=saved.append)
        clips = tmp_path / "clips"
        recorder.start(a_plan(tmp_path), str(clips))
        assert wait_for(lambda: recorder.state == State.RUNNING), recorder.error
        recorder.save(2)
        assert wait_for(lambda: saved, 30)
        clip = saved[0]
        assert os.path.dirname(clip) == str(clips)
        assert os.path.basename(clip).startswith("Replay_")
        assert os.listdir(tmp_path / "obs") == []          # OBS's save is gone
        info = probe.probe(clip)
        assert [t.name for t in info.tracks] == ["Vertex Game", "Vertex Chat", "Vertex Mic"]
        assert info.duration < 3.5                           # the last 2 s, from a keyframe
        recorder.stop()

    def test_obs_stopping_the_buffer_is_a_failure(self, connected, tmp_path):
        recorder = ObsRecorder()
        recorder.start(a_plan(tmp_path), str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.RUNNING), recorder.error
        connected.replay_active = False
        connected.event("ReplayBufferStateChanged", {
            "outputActive": False, "outputState": "OBS_WEBSOCKET_OUTPUT_STOPPED"})
        assert wait_for(lambda: recorder.state == State.FAILED)
        assert recorder.error == "OBS stopped the replay buffer."

    def test_closing_quits_only_an_obs_vertex_started(self, connected, tmp_path, monkeypatch):
        class Started:
            pid = 4242

            def poll(self):
                return None

        launched, closed = [], []
        monkeypatch.setattr(obs, "find", lambda _command: "C:/OBS/bin/64bit/obs64.exe")
        monkeypatch.setattr(obs, "launch", lambda exe: launched.append(exe) or Started())
        monkeypatch.setattr(windows, "close_program", lambda pid: closed.append(pid) or True)
        # OBS already open: the user's, left alone.
        recorder = ObsRecorder()
        recorder.start(a_plan(tmp_path), str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.RUNNING), recorder.error
        recorder.close_app()
        assert recorder.state == State.STOPPED and not launched and not closed
        # Started by Vertex: quit with the buffer, once.
        running = iter([False])
        monkeypatch.setattr(obs, "running", lambda: next(running, True))
        recorder.start(a_plan(tmp_path), str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.RUNNING), recorder.error
        assert launched
        recorder.close_app()
        assert closed == [4242] and not connected.replay_active
        recorder.close_app()
        assert closed == [4242]

    def test_a_buffer_obs_wont_start(self, connected, tmp_path, monkeypatch):
        monkeypatch.setattr("vertex.recorder.obs_replay.OUTPUT_SECONDS", 0.3)
        connected.start_fails = True
        recorder = ObsRecorder()
        recorder.start(a_plan(tmp_path), str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.FAILED)
        assert "didn't start the replay buffer" in recorder.error

    def test_obs_with_its_server_off(self, connected, tmp_path, monkeypatch):
        monkeypatch.setattr(obs, "websocket_settings", lambda: obs.WebSocketSettings())
        recorder = ObsRecorder()
        recorder.start(a_plan(tmp_path), str(tmp_path / "clips"))
        assert wait_for(lambda: recorder.state == State.FAILED)
        assert "WebSocket server is off" in recorder.error


def test_a_save_that_cant_be_finished_is_kept(tmp_path):
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"not a video")
    clip = finish(str(raw), str(tmp_path / "clips"), None, {})
    assert os.path.exists(clip) and not raw.exists()
    assert os.listdir(tmp_path / "clips") == [os.path.basename(clip)]


@pytest.mark.skipif(not windows.ON_WINDOWS, reason="asks Windows itself")
def test_what_windows_says():
    import sys

    assert windows.file_version(sys.executable)[:1] == (sys.version_info.major,)
    assert all(m.width > 0 and m.height > 0 for m in obs.monitor_rects())
    assert isinstance(obs.gpu_vendor(), str)
    for name, description in obs.list_audio_devices()[2:]:
        assert name.startswith(("{0.0.0.", "{0.0.1.")) and description
    assert obs.running() in (True, False)
