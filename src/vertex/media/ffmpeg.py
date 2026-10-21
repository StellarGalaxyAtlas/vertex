"""Running ffmpeg passes: cancellable, with progress, with readable errors."""

from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Callable

from vertex.platform import NO_WINDOW
from vertex.proc import last_line

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Every invocation starts like this: no banner, never read stdin (a stray
# keypress in the launching terminal must not answer a prompt), errors only.
BASE = [FFMPEG, "-hide_banner", "-nostdin"]

_TIME_RE = re.compile(rb"out_time_us=(\d+)")


class MediaError(Exception):
    """An ffmpeg/ffprobe operation failed; the message is fit to show a user."""


class Cancelled(MediaError):
    def __init__(self):
        super().__init__("Cancelled.")


ProgressFn = Callable[[float], None]


def run_pass(argv: list[str], duration: float, on_progress: ProgressFn | None = None,
             base: float = 0.0, span: float = 1.0,
             cancel: threading.Event | None = None) -> None:
    """Run one ffmpeg pass, mapping its progress into [base, base + span].

    `argv` must ask for `-progress pipe:1`. Raises Cancelled when `cancel` is
    set, MediaError with ffmpeg's last stderr line when it fails.
    """
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **NO_WINDOW)
    except OSError as exc:
        raise MediaError(f"Could not start ffmpeg: {exc}") from exc

    # stderr is drained on its own thread: a pass that logs a lot would
    # otherwise fill the pipe and stall waiting for us to read it.
    errors: list[bytes] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    try:
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            match = _TIME_RE.search(line)
            if match and on_progress is not None and duration > 0:
                done = min(1.0, int(match.group(1)) / 1_000_000 / duration)
                on_progress(base + span * done)
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        reader.join(timeout=5)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        raise MediaError(last_line(b"".join(errors), "ffmpeg failed."))


def run_quiet(argv: list[str], timeout: float, what: str) -> subprocess.CompletedProcess:
    """Run a short ffmpeg/ffprobe command, raising MediaError on failure."""
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout, check=True,
                              **NO_WINDOW)
    except subprocess.CalledProcessError as exc:
        raise MediaError(f"{what}: {last_line(exc.stderr, 'ffmpeg failed.')}") from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise MediaError(f"{what}: {exc}") from exc
