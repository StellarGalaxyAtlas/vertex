"""Peak levels of one audio stream, for the waveform drawn in each editor lane."""

from __future__ import annotations

import array
import subprocess
import sys
import threading

from vertex.media.ffmpeg import BASE
from vertex.platform import NO_WINDOW

# A lane is a couple of thousand pixels wide at most, so 4 kHz mono still
# leaves ~100 samples behind every pixel column, and decodes fast.
PEAK_RATE = 4000
PEAK_BUCKETS = 2000
FULL_SCALE = 32768.0
_BIG_ENDIAN = sys.byteorder == "big"


def peaks(clip_path: str, index: int, duration: float, buckets: int = PEAK_BUCKETS,
          cancel: threading.Event | None = None) -> list[float]:
    """Peak level per time slice of audio stream `index`, as floats 0-1.

    Empty when the stream will not decode or on cancellation: a waveform is
    decoration, and a caller that cannot have one draws a plain lane.

    The PCM is reduced as it arrives, so memory stays at one 64 KB read
    however long the clip is. Blocking; call from a worker thread.
    """
    if duration <= 0 or buckets <= 0:
        return []
    argv = [*BASE, "-v", "error", "-i", clip_path, "-map", f"0:a:{index}", "-vn",
            "-ac", "1", "-ar", str(PEAK_RATE), "-f", "s16le", "-"]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                **NO_WINDOW)
    except OSError:
        return []

    per_bucket = max(1, round(duration * PEAK_RATE / buckets))
    levels: list[float] = []
    peak = filled = 0
    tail = b""
    try:
        while chunk := proc.stdout.read(1 << 16):
            if cancel is not None and cancel.is_set():
                return []
            data = tail + chunk          # s16le is two bytes; a read can split one
            usable = len(data) - len(data) % 2
            tail, data = data[usable:], data[:usable]
            samples = array.array("h")
            samples.frombytes(data)
            if _BIG_ENDIAN:
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
                    peak = filled = 0
        proc.wait(timeout=10)
    except (subprocess.SubprocessError, OSError, ValueError):
        return []
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if proc.returncode != 0:
        return []        # no such stream, or a codec this build cannot decode
    if filled:
        levels.append(min(1.0, peak / FULL_SCALE))
    return levels
