import os
import shutil
import subprocess

import pytest

from vertex import logs, sounds


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own home, XDG and AppData dirs, so nothing touches
    the real ones."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))     # what ~ means on Windows
    for var, sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                     ("XDG_STATE_HOME", ".local/state"), ("XDG_CACHE_HOME", ".cache"),
                     ("APPDATA", "AppData/Roaming"), ("LOCALAPPDATA", "AppData/Local")):
        monkeypatch.setenv(var, str(home / sub))
    yield home
    # A test that saved settings switched the logs on, in its own home.
    logs.shutdown()
    monkeypatch.setattr(logs, "_enabled", None)


class FakeMpv:
    """libmpv as sounds.Player uses it: what it was told to play, and where."""

    def __init__(self):
        self.audio_device_list = [{"name": "auto"}, {"name": "pulse/alsa_output.usb-headset"}]
        self.audio_device = "auto"
        self.volume = 100
        self.played: list[tuple[str, str, int]] = []
        self.terminated = False

    def play(self, path):
        self.played.append((path, self.audio_device, self.volume))

    def terminate(self):
        self.terminated = True


@pytest.fixture(autouse=True)
def fake_mpv_sounds(monkeypatch):
    """No test plays a sound: each gets a stand-in for libmpv, the players it
    made listed here."""
    made: list[FakeMpv] = []

    def new_player():
        made.append(FakeMpv())
        return made[-1]

    monkeypatch.setattr(sounds, "_new_player", new_player)
    return made


def _have_ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


requires_ffmpeg = pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(scope="session")
def sample_clip(tmp_path_factory):
    """A 4-second 320x180 clip with three named audio tracks, like a recorder's."""
    if not _have_ffmpeg():
        pytest.skip("ffmpeg/ffprobe not installed")
    out = tmp_path_factory.mktemp("media") / "Apex-Legends__2026-08-11__22-14-07.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=4",
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-c:a", "aac",
        "-shortest",
        "-metadata:s:a:0", "title=Vertex Game",
        "-metadata:s:a:1", "title=Devices: Monitor of Vertex Chat",
        "-metadata:s:a:2", "title=Vertex Mic",
        str(out),
    ], check=True, capture_output=True)
    return str(out)


def env_flag(name):
    return os.environ.get(name, "") not in ("", "0", "no")
