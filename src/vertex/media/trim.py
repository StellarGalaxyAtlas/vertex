"""Lossless trims: cut a clip without re-encoding anything."""

from __future__ import annotations

import os
import subprocess

from vertex.media.ffmpeg import BASE, FFPROBE, MediaError, run_quiet
from vertex.media.probe import probe

# How far back to look for the keyframe before a cut point. Recorders key every
# couple of seconds; beyond this the search costs more than the seek saves.
KEYFRAME_WINDOW = 30.0
MIN_SELECTION = 0.05


def keyframe_before(clip_path: str, seconds: float, window: float = KEYFRAME_WINDOW) -> float:
    """Timestamp of the last video keyframe at or before `seconds`.

    Falls back to `seconds` itself when the packets cannot be read, which is
    no worse than not having looked.
    """
    seconds = max(0.0, seconds)
    if seconds <= 0:
        return 0.0
    low = max(0.0, seconds - window)
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "packet=pts_time,flags",
             "-read_intervals", f"{low:.3f}%{seconds + 0.05:.3f}",
             "-of", "csv=p=0", clip_path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return seconds
    best = None
    for line in out.splitlines():
        stamp_text, _, flags = line.partition(",")
        if "K" not in flags:
            continue
        try:
            stamp = float(stamp_text)
        except ValueError:
            continue
        if stamp <= seconds + 0.001 and (best is None or stamp > best):
            best = stamp
    return seconds if best is None else best


def audio_titles(clip_path: str) -> dict[int, str]:
    """{audio position: title} for streams that really carry a name.

    Streams without one are left out: inventing "Audio N" into a file that
    never had it would be a change, not a copy.
    """
    try:
        info = probe(clip_path)
    except MediaError:
        return {}
    return {track.index: track.name for track in info.tracks if track.has_name}


def trim_command(clip_path: str, out_path: str, start: float, end: float,
                 titles: dict[int, str]) -> list[str]:
    duration = max(0.0, end - start)
    argv = [
        *BASE, "-v", "error", "-y",
        "-ss", f"{max(0.0, start):.3f}", "-i", clip_path, "-t", f"{duration:.3f}",
        # Every stream, not ffmpeg's one-per-type default; "?" lets a clip with
        # no audio through.
        "-map", "0:v", "-map", "0:a?", "-c", "copy",
        # Input seeking leaves the first packets with negative timestamps;
        # without this the copy starts with a stutter or silent audio.
        "-avoid_negative_ts", "make_zero",
    ]
    # The mp4 muxer only writes stream titles it is given explicitly, so hand
    # each track its name back or the mixer would show "Audio 1/2/3".
    for position, title in sorted(titles.items()):
        argv += [f"-metadata:s:a:{position}", f"title={title}"]
    if out_path.lower().endswith(".mp4"):
        argv += ["-movflags", "+faststart"]
    argv.append(out_path)
    return argv


def trim(clip_path: str, out_path: str, start: float, end: float, timeout: float = 600) -> int:
    """Cut [start, end] out of the clip, keeping every stream bit-for-bit.

    The result keeps the source quality and every audio track, so it can be
    opened and mixed again with no generation loss. Stream copying can only
    begin on a keyframe, so playback starts at the keyframe at or before
    `start`; the end is exact. Returns the new file's size.
    """
    if end - start < MIN_SELECTION:
        raise MediaError("The selection is too short to trim.")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    argv = trim_command(clip_path, out_path, start, end, audio_titles(clip_path))
    run_quiet(argv, timeout, "Could not trim the clip")
    return os.path.getsize(out_path)
