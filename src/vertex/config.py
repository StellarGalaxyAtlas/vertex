"""The user's settings, stored as JSON in ~/.config/vertex/config.json.

Keys Vertex doesn't know are ignored (and dropped on the next save), and
anything missing or of the wrong type falls back to its default.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vertex import APP_NAME, notifications, paths, system
from vertex.core.name_patterns import NamePattern

# Subfolder of the user's videos dir that clips are recorded into by default.
CLIP_SUBDIR = "Game Recordings"

# Settings first-run setup has to produce before the app can start.
REQUIRED_FIELDS = ("clip_path", "export_path", "data_path", "state_path", "cache_path")

# The folders a run cannot quietly do without. Everything else a config names
# is output (exports) or derived state (thumbnails), remade on demand.
CHECKED_DIRS = ("clip_path", "data_path")


# The library's card size: the narrowest a card may be, in pixels, before a row
# holds one card fewer. Cards stretch to fill their row.
CARD_WIDTH_RANGE = (200, 640)
CARD_WIDTH_DEFAULT = 290

# --- Recorder ---------------------------------------------------------------
# Option values offered for GPU Screen Recorder. Kept here rather than in the
# recorder module because the settings UI and validation both need them.

CAPTURE_TARGETS = ("screen", "portal", "focused", "region")
CONTAINERS = ("mp4", "mkv")
VIDEO_CODECS = ("auto", "h264", "hevc", "av1", "vp8", "vp9",
                "hevc_10bit", "av1_10bit", "hevc_hdr", "av1_hdr")
QUALITIES = ("medium", "high", "very_high", "ultra")
BITRATE_MODES = ("auto", "qp", "vbr", "cbr")
FRAMERATE_MODES = ("vfr", "cfr", "content")
COLOR_RANGES = ("limited", "full")
AUDIO_CODECS = ("aac", "opus")
REPLAY_STORAGES = ("ram", "disk")
ENCODERS = ("gpu", "cpu")


@dataclass
class RecorderConfig:
    """How Vertex runs the replay buffer: GPU Screen Recorder's on Linux,
    OBS Studio's on Windows (see recorder.backend)."""

    autostart: bool = False          # start the replay buffer when Vertex starts
    # GSR's command, which may be a full one (a Flatpak run line); on Windows
    # obs64.exe, "" = wherever OBS is installed.
    command: str = "" if system.WINDOWS else "gpu-screen-recorder"
    capture: str = "screen"          # screen | portal | focused | region | <monitor name>
    region: str = ""                 # WxH+X+Y, for capture == "region"
    resolution: str = ""             # "1080p" (short side), "" = the monitor's own, or WxH
    fps: int = 60
    replay_seconds: int = 60
    replay_storage: str = "ram"
    container: str = "mp4"
    video_codec: str = "auto"
    quality: str = "very_high"       # the video quality level ("High"); see recorder.presets
    bitrate_kbps: int = 0            # for cbr: 0 = what the quality level comes to
    bitrate_mode: str = "cbr"
    framerate_mode: str = "vfr"
    color_range: str = "limited"
    audio_codec: str = "aac"         # AAC plays everywhere a clip gets shared
    audio_bitrate: int = 0           # kbps, 0 = recorder's default
    cursor: bool = True
    encoder: str = "gpu"
    keyframe_interval: float = 2.0
    restore_portal_session: bool = True
    output_dir: str = ""             # "" = the clip folder
    # The clip's audio tracks, as GSR's -a takes them ("default_output",
    # "default_input", "device:<node>", "app:<name>"); "" = no such track.
    # While a device is missing, its track records the default output or
    # input instead (gsr.available_tracks).
    game_audio: str = "default_output"
    chat_audio: str = ""
    mic_audio: str = "default_input"
    extra_args: str = ""


# --- The whole file ---------------------------------------------------------

