"""Make Vertex's own sounds (src/vertex/assets/sounds): soft two-note chimes,
synthesised here, so they are Vertex's to ship.

usage: python tools/make_sounds.py [OUT_DIR]     (needs numpy)
"""

import os
import sys
import wave

import numpy as np

RATE = 48000
SOFT = ((1, 1.0), (2, 0.18), (3, 0.06))      # a sine with a little warmth


def tone(freq: float, seconds: float, decay: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    wave_ = sum(weight * np.sin(2 * np.pi * freq * harmonic * t) for harmonic, weight in SOFT)
    return wave_ * np.clip(t / 0.004, 0, 1) * np.exp(-t / decay)


def together(*parts: tuple[float, np.ndarray]) -> np.ndarray:
    """(start in seconds, sound) pairs, mixed."""
    out = np.zeros(max(int(start * RATE) + len(sound) for start, sound in parts))
    for start, sound in parts:
        at = int(start * RATE)
        out[at:at + len(sound)] += sound
    return out


SOUNDS = {
    "clip-saved": together((0, tone(659.3, 0.5, 0.18)), (0.09, tone(987.8, 0.6, 0.22))),
    "clip-not-saved": together((0, tone(440, 0.5, 0.16)), (0.12, tone(311.1, 0.6, 0.22))),
    "replay-started": tone(880, 0.35, 0.10),
    "replay-stopped": tone(523.3, 0.35, 0.10),
}


def write(path: str, sound: np.ndarray, peak: float = 0.5) -> None:
    sound = sound / np.max(np.abs(sound)) * peak
    fade = int(0.01 * RATE)
    sound[-fade:] *= np.linspace(1, 0, fade)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((sound * 32767).astype("<i2").tobytes())


def main(folder: str) -> None:
    for name, sound in SOUNDS.items():
        write(os.path.join(folder, f"{name}.wav"), sound)
        print("wrote", os.path.join(folder, f"{name}.wav"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "vertex", "assets",
        "sounds"))
