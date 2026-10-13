"""Small subprocess helpers shared by the ffmpeg, pactl and recorder wrappers."""

from __future__ import annotations

import ctypes
import ctypes.util
import shutil
import signal
import subprocess


class ToolMissing(RuntimeError):
    """A required external program is not installed."""

    def __init__(self, tool: str):
        super().__init__(f"'{tool}' was not found on PATH")
        self.tool = tool


def which(tool: str) -> str | None:
    return shutil.which(tool)


def require(tool: str) -> str:
    path = which(tool)
    if path is None:
        raise ToolMissing(tool)
    return path


def last_line(text: str | bytes | None, fallback: str = "") -> str:
    """The last non-blank line of a tool's output — usually the actual error."""
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else fallback


_PR_SET_PDEATHSIG = 1


def die_with_parent() -> None:
    """preexec_fn: have the kernel SIGTERM the child if Vertex itself dies.

    A replay buffer or a pactl event stream outliving the app that started it
    keeps recording or holding devices with nobody left to stop it.
    """
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    except (OSError, AttributeError):
        pass  # not Linux, or no libc to ask; the child just won't follow us


def run(argv: list[str], timeout: float = 30, check: bool = True,
        text: bool = True) -> subprocess.CompletedProcess:
    """subprocess.run with output captured and a timeout always set."""
    return subprocess.run(argv, capture_output=True, text=text, timeout=timeout, check=check)
