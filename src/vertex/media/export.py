"""Trim + mix a clip down to a shareable file, optionally under a size cap.

An export either keeps the source video untouched (the video stream is copied
and only the audio mix is re-encoded) or is sized to a byte budget. For a
budget, the bytes become a bitrate and the resolution steps down a ladder
until that bitrate looks reasonable; the encode is two-pass x264, because
single-pass CRF cannot hit a size and single-pass ABR overshoots on
high-motion gameplay.

`export_clip` is the whole job: it stages the output beside its destination
under a hidden name and moves it into place only once finished, so a
cancelled or failed export leaves nothing behind.
"""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from vertex.core.clips import staging_path
from vertex.media.ffmpeg import BASE, MediaError, ProgressFn, run_pass, run_quiet
from vertex.media.mixing import ffmpeg_graph
from vertex.media.probe import AudioTrack, MediaInfo
from vertex.media.trim import MIN_SELECTION, keyframe_before

MB = 1024 * 1024

# What the export sheet offers, as (label, byte cap). None = no cap: the source
# video is copied through untouched. 10/25/50/100 cover what chat platforms
# actually enforce on uploads.
SIZE_CHOICES: tuple[tuple[str, int | None], ...] = (
    ("Original", None),
    ("10 MB", 10 * MB),
    ("25 MB", 25 * MB),
    ("50 MB", 50 * MB),
    ("100 MB", 100 * MB),
)
# Quick export's size until one has been exported at from the export sheet.
QUICK_SIZE = "10 MB"


def size_choice(name: str, fallback: str = SIZE_CHOICES[0][0]) -> tuple[str, int | None]:
    """The size choice called `name`, or `fallback`'s when there is none."""
    sizes = dict(SIZE_CHOICES)
    name = name if name in sizes else fallback
    return name, sizes[name]


def apply_edit(edit, duration: float, tracks: Sequence[AudioTrack]) -> tuple[float, float]:
    """Set each track's saved volume and mute from the library's `edit` (a
    ClipEdit) and return the saved trim as (start, end), the whole clip if
    it has none. What the editor opens with, and what a quick export uses."""
    start, end = 0.0, duration
    if duration:
        if edit.trim_start is not None:
            start = max(0.0, min(edit.trim_start, duration))
        if edit.trim_end is not None:
            end = max(start + 0.1, min(edit.trim_end, duration))
    for track in tracks:
        saved = edit.mix_for(track.name)
        if saved is not None:
            track.volume, track.muted = max(0.0, min(1.5, saved.volume)), saved.muted
    return start, end

# Headroom for the container and x264 missing slightly. Measured overshoot on
# high-motion gameplay is ~5%, so 0.92 lands safely under.
BUDGET_MARGIN = 0.92
# Bits per pixel per frame that still looks acceptable on x264 'medium' for
# high-motion gameplay — above the usual film rule of thumb.
BITS_PER_PIXEL = 0.075
HEIGHT_LADDER = (1440, 1080, 900, 720, 540, 480, 360)
# How far above "looks fine" the bitrate may go with budget to spare.
QUALITY_CEILING = 2.5
AUDIO_KBPS = 128
AUDIO_KBPS_TIGHT = 64      # for long clips where the video needs every bit
MIN_VIDEO_KBPS = 150       # below this the result is not worth producing


@dataclass
class EncodePlan:
    width: int
    height: int
    fps: float
    video_kbps: int
    audio_kbps: int

    @property
    def summary(self) -> str:
        return f"{self.height}p{round(self.fps)} · {self.video_kbps} kbps"

    def estimate(self, duration: float) -> int:
        return int((self.video_kbps + self.audio_kbps) * 1000 * duration / 8)


def copy_estimate(info: MediaInfo, duration: float) -> int:
    """Bytes a stream copy of `duration` seconds would take; 0 when unknown."""
    if info.bitrate <= 0 or duration <= 0:
        return 0
    return int(info.bitrate * duration / 8)


