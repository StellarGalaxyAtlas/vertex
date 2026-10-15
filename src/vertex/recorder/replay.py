"""Running GPU Screen Recorder's replay buffer as a child process.

The buffer is controlled with signals — SIGUSR1 saves the whole buffer,
SIGRTMIN+n saves only the last 10 s … 30 min, SIGINT stops without saving —
and every saved replay's path is printed on stdout. This class wraps exactly
that and nothing more; it knows nothing about Qt or the library, and reports
through callbacks that run on its reader threads.

Stopping signals GSR's whole process group, wrappers and helpers alike. Saving
signals GSR alone: its helpers share the group, and gsr-kms-server, which
captures the screen for it, has no handler for those signals. They killed it,
after which GSR got no more frames and saved nothing more: the first save of
a run worked, and no other.
"""

from __future__ import annotations

import enum
import os
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable

from vertex.logs import RECORDER as log
from vertex.proc import die_with_parent
from vertex.recorder.gsr import SAVE_PRESETS

# How long the recorder has to stay up before it counts as running. GSR exits
# within a fraction of a second when a capture target or audio device is bad.
SETTLE_SECONDS = 1.5

# GPU Screen Recorder's process name, as the kernel keeps it: 15 characters.
RECORDER_NAME = "gpu-screen-recorder"[:15]


def _children() -> dict[int, list[int]]:
    """Every process's children, from /proc."""
    tree: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8", errors="replace") as handle:
                stat = handle.read()
        except OSError:
            continue
        # "pid (name) state ppid …", where the name may hold spaces and brackets.
        fields = stat.rsplit(")", 1)[-1].split()
        if len(fields) > 1 and fields[1].isdigit():
            tree.setdefault(int(fields[1]), []).append(int(entry))
    return tree


def _name(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def recorder_pids(root: int) -> list[int]:
    """GPU Screen Recorder itself: `root`, or the GSR a wrapper started (a
    Flatpak run line). Its own children — its helpers — are left out."""
    tree = _children()
    found, queue, seen = [], [root], set()
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        if _name(pid) == RECORDER_NAME:
            found.append(pid)
        else:
            queue.extend(tree.get(pid, []))
    return found


class State(enum.Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


class RecorderError(RuntimeError):
    pass


class ReplayRecorder:
    def __init__(self,
                 on_state: Callable[[State, str], None] | None = None,
                 on_saved: Callable[[str], None] | None = None):
        self.on_state = on_state
        self.on_saved = on_saved
        self.state = State.STOPPED
        self.error = ""
        self.argv: list[str] = []
        self._proc: subprocess.Popen | None = None
        self._stderr: deque[str] = deque(maxlen=40)
        self._lock = threading.Lock()
        self._stopping = False
        self._started_at = 0.0

    # --- Lifecycle ----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self.running else None

    def start(self, argv: list[str], output_dir: str) -> None:
        with self._lock:
            if self.running:
                raise RecorderError("The replay buffer is already running.")
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as exc:
                raise RecorderError(f"Could not create {output_dir}: {exc}") from exc
            self.argv = list(argv)
            self._stderr.clear()
            self._stopping = False
            self.error = ""
            try:
                # Its own session, so signals reach a wrapper's children too
                # (a Flatpak run line), and it dies with us if we crash.
                self._proc = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    bufsize=1, start_new_session=True, preexec_fn=die_with_parent)
            except OSError as exc:
                self._set(State.FAILED, f"Could not start GPU Screen Recorder: {exc}")
                raise RecorderError(self.error) from exc
            self._started_at = time.monotonic()
            proc = self._proc
        self._set(State.STARTING)
        threading.Thread(target=self._read_stdout, args=(proc,), daemon=True,
                         name="gsr-stdout").start()
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True,
                         name="gsr-stderr").start()
        threading.Thread(target=self._settle, args=(proc,), daemon=True,
                         name="gsr-settle").start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the buffer without saving it."""
        with self._lock:
            proc, self._stopping = self._proc, True
        if proc is None or proc.poll() is not None:
            self._set(State.STOPPED)
            return
        self._signal(proc, signal.SIGINT)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("GPU Screen Recorder didn't stop within %g seconds; killing it", timeout)
            self._signal(proc, signal.SIGKILL)
            proc.wait(timeout=2)
        self._set(State.STOPPED)

    def save(self, seconds: int | None = None) -> None:
        """Save the buffer, or only its last `seconds` (10, 30, 60, 300, 600, 1800).

        Reads /proc to find GSR in the process tree: quick, but call it off
        the UI thread."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise RecorderError("The replay buffer is not running.")
        if seconds is None:
            sig = signal.SIGUSR1
        else:
            offset = SAVE_PRESETS.get(int(seconds))
            if offset is None:
                raise RecorderError(f"Can only save the last {sorted(SAVE_PRESETS)} seconds.")
            sig = signal.SIGRTMIN + offset
        for pid in recorder_pids(proc.pid) or [proc.pid]:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass

    @staticmethod
    def _signal(proc: subprocess.Popen, sig: int) -> None:
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
                pass

    # --- Threads ------------------------------------------------------------

    def _set(self, state: State, error: str = "") -> None:
        self.state = state
        if error:
            self.error = error
        if self.on_state is not None:
            self.on_state(state, error)

    def _settle(self, proc: subprocess.Popen) -> None:
        deadline = self._started_at + SETTLE_SECONDS
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return            # _read_stdout reports the exit
            time.sleep(0.05)
        if proc is self._proc and proc.poll() is None and self.state == State.STARTING:
            self._set(State.RUNNING)

    def _read_stdout(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            path = line.strip()
            # The only thing GSR prints on stdout is the path of each save.
            if path and os.path.isabs(path) and self.on_saved is not None:
                self.on_saved(path)
        code = proc.wait()
        if proc is not self._proc:
            return
        if self._stopping or code == 0:
            self._set(State.STOPPED)
            return
        time.sleep(0.1)       # let the stderr reader catch the last lines
        log.error("GPU Screen Recorder exited with code %d. Its last output:\n%s", code,
                  "\n".join(self._stderr) or "(nothing)")
        detail = self.stderr_tail() or f"exit code {code}"
        self._set(State.FAILED, f"GPU Screen Recorder stopped: {detail}")

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                self._stderr.append(line)

    def stderr_tail(self, lines: int = 3) -> str:
        """The last error lines GSR printed — usually the reason it stopped."""
        relevant = [line for line in self._stderr
                    if "error" in line.lower() or "warning" not in line.lower()]
        return "\n".join((relevant or list(self._stderr))[-lines:])
