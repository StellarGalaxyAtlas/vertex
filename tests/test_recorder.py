import os
import stat
import sys
import textwrap
import time

import pytest

from vertex.config import Config, RecorderConfig
from vertex.recorder import gsr, monitors, presets
from vertex.recorder.gsr import CaptureOption
from vertex.recorder.monitors import Screen
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
        print("window"); print("focused"); print("DP-1|2560x1440"); print("region")
        print("portal"); sys.exit(0)
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
        rec = presets.resolve(RecorderConfig(), [])
        argv = gsr.build_argv(rec, [gsr.Track("default_output", "")], "/clips")
        assert argv[:3] == ["gpu-screen-recorder", "-w", "screen"]
        assert argv[-2:] == ["-o", "/clips"]
        pairs = dict(zip(argv[1::2], argv[2::2], strict=False))
        assert pairs["-r"] == "60" and pairs["-c"] == "mp4" and pairs["-ac"] == "aac"
        # Constant bitrate by default, at what High comes to for 1080p60.
        assert pairs["-bm"] == "cbr" and pairs["-q"] == "20000" and pairs["-v"] == "no"
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
        assert gsr.validate(presets.resolve(RecorderConfig(), [])) == []
        assert gsr.validate(RecorderConfig(resolution="1080p", bitrate_mode="qp")) == []
        assert any("bitrate" in p for p in gsr.validate(RecorderConfig()))

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
        assert [o.value for o in gsr.list_capture_options(fake_gsr)] == \
            ["window", "focused", "DP-1", "region", "portal"]

    def test_missing(self, tmp_path):
        info = gsr.detect(str(tmp_path / "nope"))
        assert not info.available and "not installed" in info.error
        assert gsr.list_capture_options(str(tmp_path / "nope")) == []

    def test_capture_options(self):
        # As GSR 5.15 prints them: bare options, monitors with their size
        # (turned with a rotated monitor), cameras once per mode.
        text = ("window\nfocused\nDP-1|2560x1440\nHDMI-A-1|1080x1920\nregion\n"
                "/dev/video0|1920x1080@30hz|mjpeg\n/dev/video0|640x480@30hz|yuyv\n"
                "portal\n\n")
        assert gsr.parse_capture_options(text) == [
            CaptureOption("window", "window"),
            CaptureOption("focused", "focused"),
            CaptureOption("DP-1", "monitor", 2560, 1440),
            CaptureOption("HDMI-A-1", "monitor", 1080, 1920),
            CaptureOption("region", "region"),
            CaptureOption("/dev/video0", "camera"),
            CaptureOption("portal", "portal"),
        ]
        assert gsr.parse_capture_options("DP-1|odd") == [CaptureOption("DP-1", "monitor")]


class TestMonitors:
    LANDSCAPE = Screen("DP-1", 0, 240, 2560, 1440, "Dell", (2560, 1440))
    VERTICAL = Screen("DP-2", 2560, 0, 1080, 1920, "AOC", (1080, 1920))

    def test_placed_where_the_desktop_has_them_in_gsrs_order(self):
        options = [CaptureOption("DP-2", "monitor", 1080, 1920),
                   CaptureOption("DP-1", "monitor", 2560, 1440), CaptureOption("portal", "portal")]
        arranged = monitors.arrange(options, [self.LANDSCAPE, self.VERTICAL])
        assert [m.name for m in arranged] == ["DP-2", "DP-1"]
        vertical = arranged[0]
        assert (vertical.x, vertical.y, vertical.width, vertical.height) == (2560, 0, 1080, 1920)
        assert vertical.pixels == (1080, 1920) and vertical.model == "AOC" and vertical.placed

    def test_gsr_decides_what_is_listed(self):
        # A screen GSR can't record is left out; one the desktop doesn't know
        # by that name is put to the right of the rest.
        options = [CaptureOption("DP-1", "monitor", 2560, 1440),
                   CaptureOption("DP-3", "monitor", 1920, 1080)]
        arranged = monitors.arrange(options, [self.LANDSCAPE, self.VERTICAL])
        assert [m.name for m in arranged] == ["DP-1", "DP-3"]
        loose = arranged[1]
        assert not loose.placed
        assert (loose.x, loose.y, loose.width, loose.height) == (2560, 240, 1920, 1080)

    def test_without_gsr_the_desktops_monitors_stand_in(self):
        arranged = monitors.arrange([CaptureOption("portal", "portal")],
                                    [self.LANDSCAPE, self.VERTICAL])
        assert [(m.name, m.pixels) for m in arranged] == [("DP-1", (2560, 1440)),
                                                          ("DP-2", (1080, 1920))]
        assert monitors.arrange([], []) == []

    def test_resolution_falls_back_to_the_desktops(self):
        arranged = monitors.arrange([CaptureOption("DP-1", "monitor")], [self.LANDSCAPE])
        assert arranged[0].pixels == (2560, 1440)
        loose = monitors.arrange([CaptureOption("X-1", "monitor")], [])[0]
        assert loose.pixels == (0, 0) and (loose.width, loose.height) == (1920, 1080)

    def test_fit_keeps_proportions_and_centres(self):
        arranged = monitors.arrange([], [self.LANDSCAPE, self.VERTICAL])
        boxes = monitors.fit(arranged, 400, 200, margin=10)
        # 3640 × 1920 desktop units into 380 × 180: height decides the scale.
        scale = 180 / 1920
        (lx, ly, lw, lh), (vx, vy, vw, vh) = boxes
        assert vh == pytest.approx(180) and vw == pytest.approx(1080 * scale)
        assert lw == pytest.approx(2560 * scale) and lh == pytest.approx(1440 * scale)
        assert vy == pytest.approx(10) and ly == pytest.approx(10 + 240 * scale)
        assert vx == pytest.approx(lx + lw)            # touching on the desktop, touching here
        assert lx == pytest.approx((400 - 3640 * scale) / 2)
        assert monitors.fit([], 400, 200) == []
        assert monitors.fit(arranged, 10, 10, margin=10) == [(5, 5, 0, 0), (5, 5, 0, 0)]

    def test_the_monitor_recorded(self):
        arranged = monitors.arrange([], [self.LANDSCAPE, Screen("DP-3", 0, 0, 800, 600,
                                                                primary=True)])
        assert monitors.target("DP-1", arranged) == "DP-1"
        # Not connected, or nothing picked: the primary monitor, else the first.
        assert monitors.target("HDMI-A-1", arranged) == "DP-3"
        assert monitors.target("screen", arranged) == "DP-3"
        assert monitors.target("portal", arranged[:1]) == "DP-1"
        assert monitors.target("DP-1", []) == "DP-1"
        assert monitors.target("", []) == "screen"

    def test_names_monitor_reads_values_as_gsr_does(self):
        for value in ("DP-1", "HDMI-A-1", "eDP-1", "DVI-D-0"):
            assert monitors.names_monitor(value), value
        for value in ("", "screen", "screen-direct", "portal", "focused", "region",
                      "/dev/video0", "1920x1080+0+0", "0x3a00007", "12345"):
            assert not monitors.names_monitor(value), value

    def test_reading_order(self):
        left = Screen("HDMI-A-1", -1920, 360, 1920, 1080)
        arranged = monitors.arrange([], [self.VERTICAL, self.LANDSCAPE, left])
        assert [m.name for m in monitors.reading_order(arranged)] == ["HDMI-A-1", "DP-1", "DP-2"]


