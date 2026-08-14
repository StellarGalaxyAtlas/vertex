"""Trim + mix a clip down to a shareable file, optionally under a size cap.

An export either keeps the source video untouched (the video stream is copied
and only the audio mix is re-encoded) or is sized to a byte budget the caller
picks. For a budget, the bytes are turned into a bitrate and the resolution is
stepped down the ladder until that bitrate is enough to look reasonable; the
encode is two-pass x264, because single-pass CRF cannot hit a size target and
single-pass ABR overshoots on high-motion gameplay.

No GUI dependencies here, so the sizing maths can be exercised on its own.
"""

import array
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field


MB = 1024 * 1024

# array('h') is the machine's byte order; ffmpeg is asked for little-endian.
BIG_ENDIAN = sys.byteorder == "big"

SIZE_LIMIT = 50 * MB

# What the export window offers, as (label, byte cap). `None` means no cap: the
# source video is copied through untouched. 25/50/100 cover the tiers the chat
# platforms actually enforce.
SIZE_CHOICES = (
    ("Original", None),
    ("25 MB", 25 * MB),
    ("50 MB", 50 * MB),
    ("100 MB", 100 * MB),
)

# Leave headroom for the MP4 container and for x264 missing the target slightly.
# Measured overshoot on high-motion gameplay is ~5%, so 0.92 lands safely under.
BUDGET_MARGIN = 0.92

# Bits per pixel per frame that still looks acceptable on x264 'medium'.
# Gameplay is high-motion, so this sits above the usual film rule of thumb.
BITS_PER_PIXEL = 0.075

# Heights the export may step down to. Never upscales past the source.
HEIGHT_LADDER = (1440, 1080, 900, 720, 540, 480, 360)

# Ceiling on how far above "looks fine" the bitrate may go when there is budget
# to spare, as a multiple of BITS_PER_PIXEL.
QUALITY_CEILING = 2.5

AUDIO_KBPS = 128
AUDIO_KBPS_TIGHT = 64      # for long clips where video needs every bit
MIN_VIDEO_KBPS = 150       # below this the result is not worth producing


class ExportError(Exception):
    pass


@dataclass
class AudioTrack:
    """One audio stream of the clip, with the user's mixer settings."""

    index: int              # 0-based position among audio streams
    name: str               # raw device name from the file's stream tags
    label: str = ""         # what the mixer shows; assigned by player.py
    volume: float = 1.0     # linear gain
    muted: bool = False

    @property
    def gain(self):
        return 0.0 if self.muted else round(max(0.0, self.volume), 3)


@dataclass
class MediaInfo:
    width: int = 0
    height: int = 0
    fps: float = 60.0
    duration: float = 0.0
    bitrate: float = 0.0    # bits/s over the whole file, video and audio
    tracks: list = field(default_factory=list)

    @property
    def summary(self):
        return f"{self.height}p{round(self.fps)}" if self.height else ""


@dataclass
class ExportPlan:
    width: int
    height: int
    fps: float
    video_kbps: int
    audio_kbps: int

    @property
    def summary(self):
        return f"{self.height}p{round(self.fps)} · {self.video_kbps} kbps"


def _parse_fraction(text, default=60.0):
    try:
        if "/" in str(text):
            num, den = str(text).split("/", 1)
            return float(num) / float(den) if float(den) else default
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return default


# MP4 track handlers that name the muxer's boilerplate rather than the source,
# so they say nothing about what was recorded. GPU Screen Recorder writes
# "SoundHandler" on every track; SteelSeries Moments writes "Game"/"Chat"/"Mic".
GENERIC_HANDLERS = frozenset({"soundhandler", "sound media handler",
                              "videohandler", "core media audio"})


def track_name(tags, position):
    """Best name for an audio stream from its tags, or a plain 'Audio N'.

    Recorders disagree on where the source belongs: GPU Screen Recorder puts it
    in `name`, SteelSeries Moments in the MP4 handler, others in `title`.
    """
    handler = tags.get("handler_name", "")
    if handler.strip().casefold() in GENERIC_HANDLERS:
        handler = ""
    return tags.get("name") or tags.get("title") or handler or f"Audio {position}"