@dataclass
class Config:
    clip_path: str = ""
    data_path: str = ""
    state_path: str = ""
    export_path: str = ""
    cache_path: str = ""
    keep_logs: bool = True      # write what Vertex does to the log folder (vertex.logs)
    log_path: str = ""          # "" = a logs folder in the state folder

    close_to_tray: bool = True
    colour_scheme: str = "navy"                                # a key of ui/theme.SCHEMES
    card_width: int = CARD_WIDTH_DEFAULT                       # see CARD_WIDTH_RANGE
    # The size last exported at (a label of media/export.SIZE_CHOICES); "" = none yet.
    export_size: str = ""
    # Desktop pop-ups switched away from their default, by kind (see notifications).
    notifications: dict[str, bool] = field(default_factory=dict)
    # Pop-ups through GPU Screen Recorder's notifier, over games, when it is installed.
    notify_over_games: bool = True

    recorder: RecorderConfig = field(default_factory=RecorderConfig)

    # How clip apps write the game and the time into names, as the user
    # taught Vertex (NamePattern.to_dict()), tried first to last.
    name_patterns: list[dict] = field(default_factory=list)

    def patterns(self) -> list[NamePattern]:
        return [p for p in map(NamePattern.from_dict, self.name_patterns) if p is not None]

    # --- Paths ---------------------------------------------------------------

    def resolved_clip_dir(self) -> str:
        return paths.normalize(self.clip_path)

    def resolved_export_dir(self) -> str:
        return paths.normalize(self.export_path)

    def resolved_data_dir(self) -> str:
        return paths.normalize(self.data_path) or str(paths.default_data_dir())

    def resolved_state_dir(self) -> str:
        return paths.normalize(self.state_path) or str(paths.default_state_dir())

    def resolved_cache_dir(self) -> str:
        return paths.normalize(self.cache_path) or str(paths.default_cache_dir())

    def resolved_log_dir(self) -> str:
        return paths.normalize(self.log_path) or os.path.join(self.resolved_state_dir(), "logs")

    def resolved_recording_dir(self) -> str:
        return paths.normalize(self.recorder.output_dir) or self.resolved_clip_dir()

    def is_complete(self) -> bool:
        """Every path set, and the clips folder reachable from this account.

        A blank field means a setting was added after this config was written.
        A clips folder that neither exists nor sits under this account's home is
        a config carried over from another machine, so setup re-derives it
        rather than leaving the app pointed at someone else's home directory.
        """
        if not all(paths.normalize(getattr(self, key)) for key in REQUIRED_FIELDS):
            return False
        clips = self.resolved_clip_dir()
        home = os.path.expanduser("~")
        return os.path.isdir(clips) or clips.startswith(home + os.sep)

    def missing_dirs(self) -> list[tuple[str, str]]:
        """Configured folders that are not on disk, as (key, path) pairs.

        Renamed, moved, or on a drive that is not mounted — none of which is the
        app's to guess at. Reported rather than recreated, because an empty
        folder in place of either of these is indistinguishable from a fresh
        install: the clips are not listed, or every tag looks lost while the
        real library sits safely somewhere else.
        """
        found = {"clip_path": self.resolved_clip_dir(), "data_path": self.resolved_data_dir()}
        return [(key, found[key]) for key in CHECKED_DIRS
                if found[key] and not os.path.isdir(found[key])]

    def ensure_dirs(self) -> list[str]:
        """Create the folders this config names. Returns the ones that failed."""
        failed = []
        for path in (self.resolved_clip_dir(), self.resolved_data_dir(),
                     self.resolved_state_dir(), self.resolved_cache_dir(),
                     self.resolved_export_dir()):
            if not path:
                continue
            try:
                paths.make_dir(path)
            except OSError:
                failed.append(path)
        return failed

    # --- Serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        config = _fill(cls(), data, skip=("recorder", "name_patterns"))
        taught = data.get("name_patterns")
        if isinstance(taught, list):
            config.name_patterns = [pattern.to_dict() for pattern in
                                    map(NamePattern.from_dict, taught) if pattern is not None]
        config.notifications = notifications.changed_choices(
            {kind: on for kind, on in config.notifications.items() if isinstance(on, bool)})
        config.card_width = min(max(config.card_width, CARD_WIDTH_RANGE[0]), CARD_WIDTH_RANGE[1])
        config.recorder = _fill(RecorderConfig(), data.get("recorder"))
        # Tidied, as Windows' own separators, but '~' kept as written.
        for owner, key in [*((config, key) for key in (*REQUIRED_FIELDS, "log_path")),
                           (config.recorder, "output_dir")]:
            value = getattr(owner, key).strip()
            setattr(owner, key, os.path.normpath(value) if value else "")
        return config

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> Config:
        """Read the config file. Raises OSError/ValueError if it is unreadable."""
        with open(path or paths.config_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("config.json does not hold an object")
        return cls.from_dict(data)

    @classmethod
    def load_or_default(cls, path: str | os.PathLike | None = None) -> Config:
        try:
            return cls.load(path)
        except (OSError, ValueError):
            return cls()

    def save(self, path: str | os.PathLike | None = None) -> None:
        """Write the file atomically, so a crash mid-save never truncates it."""
        target = Path(path or paths.config_path())
        paths.make_dir(target.parent)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.to_dict(), handle, indent=4)
                handle.write("\n")
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _fill(instance, data: Any, skip: tuple[str, ...] = ()):
    """Copy known keys from `data` onto a dataclass, keeping defaults on mismatch.

    A value of the wrong type is ignored rather than trusted: a hand-edited
    config should cost one setting, not a crash at startup.
    """
    if not isinstance(data, dict):
        return instance
    for item in dataclasses.fields(instance):
        if item.name in skip or item.name not in data:
            continue
        current = getattr(instance, item.name)
        value = data[item.name]
        if isinstance(current, bool):
            if isinstance(value, bool):
                setattr(instance, item.name, value)
        elif isinstance(current, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(instance, item.name, type(current)(value))
        elif isinstance(current, str):
            if isinstance(value, str):
                setattr(instance, item.name, value)
        elif isinstance(current, list):
            if isinstance(value, list):
                setattr(instance, item.name, [str(v) for v in value if isinstance(v, str)])
        elif isinstance(current, dict) and isinstance(value, dict):
            setattr(instance, item.name, dict(value))
    return instance


def default_config() -> Config:
    """A Config with every path filled in for the account running right now."""
    videos = paths.xdg_user_dir("VIDEOS", "~/Videos")
    clips = os.path.join(videos, CLIP_SUBDIR)
    return Config(
        clip_path=clips,
        data_path=str(paths.default_data_dir()),
        state_path=str(paths.default_state_dir()),
        export_path=os.path.join(clips, APP_NAME, "Exports"),
        cache_path=str(paths.default_cache_dir()),
    )


def needs_setup(path: str | os.PathLike | None = None) -> bool:
    """True when first-run setup has to run before the app is usable."""
    try:
        config = Config.load(path)
    except (OSError, ValueError):
        return True
    return not config.is_complete()