class TestPresets:
    LANDSCAPE = (2560, 1440)
    VERTICAL = (1080, 1920)

    def test_output_size_keeps_the_monitors_shape(self):
        assert presets.output_size("1080p", self.LANDSCAPE) == (1920, 1080)
        # "720p" on a vertical monitor: its short side, so it stays vertical.
        assert presets.output_size("720p", self.VERTICAL) == (720, 1280)
        assert presets.output_size("1080p", (3440, 1440)) == (2580, 1080)
        # Never scaled up; "" is the monitor's own size.
        assert presets.output_size("1440p", (1920, 1080)) == (1920, 1080)
        assert presets.output_size("1080p", self.VERTICAL) == self.VERTICAL
        assert presets.output_size("", self.LANDSCAPE) == self.LANDSCAPE
        # A WxH limit from older settings works as GSR's does.
        assert presets.output_size("1920x1080", self.VERTICAL) == (607, 1080)
        assert presets.output_size("1080p", (0, 0)) == (1920, 1080)

    def test_gsr_box(self):
        assert presets.gsr_box("720p", self.VERTICAL) == "720x1280"
        assert presets.gsr_box("1080p", self.LANDSCAPE) == "1920x1080"
        assert presets.gsr_box("1080p", self.VERTICAL) == ""
        assert presets.gsr_box("", self.LANDSCAPE) == ""
        assert presets.gsr_box("1280x720", self.LANDSCAPE) == "1280x720"
        assert presets.gsr_box("720p", (0, 0)) == "1280x720"

    def test_video_bitrate_follows_size_and_frame_rate(self):
        assert presets.video_kbps("very_high", (1920, 1080), 60) == 20000
        assert presets.video_kbps("ultra", (1080, 1920), 60) == 35000
        assert presets.video_kbps("very_high", (1920, 1080), 30) == 12000
        assert presets.video_kbps("very_high", (2560, 1440), 60) == 31000
        assert presets.video_kbps("medium", (64, 64), 1) == 1000
        levels = [presets.video_kbps(level, (1920, 1080), 60) for level in presets.LEVELS]
        assert levels == [8000, 12000, 20000, 35000]

    def test_resolve_for_the_recorded_monitor(self):
        arranged = monitors.arrange([], [
            Screen("DP-1", 0, 240, 2560, 1440, pixels=self.LANDSCAPE, primary=True),
            Screen("DP-2", 2560, 0, 1080, 1920, pixels=self.VERTICAL)])
        rec = RecorderConfig(capture="DP-2", resolution="720p", fps=60)
        resolved = presets.resolve(rec, arranged)
        assert (resolved.capture, resolved.resolution) == ("DP-2", "720x1280")
        assert resolved.bitrate_kbps == presets.video_kbps("very_high", (720, 1280), 60)
        # Nothing picked: the primary monitor. A bitrate set by hand is kept.
        resolved = presets.resolve(RecorderConfig(resolution="1080p", bitrate_kbps=40000),
                                   arranged)
        assert (resolved.capture, resolved.resolution) == ("DP-1", "1920x1080")
        assert resolved.bitrate_kbps == 40000
        # GSR's quality modes ignore it; the estimate goes by the level then.
        resolved = presets.resolve(RecorderConfig(bitrate_mode="qp", bitrate_kbps=40000), [])
        assert resolved.bitrate_kbps == 20000

    def test_clip_size(self):
        resolved = presets.resolve(RecorderConfig(replay_seconds=60), [])
        assert resolved.bitrate_kbps == 20000
        # 20 Mbps of video and two AAC tracks at GSR's 160 kbps, for a minute.
        assert presets.clip_bytes(resolved, 2) == 20320 * 1000 // 8 * 60
        opus = presets.resolve(RecorderConfig(audio_codec="opus", audio_bitrate=0), [])
        assert presets.audio_kbps(opus) == 128


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