def probe(clip_path):
    """Read dimensions, fps, duration and audio tracks via ffprobe."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=index,codec_type,width,height,r_frame_rate"
             ":stream_tags=name,title,handler_name"
             ":format=duration,size,bit_rate",
             "-of", "json", clip_path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        raise ExportError(f"Could not read clip: {exc}") from exc

    info = MediaInfo()
    fmt = data.get("format", {})
    try:
        info.duration = float(fmt.get("duration", 0.0))
    except (TypeError, ValueError):
        info.duration = 0.0
    try:
        info.bitrate = float(fmt.get("bit_rate", 0.0))
    except (TypeError, ValueError):
        info.bitrate = 0.0
    if info.bitrate <= 0 and info.duration > 0:
        # Some muxers leave bit_rate out of the container header; the file's own
        # size over its duration is the same number for our purposes.
        try:
            info.bitrate = float(fmt.get("size", 0.0)) * 8 / info.duration
        except (TypeError, ValueError):
            info.bitrate = 0.0

    audio_pos = 0
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        tags = stream.get("tags", {}) or {}
        if kind == "video" and not info.width:
            info.width = int(stream.get("width") or 0)
            info.height = int(stream.get("height") or 0)
            info.fps = _parse_fraction(stream.get("r_frame_rate"), 60.0)
        elif kind == "audio":
            info.tracks.append(
                AudioTrack(index=audio_pos, name=track_name(tags, audio_pos + 1))
            )
            audio_pos += 1
    return info


# --- Waveforms -------------------------------------------------------------
# What the editor draws inside each audio lane. Decoding at the source rate
# would be wasted work: a lane is a couple of thousand pixels wide at most, so
# 4 kHz mono still leaves ~100 samples behind every pixel column, and a minute
# of it decodes in well under a second.
PEAK_RATE = 4000
PEAK_BUCKETS = 2000
FULL_SCALE = 32768.0


def peaks(clip_path, index, duration, buckets=PEAK_BUCKETS, cancel=None):
    """Peak level per time slice of one audio stream, as `buckets` floats 0-1.

    Empty when the stream will not decode, and empty on cancellation: a
    waveform is decoration, and a caller that cannot have one draws a plain
    lane rather than reporting a failure at the user.

    The PCM is reduced as it arrives rather than collected. A long clip's audio
    runs to tens of megabytes and none of it is wanted once its bucket has a
    peak, so this holds one 64 KB read at a time however long the clip is.

    Blocking; call from a worker thread. `cancel` is an Event — it kills the
    decode, which matters because the editor can be closed while one is
    running.
    """
    if duration <= 0 or buckets <= 0:
        return []
    argv = [
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error",
        "-i", clip_path, "-map", f"0:a:{index}", "-vn",
        "-ac", "1", "-ar", str(PEAK_RATE), "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
    except OSError:
        return []

    per_bucket = max(1, round(duration * PEAK_RATE / buckets))
    levels, peak, filled, tail = [], 0, 0, b""
    try:
        while True:
            chunk = proc.stdout.read(1 << 16)
            if not chunk:
                break
            if cancel is not None and cancel.is_set():
                proc.kill()
                return []
            # s16le is two bytes a sample and a pipe read can split one.
            data = tail + chunk
            usable = len(data) - len(data) % 2
            tail, data = data[usable:], data[:usable]
            samples = array.array("h")
            samples.frombytes(data)
            if BIG_ENDIAN:
                samples.byteswap()

            at = 0
            while at < len(samples):
                take = min(per_bucket - filled, len(samples) - at)
                window = samples[at:at + take]
                peak = max(peak, max(window), -min(window))
                at += take
                filled += take
                if filled >= per_bucket:
                    levels.append(min(1.0, peak / FULL_SCALE))
                    peak, filled = 0, 0
        proc.wait(timeout=10)
    except (subprocess.SubprocessError, OSError, ValueError):
        return []
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        return []      # no such stream, or a codec this build cannot decode
    if filled:
        levels.append(min(1.0, peak / FULL_SCALE))
    return levels


def copy_estimate(info, duration):
    """Bytes a stream copy of `duration` seconds of this clip would come to.

    A copy carries the source's own bitrate, so the size follows the length of
    the selection instead of any fixed budget. 0 when the bitrate is unknown,
    which reads as "don't claim a number".
    """
    if info.bitrate <= 0 or duration <= 0:
        return 0
    return int(info.bitrate * duration / 8)


def plan(duration, width, height, fps, has_audio=True, limit=SIZE_LIMIT):
    """Pick resolution and bitrates that fit `duration` seconds into `limit` bytes."""
    if duration <= 0:
        raise ExportError("Nothing selected to export.")
    if not width or not height:
        raise ExportError("Clip has no video stream.")

    budget_kbits = limit * 8 * BUDGET_MARGIN / 1000.0
    total_kbps = budget_kbits / duration

    for audio_kbps in ([AUDIO_KBPS, AUDIO_KBPS_TIGHT] if has_audio else [0]):
        video_kbps = total_kbps - audio_kbps
        if video_kbps >= MIN_VIDEO_KBPS:
            break
    else:
        raise ExportError(
            f"{duration:.0f}s is too long to fit in "
            f"{limit // (1024 * 1024)} MB — trim it shorter."
        )

    aspect = width / height

    def needed_kbps(h):
        return h * aspect * h * fps * BITS_PER_PIXEL / 1000.0

    # Largest height whose "looks fine" bitrate fits the budget; the smallest
    # rung is the floor, so a very long clip still produces something.
    candidates = [h for h in HEIGHT_LADDER if h <= height] or [min(HEIGHT_LADDER)]
    chosen = candidates[-1]
    for candidate in candidates:
        if needed_kbps(candidate) <= video_kbps:
            chosen = candidate
            break

    # A short clip can afford far more bitrate than its resolution can use.
    # Spending it produces a needlessly large file for no visible gain, and the
    # cap is what keeps a 5s export well under the limit rather than at it.
    video_kbps = min(video_kbps, needed_kbps(chosen) * QUALITY_CEILING)

    out_width = int(round(chosen * aspect)) // 2 * 2   # x264 needs even dimensions
    return ExportPlan(
        width=out_width, height=chosen, fps=fps,
        video_kbps=int(video_kbps), audio_kbps=int(audio_kbps),
    )


def grab_frame(clip_path, seconds, out_path, width=480):
    """Write a single frame from `seconds` into out_path (a JPEG preview)."""
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
             "-ss", f"{max(0.0, seconds):.3f}", "-i", clip_path,
             "-frames:v", "1", "-vf", f"scale={width}:-2", out_path],
            capture_output=True, timeout=30, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise ExportError(f"Could not read a preview frame: {exc}") from exc
    return out_path


def _audio_titles(clip_path):
    """Per-audio-stream source names, as {position: title}.

    Only streams that really carry a name are listed — `probe` invents "Audio N"
    for the rest, and inventing one into a file that never had it would be a
    change, not a copy.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream_tags=name,title", "-of", "json", clip_path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        streams = json.loads(out).get("streams", [])
    except (subprocess.SubprocessError, OSError, ValueError):
        return {}
    titles = {}
    for position, stream in enumerate(streams):
        tags = stream.get("tags", {}) or {}
        title = tags.get("name") or tags.get("title")
        if title:
            titles[position] = title
    return titles


