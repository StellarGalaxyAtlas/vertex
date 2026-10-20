"""What is inside a clip: dimensions, frame rate, duration and audio tracks."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from vertex.media import mp4meta
from vertex.media.ffmpeg import FFPROBE, MediaError
from vertex.platform import NO_WINDOW


@dataclass
class AudioTrack:
    """One audio stream of a clip, with the user's mixer settings."""

    index: int              # 0-based position among the clip's audio streams
    name: str               # the recorder's name for it, from the stream tags
    label: str = ""         # what the mixer shows; see media.tracks
    channel: str = ""       # the part it holds, when recognised ("game", "mic", …)
    volume: float = 1.0     # linear gain, 0..1.5
    muted: bool = False
    has_name: bool = True   # False when `name` is our "Audio N" placeholder

    @property
    def gain(self) -> float:
        return 0.0 if self.muted else round(max(0.0, self.volume), 3)

    @property
    def audible(self) -> bool:
        return not self.muted and self.volume > 0


@dataclass
class MediaInfo:
    width: int = 0
    height: int = 0
    fps: float = 60.0
    duration: float = 0.0
    bitrate: float = 0.0      # bits/s over the whole file, video and audio
    tracks: list[AudioTrack] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return f"{self.height}p{round(self.fps)}" if self.height else ""


# MP4 handlers that name the muxer's boilerplate rather than the source, so
# they say nothing about what was recorded. SteelSeries Moments writes
# "Game"/"Chat"/"Mic" there instead, which is worth keeping.
GENERIC_HANDLERS = frozenset({"soundhandler", "sound media handler",
                              "videohandler", "core media audio"})


def track_name(tags: dict, position: int) -> tuple[str, bool]:
    """Best name for an audio stream from its tags, and whether it had one.

    Recorders disagree on where the source belongs: GPU Screen Recorder puts
    it in `title`, some builds in `name`, SteelSeries Moments in the handler.
    `name` is read first and must stay first: the library keys each track's
    saved volume by this string, so changing the order would orphan them.
    """
    handler = tags.get("handler_name", "") or ""
    if handler.strip().casefold() in GENERIC_HANDLERS:
        handler = ""
    name = tags.get("name") or tags.get("title") or handler
    if name:
        return name, True
    return f"Audio {position}", False


def _fraction(text, default: float = 60.0) -> float:
    try:
        if "/" in str(text):
            num, den = str(text).split("/", 1)
            return float(num) / float(den) if float(den) else default
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_probe(data: dict) -> MediaInfo:
    """Turn ffprobe's JSON into a MediaInfo. Separate from `probe` for testing."""
    info = MediaInfo()
    fmt = data.get("format", {}) or {}
    info.duration = _number(fmt.get("duration"))
    info.bitrate = _number(fmt.get("bit_rate"))
    if info.bitrate <= 0 and info.duration > 0:
        # Some muxers leave bit_rate out; size over duration is the same number.
        info.bitrate = _number(fmt.get("size")) * 8 / info.duration

    position = 0
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and not info.width:
            info.width = int(stream.get("width") or 0)
            info.height = int(stream.get("height") or 0)
            info.fps = _fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
            if info.fps <= 0 or info.fps > 1000:
                info.fps = _fraction(stream.get("r_frame_rate"))
        elif kind == "audio":
            position += 1
            name, named = track_name(stream.get("tags", {}) or {}, position)
            info.tracks.append(AudioTrack(index=position - 1, name=name, has_name=named))
    return info


def probe(clip_path: str, timeout: float = 30) -> MediaInfo:
    """Read dimensions, fps, duration and audio tracks via ffprobe."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries",
             "stream=index,codec_type,width,height,r_frame_rate,avg_frame_rate"
             ":stream_tags=name,title,handler_name:format=duration,size,bit_rate",
             "-of", "json", clip_path],
            capture_output=True, text=True, timeout=timeout, check=True, **NO_WINDOW,
        ).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        raise MediaError(f"Could not read the clip: {exc}") from exc
    info = parse_probe(data)
    if any(not track.has_name for track in info.tracks):
        _fill_mp4_names(clip_path, info)
    return info


def _fill_mp4_names(clip_path: str, info: MediaInfo) -> None:
    """Take titles ffprobe could not see from the file's own track boxes."""
    names = mp4meta.audio_track_names(clip_path)
    if len(names) != len(info.tracks):
        return            # the boxes disagree with ffprobe; trust neither
    for track, name in zip(info.tracks, names, strict=True):
        if not track.has_name and name:
            track.name, track.has_name = name, True


def duration(clip_path: str, timeout: float = 15) -> float | None:
    """Just the duration, cheaply. None when it cannot be read."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", clip_path],
            capture_output=True, text=True, timeout=timeout, **NO_WINDOW,
        ).stdout
        value = float(out.strip())
    except (ValueError, subprocess.SubprocessError, OSError):
        return None
    return value if value > 0 else None