def plan(duration: float, width: int, height: int, fps: float,
         has_audio: bool = True, limit: int = 50 * MB) -> EncodePlan:
    """Pick resolution and bitrates that fit `duration` seconds into `limit` bytes."""
    if duration <= 0:
        raise MediaError("Nothing is selected to export.")
    if not width or not height:
        raise MediaError("The clip has no video stream.")

    total_kbps = limit * 8 * BUDGET_MARGIN / 1000.0 / duration
    for audio_kbps in ((AUDIO_KBPS, AUDIO_KBPS_TIGHT) if has_audio else (0,)):
        video_kbps = total_kbps - audio_kbps
        if video_kbps >= MIN_VIDEO_KBPS:
            break
    else:
        raise MediaError(f"{duration:.0f}s is too long to fit in {limit // MB} MB — "
                         "trim it shorter.")

    aspect = width / height

    def needed_kbps(h: int) -> float:
        return h * aspect * h * fps * BITS_PER_PIXEL / 1000.0

    candidates = [h for h in HEIGHT_LADDER if h <= height] or [min(HEIGHT_LADDER)]
    chosen = candidates[-1]
    for candidate in candidates:
        if needed_kbps(candidate) <= video_kbps:
            chosen = candidate
            break
    # A short clip can afford more bitrate than its resolution can use; the
    # ceiling keeps a 5s export well under the cap rather than at it.
    video_kbps = min(video_kbps, needed_kbps(chosen) * QUALITY_CEILING)
    out_width = round(chosen * aspect) // 2 * 2   # x264 needs even sizes
    return EncodePlan(width=out_width, height=chosen, fps=fps,
                      video_kbps=int(video_kbps), audio_kbps=int(audio_kbps))


def two_pass_commands(clip_path: str, out_path: str, start: float, duration: float,
                      tracks: Sequence[AudioTrack], plan_: EncodePlan,
                      logfile: str) -> tuple[list[str], list[str]]:
    """The two ffmpeg passes. Pass 1 is video-only; pass 2 muxes the mix in."""
    video = f"[0:v]scale={plan_.width}:{plan_.height}:flags=bicubic,format=yuv420p[vo]"
    mix = ffmpeg_graph(tracks)
    common = [*BASE, "-y", "-ss", f"{start:.3f}", "-i", clip_path, "-t", f"{duration:.3f}",
              "-progress", "pipe:1", "-nostats"]
    codec = ["-c:v", "libx264", "-preset", "medium", "-b:v", f"{plan_.video_kbps}k",
             "-maxrate", f"{int(plan_.video_kbps * 1.5)}k",
             "-bufsize", f"{plan_.video_kbps * 2}k", "-passlogfile", logfile]
    first = [*common, "-filter_complex", video, "-map", "[vo]", *codec,
             "-pass", "1", "-an", "-f", "null", os.devnull]
    graph = video if mix is None else f"{video};{mix}"
    second = [*common, "-filter_complex", graph, "-map", "[vo]"]
    if mix is not None:
        second += ["-map", "[ao]", "-c:a", "aac", "-b:a", f"{plan_.audio_kbps}k", "-ac", "2"]
    else:
        second += ["-an"]
    second += [*codec, "-pass", "2", "-movflags", "+faststart", "-f", "mp4", out_path]
    return first, second


