"""GPU Screen Recorder: finding it, asking it what it can do, and building its
command line from Vertex's settings.

Everything about a recording is a command-line flag, so the whole of
`RecorderConfig` maps onto one argv, built here as a pure function. Audio is
where Vertex adds something: with Sonar on, every recorded channel becomes its
own track, titled after the channel, so every clip carries the same tracks in
the same layout whatever the hardware is called.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass

from vertex.audio import channels
from vertex.config import (
    BITRATE_MODES,
    COLOR_RANGES,
    CONTAINERS,
    ENCODERS,
    FRAMERATE_MODES,
    QUALITIES,
    REPLAY_STORAGES,
    Config,
    RecorderConfig,
)

# `-a "name:<title>|device:<node>"` sets a track's title. Versions before this
# take the "name:" part for a device and refuse to start.
TRACK_NAMES_SINCE = (5, 15)
# The oldest release whose flags this module emits (-replay-storage, -encoder).
MIN_VERSION = (5, 0)

REPLAY_MIN, REPLAY_MAX = 2, 86400

# SIGRTMIN offsets that save only the last N seconds of the buffer.
SAVE_PRESETS = {10: 1, 30: 2, 60: 3, 300: 4, 600: 5, 1800: 6}


@dataclass
class GsrInfo:
    command: str
    available: bool = False
    version: tuple[int, ...] = ()
    version_text: str = ""
    error: str = ""

    @property
    def supports_track_names(self) -> bool:
        return self.version >= TRACK_NAMES_SINCE

    @property
    def too_old(self) -> bool:
        return bool(self.version) and self.version < MIN_VERSION


def command_argv(command: str) -> list[str]:
    try:
        argv = shlex.split(command or "")
    except ValueError:
        argv = []
    return argv or ["gpu-screen-recorder"]


def parse_version(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.groups() if part is not None)


def _query(command: str, *args: str, timeout: float = 10) -> str:
    result = subprocess.run([*command_argv(command), *args], capture_output=True, text=True,
                            timeout=timeout)
    return result.stdout


def detect(command: str) -> GsrInfo:
    info = GsrInfo(command=command)
    try:
        text = _query(command, "--version", timeout=5).strip()
    except FileNotFoundError:
        info.error = ("GPU Screen Recorder is not installed. Install the "
                      "'gpu-screen-recorder' package, or set its command in Settings.")
        return info
    except (OSError, subprocess.SubprocessError) as exc:
        info.error = f"Could not run GPU Screen Recorder: {exc}"
        return info
    info.available = True
    info.version_text = text.splitlines()[0] if text else ""
    info.version = parse_version(text)
    if info.too_old:
        info.error = (f"GPU Screen Recorder {info.version_text} is too old; Vertex needs "
                      f"{'.'.join(map(str, MIN_VERSION))} or newer.")
    return info


def list_audio_devices(command: str) -> list[tuple[str, str]]:
    """(name, description) of every device GSR can record from."""
    try:
        out = _query(command, "--list-audio-devices")
    except (OSError, subprocess.SubprocessError):
        return []
    devices = []
    for line in out.splitlines():
        name, _, description = line.partition("|")
        if name.strip():
            devices.append((name.strip(), description.strip() or name.strip()))
    return devices


def list_capture_options(command: str) -> list[str]:
    """Capture targets this machine offers: 'screen', 'portal', monitor names…"""
    try:
        out = _query(command, "--list-capture-options")
    except (OSError, subprocess.SubprocessError):
        return []
    options = []
    for line in out.splitlines():
        option = line.split("|", 1)[0].strip()
        if option and option not in options:
            options.append(option)
    return options


@dataclass(frozen=True)
class Track:
    """One audio track of a recording."""

    source: str      # what GSR records: "device:vertex_game.monitor", "default_output", …
    title: str       # the track title written into the clip ("" = GSR's own)
    channel: str = ""

    def argument(self, named: bool) -> str:
        if named and self.title:
            return f"name:{self.title}|{self.source}"
        return self.source


def audio_tracks(config: Config) -> list[Track]:
    """The tracks a recording will have under the current settings."""
    if config.sonar.enabled:
        return [Track(f"device:{channel.record_source}", channel.track_title, channel.id)
                for channel in channels.ALL if config.sonar.channel(channel.id).record]
    return [Track(source.strip(), "") for source in config.recorder.audio_sources
            if source.strip()]


def validate(rec: RecorderConfig) -> list[str]:
    """Problems with the settings that GSR would refuse to start over."""
    problems = []
    if not REPLAY_MIN <= rec.replay_seconds <= REPLAY_MAX:
        problems.append(f"The replay length must be {REPLAY_MIN}–{REPLAY_MAX} seconds.")
    if not 1 <= rec.fps <= 1000:
        problems.append("The frame rate must be between 1 and 1000.")
    if rec.capture == "region" and not re.fullmatch(r"\d+x\d+\+\d+\+\d+", rec.region):
        problems.append("A region capture needs the region as WxH+X+Y, e.g. 1920x1080+0+0.")
    if rec.resolution and not re.fullmatch(r"\d+x\d+", rec.resolution):
        problems.append("The resolution limit must look like 1920x1080.")
    if rec.capture == "focused" and not rec.resolution:
        problems.append("Recording the focused window needs a resolution limit.")
    if rec.encoder == "cpu" and rec.video_codec not in ("auto", "h264"):
        problems.append("CPU encoding only supports H.264.")
    if rec.video_codec in ("vp8", "vp9") and rec.container == "mp4":
        problems.append("VP8/VP9 cannot be stored in MP4; pick MKV.")
    if rec.video_codec.endswith("_hdr") and rec.capture == "portal":
        problems.append("HDR is not available with portal capture.")
    if rec.bitrate_mode == "cbr" and rec.bitrate_kbps <= 0:
        problems.append("Constant bitrate needs a bitrate.")
    for name, value, allowed in (
        ("container", rec.container, CONTAINERS),
        ("quality", rec.quality, QUALITIES),
        ("bitrate mode", rec.bitrate_mode, BITRATE_MODES),
        ("frame rate mode", rec.framerate_mode, FRAMERATE_MODES),
        ("color range", rec.color_range, COLOR_RANGES),
        ("replay storage", rec.replay_storage, REPLAY_STORAGES),
        ("encoder", rec.encoder, ENCODERS),
    ):
        if value not in allowed:
            problems.append(f"Unknown {name}: {value!r}.")
    try:
        shlex.split(rec.extra_args)
    except ValueError:
        problems.append("The extra arguments have an unclosed quote.")
    return problems


def build_argv(rec: RecorderConfig, tracks: list[Track], output_dir: str,
               info: GsrInfo | None = None) -> list[str]:
    """The full replay-buffer command for these settings."""
    yes_no = {True: "yes", False: "no"}
    argv = [*command_argv(rec.command), "-w", rec.capture]
    if rec.capture == "region" and rec.region:
        argv += ["-region", rec.region]
    if rec.resolution:
        argv += ["-s", rec.resolution]
    argv += ["-f", str(rec.fps), "-c", rec.container, "-k", rec.video_codec,
             "-bm", rec.bitrate_mode,
             "-q", str(rec.bitrate_kbps) if rec.bitrate_mode == "cbr" else rec.quality,
             "-fm", rec.framerate_mode, "-cr", rec.color_range,
             "-cursor", yes_no[rec.cursor], "-encoder", rec.encoder,
             "-keyint", f"{rec.keyframe_interval:g}",
             "-ac", rec.audio_codec]
    if rec.audio_bitrate > 0:
        argv += ["-ab", str(rec.audio_bitrate)]
    argv += ["-r", str(rec.replay_seconds), "-replay-storage", rec.replay_storage]
    if rec.capture == "portal":
        argv += ["-restore-portal-session", yes_no[rec.restore_portal_session]]
    named = info.supports_track_names if info is not None else False
    for track in tracks:
        argv += ["-a", track.argument(named)]
    argv += ["-v", "no"]
    argv += shlex.split(rec.extra_args or "")
    argv += ["-o", output_dir]
    return argv
