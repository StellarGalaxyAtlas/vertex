import os
import stat
import sys
import textwrap
import time

import pytest

from vertex.config import Config, RecorderConfig
from vertex.recorder import gsr
from vertex.recorder.replay import RecorderError, ReplayRecorder, State

FAKE_GSR = textwrap.dedent('''\
    #!{python}
    """Stands in for gpu-screen-recorder: same flags, same signals, same stdout."""
    import os, signal, sys, time
    args = sys.argv[1:]
    if args == ["--version"]:
        print("5.15.1"); sys.exit(0)
    if args == ["--list-audio-devices"]:
        print("default_output|Default output")
        print("vertex_game.monitor|Monitor of Vertex Game"); sys.exit(0)
    if args == ["--list-capture-options"]:
        print("window"); print("DP-1|2560x1440@0x0"); print("portal"); sys.exit(0)
    if "bad" in args:
        print("gsr error: invalid capture target", file=sys.stderr); sys.exit(2)
    out = args[args.index("-o") + 1]
    count = [0]
    def save(seconds):
        count[0] += 1
        path = os.path.join(out, f"Replay_2026-01-01_00-00-0{{count[0]}}.mp4")
        with open(path, "w") as handle:
            handle.write(str(seconds))
        print(path, flush=True)
    signal.signal(signal.SIGUSR1, lambda *a: save("all"))
    signal.signal(signal.SIGRTMIN + 2, lambda *a: save(30))
    signal.signal(signal.SIGINT, lambda *a: sys.exit(0))
    while True:
        time.sleep(0.05)
''')