def copy_command(clip_path: str, out_path: str, start: float, end: float,
                 tracks: Sequence[AudioTrack]) -> tuple[list[str], float]:
    """One pass that keeps the source video and only mixes the audio.

    The cut starts at the keyframe at or before `start`, as with a trim. Both
    streams are seeked there — otherwise the re-encoded audio would start at
    `start` exactly and leave the head of the export silent. Returns the
    command and the span it actually covers, for reading its progress.
    """
    start = keyframe_before(clip_path, start)
    duration = max(0.0, end - start)
    mix = ffmpeg_graph(tracks)
    argv = [*BASE, "-y", "-ss", f"{start:.3f}", "-i", clip_path, "-t", f"{duration:.3f}",
            "-progress", "pipe:1", "-nostats"]
    if mix is None:
        argv += ["-map", "0:v", "-an"]
    else:
        argv += ["-filter_complex", mix, "-map", "0:v", "-map", "[ao]",
                 "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "2"]
    argv += ["-c:v", "copy", "-avoid_negative_ts", "make_zero",
             "-movflags", "+faststart", "-f", "mp4", out_path]
    return argv, duration


def encode(clip_path: str, out_path: str, start: float, end: float,
           tracks: Sequence[AudioTrack], info: MediaInfo, limit: int | None,
           on_progress: ProgressFn | None = None,
           cancel: threading.Event | None = None) -> int:
    """Write [start, end] of the clip to `out_path`. Returns its size.

    `limit=None` copies the source video through; otherwise the result stays
    under `limit` bytes. Blocking; call from a worker thread.
    """
    duration = max(0.0, end - start)
    if duration < MIN_SELECTION:
        raise MediaError("The selection is too short to export.")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if limit is None:
        argv, span = copy_command(clip_path, out_path, start, end, tracks)
        run_pass(argv, span, on_progress, 0.0, 1.0, cancel)
        return os.path.getsize(out_path)

    plan_ = plan(duration, info.width, info.height, info.fps,
                 ffmpeg_graph(tracks) is not None, limit)
    with tempfile.TemporaryDirectory(prefix="vertex-export-") as workdir:
        logfile = os.path.join(workdir, "passlog")
        first, second = two_pass_commands(clip_path, out_path, start, duration, tracks,
                                          plan_, logfile)
        run_pass(first, duration, on_progress, 0.0, 0.5, cancel)
        run_pass(second, duration, on_progress, 0.5, 0.5, cancel)
        size = os.path.getsize(out_path)
        if size > limit:
            # x264 overshot (rare; very short high-motion cuts). Re-run pass 2
            # at the bitrate the first attempt implies.
            plan_.video_kbps = max(MIN_VIDEO_KBPS,
                                   int(plan_.video_kbps * limit * BUDGET_MARGIN / size))
            _, retry = two_pass_commands(clip_path, out_path, start, duration, tracks,
                                         plan_, logfile)
            run_pass(retry, duration, on_progress, 0.5, 0.5, cancel)
            size = os.path.getsize(out_path)
    return size


def size_label(limit: int | None) -> str:
    for label, value in SIZE_CHOICES:
        if value == limit:
            return label
    return "Original" if limit is None else f"{limit // MB} MB"


def export_target(folder: str, clip_name: str, limit: int | None) -> str:
    """A free '<stem> (<size>).mp4' name in `folder` for this export."""
    stem = os.path.splitext(os.path.basename(clip_name))[0]
    base = f"{stem} ({size_label(limit).replace(' ', '')})"
    candidate = os.path.join(folder, f"{base}.mp4")
    count = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{base} {count}.mp4")
        count += 1
    return candidate


@dataclass
class ExportResult:
    path: str
    size: int
    limit: int | None

    @property
    def over_limit(self) -> bool:
        return self.limit is not None and self.size > self.limit


def export_clip(clip_path: str, clip_name: str, folder: str, start: float, end: float,
                tracks: Sequence[AudioTrack], info: MediaInfo, limit: int | None,
                on_progress: ProgressFn | None = None,
                cancel: threading.Event | None = None) -> ExportResult:
    """Export into `folder`, staged so nothing half-written is ever visible."""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise MediaError(f"Could not open the export folder: {exc}") from exc
    final = export_target(folder, clip_name, limit)
    staged = staging_path(final, "vertex-export")
    try:
        size = encode(clip_path, staged, start, end, tracks, info, limit, on_progress, cancel)
        os.replace(staged, final)
    except OSError as exc:
        _remove(staged)
        raise MediaError(f"Could not save the export: {exc}") from exc
    except BaseException:
        _remove(staged)
        raise
    return ExportResult(final, size, limit)


def grab_frame(clip_path: str, seconds: float, out_path: str, width: int = 480) -> str:
    """Write one frame from `seconds` into `out_path` (a JPEG preview)."""
    run_quiet([*BASE, "-v", "error", "-y", "-ss", f"{max(0.0, seconds):.3f}", "-i", clip_path,
               "-frames:v", "1", "-vf", f"scale={width}:-2", out_path],
              30, "Could not read a preview frame")
    return out_path


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
