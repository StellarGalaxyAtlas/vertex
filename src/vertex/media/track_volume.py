"""Each audio track's recording volume, set in a clip after it is saved.

OBS records a track at its volume; GPU Screen Recorder records devices as
they are, so Vertex sets the volume in the clip it saved instead. Only the
tracks whose volume changes are encoded again, in their own codec and at
their own bitrate; the video and every other track are copied as they are.
The clip is written under a staging name and moved into place.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from vertex.core.clips import staging_path
from vertex.media.ffmpeg import BASE, FFPROBE, MediaError, run_quiet
from vertex.media.trim import audio_titles
from vertex.platform import NO_WINDOW

# ffmpeg's encoder for each codec a recorder writes audio in.
ENCODERS = {"aac": "aac", "opus": "libopus", "flac": "flac", "mp3": "libmp3lame",
            "vorbis": "libvorbis"}
DEFAULT_BITRATE = 160_000      # bits/s, when the stream doesn't say


def changes(volumes: list[int]) -> dict[int, int]:
    """{audio position: percent} for the tracks not at 100%."""
    return {position: volume for position, volume in enumerate(volumes) if volume != 100}


def _audio_streams(clip_path: str) -> list[dict]:
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_name,bit_rate", "-of", "json", clip_path],
            capture_output=True, text=True, timeout=30, check=True, **NO_WINDOW)
        return json.loads(out.stdout).get("streams", [])
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        raise MediaError(f"Could not read the clip's audio: {exc}") from exc


def command(clip_path: str, out_path: str, volumes: dict[int, int], streams: list[dict],
            titles: dict[int, str]) -> list[str]:
    argv = [*BASE, "-v", "error", "-y", "-i", clip_path,
            "-map", "0:v", "-map", "0:a?", "-c", "copy"]
    for position, volume in sorted(volumes.items()):
        if position >= len(streams):
            continue
        stream = streams[position]
        codec = stream.get("codec_name", "")
        try:
            bitrate = int(stream.get("bit_rate") or DEFAULT_BITRATE)
        except ValueError:
            bitrate = DEFAULT_BITRATE
        argv += [f"-filter:a:{position}", f"volume={volume / 100:g}",
                 f"-c:a:{position}", ENCODERS.get(codec, "aac")]
        if codec != "flac":
            argv += [f"-b:a:{position}", str(bitrate)]
    # As in a trim: the mp4 muxer writes only the titles it is handed.
    for position, title in sorted(titles.items()):
        argv += [f"-metadata:s:a:{position}", f"title={title}"]
    if out_path.lower().endswith(".mp4"):
        argv += ["-movflags", "+faststart"]
    argv.append(out_path)
    return argv


def apply(clip_path: str, volumes: dict[int, int], timeout: float = 600) -> bool:
    """Set each track's volume ({audio position: percent}) in the clip.
    Returns whether the clip changed: not when every track stays at 100%."""
    volumes = {position: volume for position, volume in volumes.items() if volume != 100}
    if not volumes:
        return False
    streams = _audio_streams(clip_path)
    if not any(position < len(streams) for position in volumes):
        return False
    staged = staging_path(clip_path, "vertex-volume")
    try:
        run_quiet(command(clip_path, staged, volumes, streams, audio_titles(clip_path)),
                  timeout, "Could not set the tracks' volume")
        shutil.copystat(clip_path, staged)      # keep the time it was recorded
        os.replace(staged, clip_path)
    finally:
        if os.path.exists(staged):
            os.remove(staged)
    return True