def trim(clip_path, out_path, start, end, timeout=600):
    """Cut [start, end] out of the clip without re-encoding anything.

    Unlike `run` (which sizes a clip down for sharing), this keeps the source
    resolution, bitrate and *every* audio stream bit-for-bit, so the result can
    be opened in the editor and mixed again later with no generation loss.

    The price of stream copying is that the cut can only begin on a keyframe, so
    playback starts at the keyframe at or before `start` — up to a couple of
    seconds of extra head. The end is exact. Returns the new file's size.
    """
    duration = max(0.0, end - start)
    if duration < 0.05:
        raise ExportError("Selection is too short to trim.")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    argv = [
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-ss", f"{max(0.0, start):.3f}", "-i", clip_path,
        "-t", f"{duration:.3f}",
        # Every video and audio stream, not just ffmpeg's one-per-type default.
        # "?" keeps a clip with no audio from failing the map outright.
        "-map", "0:v", "-map", "0:a?", "-c", "copy",
        # Input seeking leaves the first packets with negative timestamps;
        # without this the copy starts with a stutter or silent audio.
        "-avoid_negative_ts", "make_zero",
    ]
    # The mp4 muxer only writes stream names it is given explicitly, so a plain
    # copy would leave the mixer showing "Audio 1/2" instead of the capture
    # sources. Hand each one its original name back.
    for position, title in _audio_titles(clip_path).items():
        argv += [f"-metadata:s:a:{position}", f"title={title}"]
    argv += ["-movflags", "+faststart", out_path]
    try:
        subprocess.run(argv, capture_output=True, timeout=timeout, check=True)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or b"").decode(errors="replace").strip()
        raise ExportError(tail.splitlines()[-1] if tail else "ffmpeg failed.") from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise ExportError(f"Could not trim the clip: {exc}") from exc
    return os.path.getsize(out_path)


