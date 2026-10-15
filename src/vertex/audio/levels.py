"""Live levels of Sonar's channels, for the meters next to their faders.

pactl has no peak readings, so each channel is read the way pavucontrol's
meters are: a small recording of the channel (an output's monitor, or the
Vertex Mic itself) at a low sample rate, of which only the loudest sample in
each block is kept. One `parec` per channel, only while a page with meters is
shown; it names its stream "Peak detect", which marks it as a meter rather
than an app recording (see `pulse.is_meter`), and it is never moved.
"""

from __future__ import annotations

import array
import math
import shutil
import subprocess
import threading

RATE = 8000                  # samples a second: plenty for a peak, little to read
BLOCK = RATE // 25           # a reading 25 times a second
DB_RANGE = 60.0              # the meter shows -60 dB to 0 dB
METER_NAME = "Peak detect"   # the stream name meters go by


def parec_argv(source: str) -> list[str]:
    return ["parec", "--raw", "--format=s16le", "--channels=1", f"--rate={RATE}",
            "--latency-msec=40", "--no-move", "--client-name=Vertex",
            f"--stream-name={METER_NAME}", "-d", source]


def peak_of(data: bytes) -> float:
    """The loudest sample in a block of 16-bit audio, from 0 to 1."""
    samples = array.array("h")
    samples.frombytes(data[:len(data) // 2 * 2])
    if not samples:
        return 0.0
    return min(1.0, max(max(samples), -min(samples)) / 32768)


def meter_fraction(peak: float) -> float:
    """How far up a meter goes for `peak`: in decibels, as a mixer's meters,
    so speech and a quiet game still move it."""
    if peak <= 0.0:
        return 0.0
    return max(0.0, min(1.0, (20 * math.log10(peak) + DB_RANGE) / DB_RANGE))


class LevelReader:
    """The level of one device, read by a `parec` of its own."""

    def __init__(self, source: str):
        self.source = source
        self.peak = 0.0
        self._process: subprocess.Popen | None = None

    def start(self) -> bool:
        """Start reading. Blocking (it starts a process): not on the UI thread."""
        if shutil.which("parec") is None:
            return False
        try:
            self._process = subprocess.Popen(parec_argv(self.source), stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            return False
        threading.Thread(target=self._read, args=(self._process,), daemon=True,
                         name=f"level {self.source}").start()
        return True

    def _read(self, process: subprocess.Popen) -> None:
        stream = process.stdout
        while True:
            data = stream.read(BLOCK * 2)
            if not data:
                break
            self.peak = max(self.peak, peak_of(data))

    def take(self) -> float:
        """The loudest since the last call."""
        peak, self.peak = self.peak, 0.0
        return peak

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()


class Levels:
    """Readers for a set of devices, started and stopped together."""

    def __init__(self):
        self.readers: dict[str, LevelReader] = {}
        self._lock = threading.Lock()

    def start(self, sources: dict[str, str]) -> bool:
        """Read `sources` ({key: device}). Blocking. False if levels can't be read."""
        with self._lock:
            self._stop()
            readers = {key: LevelReader(source) for key, source in sources.items()}
            started = {key: reader for key, reader in readers.items() if reader.start()}
            self.readers = started
            return bool(started)

    def stop(self) -> None:
        """Blocking."""
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        readers, self.readers = self.readers, {}
        for reader in readers.values():
            reader.stop()

    def take(self) -> dict[str, float]:
        """Each device's loudest since the last call, from 0 to 1."""
        return {key: reader.take() for key, reader in dict(self.readers).items()}