@pytest.fixture
def fake_gsr(tmp_path):
    path = tmp_path / "gpu-screen-recorder"
    path.write_text(FAKE_GSR.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestArgv:
    def test_defaults(self):
        rec = RecorderConfig()
        argv = gsr.build_argv(rec, [gsr.Track("default_output", "")], "/clips")
        assert argv[:3] == ["gpu-screen-recorder", "-w", "screen"]
        assert argv[-2:] == ["-o", "/clips"]
        pairs = dict(zip(argv[1::2], argv[2::2], strict=False))
        assert pairs["-r"] == "60" and pairs["-c"] == "mp4" and pairs["-ac"] == "aac"
        assert pairs["-q"] == "very_high" and pairs["-v"] == "no"
        assert "-restore-portal-session" not in argv and "-ab" not in argv

    def test_sonar_tracks_are_named_on_new_recorders(self):
        config = Config()
        config.sonar.enabled = True
        config.sonar.channel("aux").record = False
        tracks = gsr.audio_tracks(config)
        assert [t.channel for t in tracks] == ["game", "chat", "media", "mic"]
        new = gsr.GsrInfo("gsr", True, (5, 15, 1))
        old = gsr.GsrInfo("gsr", True, (5, 10, 2))
        argv = gsr.build_argv(config.recorder, tracks, "/c", new)
        assert "name:Vertex Game|device:vertex_game.monitor" in argv
        assert "name:Vertex Mic|device:vertex_mic" in argv
        argv = gsr.build_argv(config.recorder, tracks, "/c", old)
        assert "device:vertex_game.monitor" in argv
        assert not [a for a in argv if a.startswith("name:")]

    def test_without_sonar_uses_configured_sources(self):
        config = Config()
        config.recorder.audio_sources = ["default_output", " ", "app:firefox"]
        assert [t.source for t in gsr.audio_tracks(config)] == ["default_output", "app:firefox"]

    def test_options(self):
        rec = RecorderConfig(command="flatpak run --command=gpu-screen-recorder x.y",
                             capture="portal", bitrate_mode="cbr", bitrate_kbps=30000,
                             audio_bitrate=192, cursor=False, extra_args="-tune quality",
                             resolution="1920x1080")
        argv = gsr.build_argv(rec, [], "/o")
        assert argv[:4] == ["flatpak", "run", "--command=gpu-screen-recorder", "x.y"]
        pairs = dict(zip(argv[4::2], argv[5::2], strict=False))
        assert pairs["-q"] == "30000" and pairs["-ab"] == "192" and pairs["-cursor"] == "no"
        assert pairs["-restore-portal-session"] == "yes" and pairs["-s"] == "1920x1080"
        assert argv[argv.index("-tune") + 1] == "quality"

    def test_region(self):
        rec = RecorderConfig(capture="region", region="800x600+10+20")
        argv = gsr.build_argv(rec, [], "/o")
        assert argv[argv.index("-region") + 1] == "800x600+10+20"

    @pytest.mark.parametrize("changes, fragment", [
        ({"replay_seconds": 1}, "replay length"),
        ({"capture": "region", "region": "nope"}, "region"),
        ({"capture": "focused"}, "focused"),
        ({"encoder": "cpu", "video_codec": "hevc"}, "CPU"),
        ({"video_codec": "vp9"}, "MKV"),
        ({"extra_args": "-x 'open"}, "quote"),
        ({"container": "avi"}, "container"),
    ])
    def test_validate(self, changes, fragment):
        problems = gsr.validate(RecorderConfig(**changes))
        assert any(fragment in problem for problem in problems), problems

    def test_valid_defaults(self):
        assert gsr.validate(RecorderConfig()) == []

    def test_parse_version(self):
        assert gsr.parse_version("5.15.1") == (5, 15, 1)
        assert gsr.parse_version("gpu-screen-recorder 4.3") == (4, 3)
        assert gsr.parse_version("") == ()


class TestDetection:
    def test_detect_and_list(self, fake_gsr):
        info = gsr.detect(fake_gsr)
        assert info.available and info.version == (5, 15, 1) and info.supports_track_names
        assert ("vertex_game.monitor", "Monitor of Vertex Game") in \
            gsr.list_audio_devices(fake_gsr)
        assert gsr.list_capture_options(fake_gsr) == ["window", "DP-1", "portal"]

    def test_missing(self, tmp_path):
        info = gsr.detect(str(tmp_path / "nope"))
        assert not info.available and "not installed" in info.error


class TestReplayRecorder:
    def test_save_and_stop(self, fake_gsr, tmp_path):
        out = tmp_path / "clips"
        states, saved = [], []
        recorder = ReplayRecorder(lambda state, _err: states.append(state), saved.append)
        recorder.start([fake_gsr, "-w", "screen", "-o", str(out)], str(out))
        assert _wait(lambda: recorder.state == State.RUNNING)
        with pytest.raises(RecorderError):
            recorder.start([fake_gsr], str(out))
        recorder.save()
        assert _wait(lambda: len(saved) == 1)
        recorder.save(30)
        assert _wait(lambda: len(saved) == 2)
        with open(saved[1]) as handle:
            assert handle.read() == "30"
        with pytest.raises(RecorderError):
            recorder.save(45)
        recorder.stop()
        assert recorder.state == State.STOPPED and not recorder.running
        assert states[:2] == [State.STARTING, State.RUNNING]
        with pytest.raises(RecorderError):
            recorder.save()

    def test_failure_reports_stderr(self, fake_gsr, tmp_path):
        recorder = ReplayRecorder()
        recorder.start([fake_gsr, "-w", "bad", "-o", str(tmp_path)], str(tmp_path))
        assert _wait(lambda: recorder.state == State.FAILED)
        assert "invalid capture target" in recorder.error

    def test_missing_binary(self, tmp_path):
        recorder = ReplayRecorder()
        with pytest.raises(RecorderError):
            recorder.start([str(tmp_path / "nope")], str(tmp_path))
        assert recorder.state == State.FAILED

    def test_child_dies_with_its_session(self, fake_gsr, tmp_path):
        recorder = ReplayRecorder()
        recorder.start([fake_gsr, "-o", str(tmp_path)], str(tmp_path))
        pid = recorder.pid
        assert pid and os.getpgid(pid) == pid      # its own process group
        recorder.stop()
