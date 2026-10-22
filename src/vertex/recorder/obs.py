"""OBS Studio as Vertex's recorder on Windows: finding it, its WebSocket
settings, the devices and monitors it can record, and what Vertex sets up in
it, built from Vertex's settings as plain data.

Vertex keeps an OBS profile and scene collection of its own, both called
"Vertex", and leaves the user's others alone. The profile holds the output
(simple mode: an encoder and a quality level, the replay buffer's length,
the tracks); the collection holds one scene with the monitor and one audio
source per clip track, each on its own track. OBS saves into a folder of
Vertex's, and Vertex finishes each save into the clips folder (see
obs_replay). No Qt here.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

from vertex import paths
from vertex.config import AUDIO_CODECS, CONTAINERS, ENCODERS, QUALITIES, RecorderConfig
from vertex.platform import windows
from vertex.platform.windows import MonitorRect
from vertex.recorder.gsr import CaptureOption, GsrInfo, Track

NAME = "OBS Studio"
INSTALL_URL = "https://obsproject.com/download"
# The first release with the settings this module writes (RecFormat2) and
# obs-websocket's own settings file.
MIN_VERSION = (30, 0)

PROFILE = "Vertex"
COLLECTION = "Vertex"
# Where the profile goes while it is reloaded, when the user has no other.
SPARE_PROFILE = "Vertex (spare)"

DISPLAY_INPUT = "Vertex Display"
REPLAY_MIN, REPLAY_MAX = 2, 21600          # OBS's own limits for the buffer
DEFAULT_PORT = 4455
MAX_TRACKS = 6

# Simple mode's two recording qualities, as Settings offers them: High is
# OBS's "High Quality, Medium File Size", Ultra its "Indistinguishable Quality".
# The lower levels GSR has come to High here.
QUALITY_LEVELS = ("very_high", "ultra")
RECORDING_QUALITY = {"medium": "Small", "high": "Small", "very_high": "Small", "ultra": "HQ"}

# Simple mode's encoder names, by GPU maker and codec.
GPU_ENCODERS = {
    "nvidia": {"h264": "nvenc", "hevc": "nvenc_hevc", "av1": "nvenc_av1"},
    "amd": {"h264": "amd", "hevc": "amd_hevc", "av1": "amd_av1"},
    "intel": {"h264": "qsv", "hevc": "qsv_hevc", "av1": "qsv_av1"},
}
CODECS = ("auto", "h264", "hevc", "av1")

# Windows' audio endpoint ids: outputs start {0.0.0., inputs {0.0.1.
_OUTPUT_PREFIX, _INPUT_PREFIX = "{0.0.0.00000000}.", "{0.0.1.00000000}."


# --- Finding OBS ------------------------------------------------------------

def config_dir() -> str:
    return os.path.join(windows.appdata(), "obs-studio")


def find(command: str = "") -> str:
    """obs64.exe: the one set in Settings, or the installed one; "" if none."""
    command = paths.normalize(command.strip('"'))
    if command:
        return command if os.path.isfile(command) else ""
    dirs = windows.registry_defaults(r"SOFTWARE\OBS Studio")
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    dirs.append(os.path.join(program_files, "obs-studio"))
    for folder in dirs:
        exe = os.path.join(folder, "bin", "64bit", "obs64.exe")
        if os.path.isfile(exe):
            return exe
    return ""


def detect(command: str = "") -> GsrInfo:
    info = GsrInfo(command=command)
    exe = find(command)
    if not exe:
        info.missing = True
        info.error = (f"{NAME} is not installed. Install it, or set where obs64.exe is "
                      f"in Settings.") if not command else f"{command} doesn't exist."
        return info
    info.available = True
    info.version = windows.file_version(exe)
    info.version_text = ".".join(map(str, info.version))
    if info.too_old:
        info.error = (f"{NAME} {info.version_text} is too old; Vertex needs "
                      f"{'.'.join(map(str, MIN_VERSION))} or newer.")
    return info


def running() -> bool:
    """Whether OBS is running for this user."""
    return windows.program_running("obs64.exe")


def launch(exe: str) -> subprocess.Popen:
    """Start OBS in the tray. It must run in its own folder to find its files;
    the shutdown check would otherwise ask about safe mode after a crash."""
    return subprocess.Popen([exe, "--minimize-to-tray", "--disable-shutdown-check"],
                            cwd=os.path.dirname(exe), close_fds=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def close(process: subprocess.Popen) -> bool:
    """Ask OBS, started by `launch`, to quit, if that same OBS still runs."""
    return process.poll() is None and windows.close_program(process.pid)


# --- obs-websocket's settings -------------------------------------------------

@dataclass
class WebSocketSettings:
    enabled: bool = False
    port: int = DEFAULT_PORT
    password: str = ""
    auth: bool = True
    found: bool = False            # OBS has written its settings file


def websocket_file() -> str:
    return os.path.join(config_dir(), "plugin_config", "obs-websocket", "config.json")


def _read_websocket(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def websocket_settings() -> WebSocketSettings:
    data = _read_websocket(websocket_file())
    if not data:
        return WebSocketSettings()
    try:
        port = int(data.get("server_port", DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    return WebSocketSettings(bool(data.get("server_enabled")), port,
                             str(data.get("server_password") or ""),
                             bool(data.get("auth_required", True)), True)


def enable_websocket() -> WebSocketSettings:
    """Switch OBS's WebSocket server on, with a password, in its settings file.
    Only while OBS is closed: OBS writes the file back when it quits."""
    path = websocket_file()
    data = _read_websocket(path)
    data["server_enabled"] = True
    data.setdefault("server_port", DEFAULT_PORT)
    if not data.get("server_password"):
        data["server_password"] = secrets.token_urlsafe(16)
        data["auth_required"] = True
    # OBS shows its connection details once, on the server's first start.
    data["first_load"] = False
    data.setdefault("alerts_enabled", False)
    paths.make_dir(os.path.dirname(path))
    temporary = f"{path}.vertex"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
    os.replace(temporary, path)
    return websocket_settings()


# --- What it can record ----------------------------------------------------------

def is_output(name: str) -> bool:
    """Whether a device (by list_audio_devices' name) plays sound rather than
    records it."""
    return name == "default_output" or name.startswith(_OUTPUT_PREFIX)


def list_audio_devices(_command: str = "") -> list[tuple[str, str]]:
    """(name, description) of every device a track can record: the defaults,
    then the outputs and inputs Windows has, by their endpoint ids."""
    devices = [("default_output", "Default output"), ("default_input", "Default input")]
    for flow, prefix in (("Render", _OUTPUT_PREFIX), ("Capture", _INPUT_PREFIX)):
        devices += [(prefix + guid, name) for guid, name in windows.audio_endpoints(flow)]
    return devices


def monitor_rects() -> list[MonitorRect]:
    return windows.monitor_rects()


def list_capture_options(_command: str = "") -> list[CaptureOption]:
    return [CaptureOption(m.name, "monitor", m.width, m.height) for m in monitor_rects()]


@lru_cache(maxsize=1)
def gpu_vendor() -> str:
    """Who made the graphics card: nvidia, amd, intel, or "" if unknown."""
    return vendor_of(windows.display_adapters())


def vendor_of(adapters: list[str]) -> str:
    """The maker of the first adapter that is one of the three, by its name."""
    for adapter in adapters:
        lowered = adapter.lower()
        if "nvidia" in lowered:
            return "nvidia"
        if "amd" in lowered or "radeon" in lowered:
            return "amd"
        if "intel" in lowered:
            return "intel"
    return ""


# --- What Vertex sets up ----------------------------------------------------------

def validate(rec: RecorderConfig) -> list[str]:
    """Problems with the settings that OBS can't record with."""
    problems = []
    if not REPLAY_MIN <= rec.replay_seconds <= REPLAY_MAX:
        problems.append(f"The replay length must be {REPLAY_MIN}–{REPLAY_MAX} seconds.")
    if not 1 <= rec.fps <= 1000:
        problems.append("The frame rate must be between 1 and 1000.")
    if rec.resolution and not re.fullmatch(r"\d+x\d+|\d+p", rec.resolution):
        problems.append("The resolution must look like 1080p or 1920x1080.")
    if rec.video_codec not in CODECS:
        problems.append(f"{NAME} can't record {rec.video_codec}; pick H.264, HEVC or AV1.")
    elif rec.encoder == "cpu" and rec.video_codec not in ("auto", "h264"):
        problems.append("CPU encoding only supports H.264.")
    for setting in ("game_audio", "chat_audio", "media_audio", "mic_audio"):
        if getattr(rec, setting).startswith("app:"):
            problems.append(f"Recording one app's sound isn't available with {NAME} yet.")
            break
    for name, value, allowed in (
        ("container", rec.container, CONTAINERS),
        ("quality", rec.quality, QUALITIES),
        ("audio codec", rec.audio_codec, AUDIO_CODECS),
        ("encoder", rec.encoder, ENCODERS),
    ):
        if value not in allowed:
            problems.append(f"Unknown {name}: {value!r}.")
    return problems


def encoder(rec: RecorderConfig, vendor: str) -> str:
    """Simple mode's encoder for these settings on this graphics card."""
    codec = "h264" if rec.video_codec == "auto" else rec.video_codec
    if rec.encoder == "cpu" or vendor not in GPU_ENCODERS:
        return "x264"
    return GPU_ENCODERS[vendor].get(codec, GPU_ENCODERS[vendor]["h264"])


@dataclass(frozen=True)
class AudioInput:
    name: str             # the source's name in OBS: "Vertex Game"
    kind: str             # wasapi_output_capture or wasapi_input_capture
    device: str           # the endpoint id, or "default"
    track: int            # 1-based
    title: str            # what the clip's track is called
    volume: int = 100     # percent


def audio_input(track: Track, number: int) -> AudioInput:
    source = track.source.removeprefix("device:")
    if source in ("default_output", "default_input"):
        output, device = source == "default_output", "default"
    else:
        output, device = is_output(source), source
    kind = "wasapi_output_capture" if output else "wasapi_input_capture"
    return AudioInput(track.title or f"Vertex Track {number}", kind, device, number,
                      track.title, track.volume)


@dataclass(frozen=True)
class Plan:
    """Everything a replay buffer run sets up in OBS."""

    command: str                       # obs64.exe as set in Settings ("" = find it)
    monitor: str                       # Windows' name for the monitor (\\.\DISPLAY1)
    size: tuple[int, int]              # the monitor's pixels
    output: tuple[int, int]            # the recorded video's size
    fps: int
    cursor: bool
    inputs: tuple[AudioInput, ...]
    profile: tuple[tuple[str, str, str], ...]     # (section, key, value)
    save_dir: str                      # where OBS saves, for Vertex to finish from
    seconds: int
    titles: dict[int, str] = field(default_factory=dict)


def buffer_mb(clip_bytes: int) -> int:
    """The memory the buffer may hold: well above what a clip should come to,
    since OBS drops the oldest seconds when it is full."""
    return max(2048, -(-clip_bytes * 3 // (1 << 20)))


def plan(rec: RecorderConfig, tracks: list[Track], save_dir: str, size: tuple[int, int],
         output: tuple[int, int], vendor: str, clip_bytes: int) -> Plan:
    """What to set up for `rec` as presets.resolve() gives it: `size` is the
    recorded monitor's, `output` the video's."""
    from vertex.recorder import presets

    inputs = tuple(audio_input(track, number)
                   for number, track in enumerate(tracks[:MAX_TRACKS], start=1))
    profile = (
        ("Output", "Mode", "Simple"),
        ("Output", "FilenameFormatting", "Replay_%CCYY-%MM-%DD_%hh-%mm-%ss"),
        ("SimpleOutput", "FilePath", save_dir),
        ("SimpleOutput", "RecFormat2", rec.container),
        ("SimpleOutput", "RecQuality", RECORDING_QUALITY.get(rec.quality, "HQ")),
        ("SimpleOutput", "RecEncoder", encoder(rec, vendor)),
        ("SimpleOutput", "RecAudioEncoder", rec.audio_codec),
        ("SimpleOutput", "ABitrate", str(min(320, presets.audio_kbps(rec)))),
        ("SimpleOutput", "RecTracks", str((1 << len(inputs)) - 1 if inputs else 1)),
        ("SimpleOutput", "RecRB", "true"),
        ("SimpleOutput", "RecRBTime", str(rec.replay_seconds)),
        ("SimpleOutput", "RecRBSize", str(buffer_mb(clip_bytes))),
        ("SimpleOutput", "RecRBPrefix", "Replay"),
        ("SimpleOutput", "RecRBSuffix", ""),
    )
    return Plan(rec.command, rec.capture, size, output, rec.fps, rec.cursor, inputs, profile,
                save_dir, rec.replay_seconds,
                {i: a.title for i, a in enumerate(inputs) if a.title})


def describe(setup: Plan) -> str:
    """The plan in a few lines, for the log and Settings' preview."""
    lines = [f"{NAME}: profile and scene collection \"{PROFILE}\"",
             f"Display: {setup.monitor} at {setup.output[0]}x{setup.output[1]}, "
             f"{setup.fps} fps{', with the cursor' if setup.cursor else ''}"]
    for audio in setup.inputs:
        what = "default " + ("output" if audio.kind == "wasapi_output_capture" else "input") \
            if audio.device == "default" else audio.device
        volume = f", at {audio.volume}%" if audio.volume != 100 else ""
        lines.append(f"Track {audio.track}: {audio.name} ({what}{volume})")
    values = {key: value for _section, key, value in setup.profile}
    lines.append(f"Encoder {values['RecEncoder']}, quality {values['RecQuality']}, "
                 f"{values['RecFormat2']}, last {setup.seconds} s")
    return "\n".join(lines)


_ITEM_PLACE = re.compile(r"(\d+)\s*x\s*(\d+)\s*@\s*(-?\d+)\s*,\s*(-?\d+)")


def pick_monitor(items: list[dict], wanted: MonitorRect | None,
                 size: tuple[int, int]) -> str:
    """The monitor capture's monitor_id for the monitor to record, from OBS's
    list of them ("DELL U2719D: 2560x1440 @ 0,0"): by place and size, else
    size alone, else the primary one, else the first."""
    usable = [item for item in items if item.get("itemEnabled", True)
              and item.get("itemValue") not in (None, "")]
    if not usable:
        return ""

    def place(item):
        match = _ITEM_PLACE.search(str(item.get("itemName", "")))
        return tuple(int(part) for part in match.groups()) if match else None

    if wanted is not None:
        exact = (wanted.width, wanted.height, wanted.x, wanted.y)
        for item in usable:
            if place(item) == exact:
                return item["itemValue"]
    for item in usable:
        found = place(item)
        if found and found[:2] == tuple(size):
            return item["itemValue"]
    for item in usable:
        if "primary" in str(item.get("itemName", "")).lower():
            return item["itemValue"]
    return usable[0]["itemValue"]
