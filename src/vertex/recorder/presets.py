"""The basic recording choices, and what they come to.

Settings offers a few plain choices — how long a clip is, its video quality,
resolution and frame rate — rather than GPU Screen Recorder's own knobs. This
module turns them into what GSR is given for the monitor being recorded (a
size box turned to match the monitor, a bitrate) and estimates how big a clip
gets.
"""

from __future__ import annotations

import dataclasses
import re

from vertex.config import QUALITIES, RecorderConfig
from vertex.recorder import monitors
from vertex.recorder.monitors import Monitor

DURATIONS = (30, 60, 90, 120)            # seconds
FRAME_RATES = (30, 60, 120)
HEIGHTS = (720, 1080, 1440, 2160)        # "1080p": the monitor's short side, in pixels

# Video quality levels by GSR's names for its quality modes (-q), lowest first.
# Settings calls them Low, Medium, High and Ultra.
LEVELS = QUALITIES

# Constant bitrate per level for H.264 at 1080p and 60 fps, in kbps. Other
# sizes and frame rates scale from these (see video_kbps).
REFERENCE_KBPS = {"medium": 8000, "high": 12000, "very_high": 20000, "ultra": 35000}
REFERENCE_RATE = 1920 * 1080 * 60

# GSR's audio bitrate when none is set (-ab), per codec, in kbps.
DEFAULT_AUDIO_KBPS = {"aac": 160, "opus": 128}

# What a monitor of unknown size is taken to be.
ASSUMED_PIXELS = (1920, 1080)


def preset_height(resolution: str) -> int:
    """The height of a "1080p" setting; 0 for anything else."""
    match = re.fullmatch(r"(\d+)p", resolution or "")
    return int(match[1]) if match else 0


def _even(value: float) -> int:
    # Encoders want even dimensions.
    return max(2, round(value / 2) * 2)


def output_size(resolution: str, pixels: tuple[int, int]) -> tuple[int, int]:
    """The size of the recorded video for a monitor of `pixels`.

    A "1080p" setting scales the monitor so its short side is 1080, keeping
    its shape, so a vertical monitor stays vertical; it never scales up. "" is
    the monitor's own size. A WxH limit from older settings fits the picture
    inside that box, as GSR does, which scales up as well as down.
    """
    width, height = pixels if all(pixels) else ASSUMED_PIXELS
    target = preset_height(resolution)
    if target:
        short = min(width, height)
        if target >= short:
            return width, height
        return _even(width * target / short), _even(height * target / short)
    box = re.fullmatch(r"(\d+)x(\d+)", resolution or "")
    if box:
        box_width, box_height = int(box[1]), int(box[2])
        scale = min(box_width / width, box_height / height)
        return int(width * scale), int(height * scale)
    return width, height


def gsr_box(resolution: str, pixels: tuple[int, int]) -> str:
    """What GSR's -s gets: "" for the monitor's own size, else WxH."""
    if not preset_height(resolution):
        return resolution or ""          # "" or a WxH limit, as it is
    if not all(pixels):
        # The monitor's shape isn't known: GSR fits it into a landscape box.
        height = preset_height(resolution)
        return f"{_even(height * 16 / 9)}x{height}"
    size = output_size(resolution, pixels)
    return "" if size == tuple(pixels) else f"{size[0]}x{size[1]}"


def video_kbps(level: str, size: tuple[int, int], fps: int) -> int:
    """The constant bitrate a quality level gives at this size and frame rate.

    Scaled by pixels per second to the power 0.75: twice the pixels or frames
    need more bits, but not twice as many, since neighbouring pixels and
    frames have more in common.
    """
    base = REFERENCE_KBPS.get(level, REFERENCE_KBPS["very_high"])
    rate = max(1, size[0] * size[1]) * max(1, fps)
    kbps = base * (rate / REFERENCE_RATE) ** 0.75
    return max(1000, round(kbps / 500) * 500)


def recorded_monitor(rec: RecorderConfig, monitor_list: list[Monitor]) -> Monitor | None:
    capture = monitors.target(rec.capture, monitor_list)
    return next((m for m in monitor_list if m.name == capture), None)


def resolve(rec: RecorderConfig, monitor_list: list[Monitor]) -> RecorderConfig:
    """The settings as GSR is given them: the monitor to record, the size box
    turned to match it, and the bitrate the video quality comes to there. A
    bitrate set by hand counts only for constant bitrate, as with GSR."""
    monitor = recorded_monitor(rec, monitor_list)
    capture = monitor.name if monitor else monitors.target(rec.capture, monitor_list)
    pixels = monitor.pixels if monitor else (0, 0)
    size = output_size(rec.resolution, pixels)
    by_hand = rec.bitrate_kbps if rec.bitrate_mode == "cbr" else 0
    return dataclasses.replace(
        rec, capture=capture, resolution=gsr_box(rec.resolution, pixels),
        bitrate_kbps=by_hand or video_kbps(rec.quality, size, rec.fps))


def audio_kbps(rec: RecorderConfig) -> int:
    return rec.audio_bitrate or DEFAULT_AUDIO_KBPS.get(rec.audio_codec, 128)


def clip_bytes(resolved: RecorderConfig, tracks: int) -> int:
    """About how big a clip of `resolved.replay_seconds` is: video and every
    audio track at their bitrates. Close for constant bitrate; with GSR's
    quality modes the size depends on what is on screen, so it is a guess."""
    kbps = resolved.bitrate_kbps + audio_kbps(resolved) * tracks
    return kbps * 1000 // 8 * resolved.replay_seconds