def audio_filter(tracks, label="ao"):
    """filter_complex fragment mixing the enabled tracks at their gains."""
    live = [t for t in tracks if not t.muted and t.volume > 0]
    if not live:
        return None
    if len(live) == 1:
        track = live[0]
        return f"[0:a:{track.index}]volume={track.gain}[{label}]"
    nodes = "".join(
        f"[0:a:{t.index}]volume={t.gain}[m{i}];" for i, t in enumerate(live)
    )
    joined = "".join(f"[m{i}]" for i in range(len(live)))
    return f"{nodes}{joined}amix=inputs={len(live)}:normalize=0[{label}]"


def build_commands(clip_path, out_path, start, duration, tracks, plan_, logfile):
    """The two ffmpeg passes. Pass 1 is video-only; pass 2 muxes the mix in."""
    scale = f"scale={plan_.width}:{plan_.height}:flags=bicubic"
    video_chain = f"[0:v]{scale},format=yuv420p[vo]"
    amix = audio_filter(tracks)

    common = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-ss", f"{start:.3f}", "-i", clip_path, "-t", f"{duration:.3f}",
        "-progress", "pipe:1", "-nostats",
    ]
    codec = [
        "-c:v", "libx264", "-preset", "medium",
        "-b:v", f"{plan_.video_kbps}k",
        "-maxrate", f"{int(plan_.video_kbps * 1.5)}k",
        "-bufsize", f"{plan_.video_kbps * 2}k",
        "-passlogfile", logfile,
    ]

    first = common + ["-filter_complex", video_chain, "-map", "[vo]"] + codec + [
        "-pass", "1", "-an", "-f", "null", os.devnull,
    ]

    graph = video_chain if amix is None else f"{video_chain};{amix}"
    second = common + ["-filter_complex", graph, "-map", "[vo]"]
    if amix is not None:
        second += ["-map", "[ao]", "-c:a", "aac",
                   "-b:a", f"{plan_.audio_kbps}k", "-ac", "2"]
    else:
        second += ["-an"]
    second += codec + ["-pass", "2", "-movflags", "+faststart", out_path]
    return first, second


# How far back to look for the keyframe before a cut point. Recorders key every
# few seconds; beyond this the search costs more than the seek saves.
KEYFRAME_WINDOW = 30.0


def keyframe_before(clip_path, seconds, window=KEYFRAME_WINDOW):
    """Timestamp of the last video keyframe at or before `seconds`.

    Falls back to `seconds` itself when the packets cannot be read, which is no
    worse than not having looked.
    """
    seconds = max(0.0, seconds)
    if seconds <= 0:
        return 0.0
    lo = max(0.0, seconds - window)
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "packet=pts_time,flags",
             "-read_intervals", f"{lo:.3f}%{seconds + 0.05:.3f}",
             "-of", "csv=p=0", clip_path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return seconds

    best = None
    for line in out.splitlines():
        time_text, _, flags = line.partition(",")
        if "K" not in flags:
            continue
        try:
            stamp = float(time_text)
        except ValueError:
            continue
        if stamp <= seconds + 0.001 and (best is None or stamp > best):
            best = stamp
    return seconds if best is None else best


