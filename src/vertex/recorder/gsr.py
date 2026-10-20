"""GPU Screen Recorder: finding it, asking it what it can do, and building its
command line from Vertex's settings.

Everything about a recording is a command-line flag, so the whole of
`RecorderConfig` maps onto one argv, built here as a pure function. Audio is
where Vertex adds something: every recorded part (game, chat, mic) becomes
its own track, titled after the part, so every clip carries the same tracks
in the same layout whatever the hardware is called.
"""

from __future__ import annotations

import dataclasses
import re
import shlex
import subprocess
from dataclasses import dataclass

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
from vertex.media import roles

# `-a "name:<title>|device:<node>"` sets a track's title. Versions before this
# take the "name:" part for a device and refuse to start.
TRACK_NAMES_SINCE = (5, 15)

# The project's own page, which keeps its install instructions current for
# every distro and the Flatpak.
INSTALL_URL = "https://git.dec05eba.com/gpu-screen-recorder/about/"

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
    missing: bool = False        # the command isn't there at all

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
        info.missing = True
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


@dataclass(frozen=True)
class CaptureOption:
    """Something GSR can record, as `--list-capture-options` reports it."""

    value: str           # what `-w` takes: "DP-1", "portal", "/dev/video0", …
    kind: str            # "monitor", "camera", or the option itself: "portal", "region", …
    width: int = 0       # a monitor's size in pixels, turned with it if it is rotated
    height: int = 0


def parse_capture_options(text: str) -> list[CaptureOption]:
    """Bare options ("window", "focused", "region", "portal"), monitors as
    NAME|WxH, and cameras as /dev/videoN|WxH@30hz|format, once per mode."""
    options: list[CaptureOption] = []
    seen = set()
    for line in text.splitlines():
        value, bar, detail = line.partition("|")
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        if value.startswith("/dev/video"):
            options.append(CaptureOption(value, "camera"))
        elif bar:
            size = re.match(r"\s*(\d+)x(\d+)", detail)
            width, height = (int(size[1]), int(size[2])) if size else (0, 0)
            options.append(CaptureOption(value, "monitor", width, height))
        else:
            options.append(CaptureOption(value, value))
    return options


def list_capture_options(command: str) -> list[CaptureOption]:
    """What this machine can record: its monitors, the portal, cameras…"""
    try:
        out = _query(command, "--list-capture-options")
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_capture_options(out)


@dataclass(frozen=True)
class Track:
    """One audio track of a recording."""

    source: str      # what GSR records: "default_output", "app:Discord", "device:…"
    title: str       # the track title written into the clip ("" = GSR's own)
    channel: str = ""
    volume: int = 100   # percent, where the recorder can set it

    def argument(self, named: bool) -> str:
        if named and self.title:
            return f"name:{self.title}|{self.source}"
        return self.source


# A clip's audio tracks: the lane each becomes, and the setting naming its device.
AUDIO_ROLES = ((roles.GAME.id, "game_audio"), (roles.CHAT.id, "chat_audio"),
               (roles.MEDIA.id, "media_audio"), (roles.MIC.id, "mic_audio"))


def audio_tracks(config: Config) -> list[Track]:
    """The tracks a recording will have: one per role with a device chosen,
    titled after the role ("Vertex Game"), so the editor names its lane Game
    whichever device it came from."""
    tracks = []
    for role, setting in AUDIO_ROLES:
        source = getattr(config.recorder, setting).strip()
        if source:
            volume = getattr(config.recorder, f"{role}_volume", 100)
            tracks.append(Track(source, roles.BY_ID[role].track_title, role, volume))
    return tracks


def fallback_source(role: str) -> str:
    """What a track records while its own device is missing."""
    return "default_input" if role == roles.MIC.id else "default_output"


def _recordable(source: str, devices: set[str]) -> bool:
    if source.startswith("device:"):
        return source.removeprefix("device:") in devices
    if source in ("default_output", "default_input"):
        return source in devices
    return True          # app:… and the like: GSR's to judge


def available_tracks(tracks: list[Track],
                     devices: list[str]) -> tuple[list[Track], list[tuple[Track, str]]]:
    """The tracks to record now. GSR won't start at all with a device it
    doesn't have (an unplugged headset), so
    such a track records the default output, or the default input for the
    microphone, until its device is back; the setting itself is kept.

    `devices` are the names list_audio_devices gives; empty means unknown.
    Returns the tracks, and each stood-in track with the source it records
    instead ("" if even that is missing, and the track is left out).
    """
    if not devices:
        return tracks, []
    known = set(devices)
    usable, stood_in = [], []
    for track in tracks:
        if _recordable(track.source, known):
            usable.append(track)
            continue
        fallback = fallback_source(track.channel)
        if fallback in known:
            usable.append(dataclasses.replace(track, source=fallback))
            stood_in.append((track, fallback))
        else:
            stood_in.append((track, ""))
    return usable, stood_in


def validate(rec: RecorderConfig) -> list[str]:
    """Problems with the settings that GSR would refuse to start over."""
    problems = []
    if not REPLAY_MIN <= rec.replay_seconds <= REPLAY_MAX:
        problems.append(f"The replay length must be {REPLAY_MIN}–{REPLAY_MAX} seconds.")
    if not 1 <= rec.fps <= 1000:
        problems.append("The frame rate must be between 1 and 1000.")
    if rec.capture == "region" and not re.fullmatch(r"\d+x\d+\+\d+\+\d+", rec.region):
        problems.append("A region capture needs the region as WxH+X+Y, e.g. 1920x1080+0+0.")
    if rec.resolution and not re.fullmatch(r"\d+x\d+|\d+p", rec.resolution):
        problems.append("The resolution must look like 1080p or 1920x1080.")
    if rec.capture == "focused" and not rec.resolution:
        problems.append("Recording the focused window needs a resolution limit.")
    if rec.encoder == "cpu" and rec.video_codec not in ("auto", "h264"):
        problems.append("CPU encoding only supports H.264.")
    if rec.video_codec in ("vp8", "vp9") and rec.container == "mp4":
        problems.append("VP8/VP9 cannot be stored in MP4; pick MKV.")
    if rec.video_codec.endswith("_hdr") and rec.capture == "portal":
        problems.append("HDR is not available with portal capture.")
    if rec.bitrate_mode == "cbr" and rec.bitrate_kbps <= 0:
        # Settings and the recorder pass presets.resolve()d settings, which have one.
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