def build_copy_command(clip_path, out_path, start, end, tracks):
    """One ffmpeg pass that keeps the source video and only mixes the audio.

    This is what "Original" exports: no scaling, no re-encode, so the picture is
    bit-for-bit what was recorded. The price of copying is that the cut can only
    begin on a keyframe, so it starts at the keyframe at or before `start` — up
    to a couple of seconds of extra head, as with `trim`. The end is exact.

    Both streams are seeked to that keyframe rather than the video alone: the
    audio is re-encoded through the mixer and would otherwise be cut at `start`
    exactly, leaving the head of the export silent.

    Returns the command and the span it actually covers, which the caller needs
    to read the progress ffmpeg reports.
    """
    start = keyframe_before(clip_path, start)
    duration = max(0.0, end - start)
    amix = audio_filter(tracks)
    argv = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-ss", f"{start:.3f}", "-i", clip_path, "-t", f"{duration:.3f}",
        "-progress", "pipe:1", "-nostats",
    ]
    if amix is None:
        argv += ["-map", "0:v", "-an"]
    else:
        argv += ["-filter_complex", amix, "-map", "0:v", "-map", "[ao]",
                 "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "2"]
    argv += [
        "-c:v", "copy",
        # Input seeking leaves the first packets with negative timestamps;
        # without this the copy starts with a stutter or silent audio.
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart", out_path,
    ]
    return argv, duration


_TIME_RE = re.compile(rb"out_time_us=(\d+)")


def _run_pass(argv, duration, on_progress, base, span, cancel):
    """Run one ffmpeg pass, reporting progress into [base, base+span]."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise ExportError("Export cancelled.")
            match = _TIME_RE.search(line)
            if match and on_progress and duration > 0:
                done = min(1.0, int(match.group(1)) / 1_000_000 / duration)
                on_progress(base + span * done)
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        tail = (proc.stderr.read() or b"").decode(errors="replace").strip()
        raise ExportError(tail.splitlines()[-1] if tail else "ffmpeg failed.")


def run(clip_path, out_path, start, end, tracks, info,
        limit=SIZE_LIMIT, on_progress=None, cancel=None):
    """Export [start, end] of the clip to out_path, staying under `limit` bytes.

    `limit=None` exports at the source's own quality instead, copying the video
    stream through — the file is then as large as the selection makes it.

    Blocking; call from a worker thread. `on_progress` receives 0.0-1.0 and is
    likewise called on that thread. Returns the finished file's size in bytes.
    """
    duration = max(0.0, end - start)
    if duration < 0.05:
        raise ExportError("Selection is too short to export.")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if limit is None:
        argv, span = build_copy_command(clip_path, out_path, start, end, tracks)
        _run_pass(argv, span, on_progress, 0.0, 1.0, cancel)
        return os.path.getsize(out_path)

    has_audio = audio_filter(tracks) is not None
    plan_ = plan(duration, info.width, info.height, info.fps, has_audio, limit)

    with tempfile.TemporaryDirectory(prefix="gsm-export-") as workdir:
        logfile = os.path.join(workdir, "passlog")
        first, second = build_commands(
            clip_path, out_path, start, duration, tracks, plan_, logfile
        )
        _run_pass(first, duration, on_progress, 0.0, 0.5, cancel)
        _run_pass(second, duration, on_progress, 0.5, 0.5, cancel)

        size = os.path.getsize(out_path)
        if size > limit:
            # x264 overshot (rare, but happens on very short high-motion cuts).
            # Re-run pass 2 scaled to the bitrate the first attempt implies.
            shrink = (limit * BUDGET_MARGIN) / size
            plan_.video_kbps = max(
                MIN_VIDEO_KBPS, int(plan_.video_kbps * shrink)
            )
            _, retry = build_commands(
                clip_path, out_path, start, duration, tracks, plan_, logfile
            )
            _run_pass(retry, duration, on_progress, 0.5, 0.5, cancel)
            size = os.path.getsize(out_path)
    return size
