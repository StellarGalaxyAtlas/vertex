"""The application context: config, library, thumbnails and the recorder.

Views never call ffmpeg or the recorder themselves. They call these
controllers, which run the blocking work on worker threads and report back
through Qt signals on the UI thread.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from vertex import fmt, hotkeys, logs, notifications, system
from vertex.config import Config
from vertex.core import naming
from vertex.library import Library
from vertex.media import probe
from vertex.media.thumbnails import ThumbnailCache
from vertex.recorder import backend, gsr, monitors, presets
from vertex.recorder.replay import RecorderError, State
from vertex.ui import screens, workers


class ThumbnailService(QObject):
    thumbnail_ready = Signal(str, str)       # clip path, image path ("" = none)
    preview_ready = Signal(str, list)        # clip path, frame paths
    duration_ready = Signal(str, float)      # clip path, seconds (0 = unknown)
    idle = Signal()

    def __init__(self, cache_dir: str, parent=None):
        super().__init__(parent)
        self.cache = ThumbnailCache(cache_dir)
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="thumbs")
        self._inflight: set[tuple[str, str]] = set()
        self._closed = False

    @property
    def pending(self) -> int:
        return len(self._inflight)

    def _submit(self, kind: str, clip_path: str, fn, deliver) -> None:
        key = (kind, clip_path)
        if key in self._inflight or self._closed:
            return
        self._inflight.add(key)

        def done(value):
            self._inflight.discard(key)
            deliver(value)
            if not self._inflight:
                self.idle.emit()

        workers.run(fn, done, lambda _exc: done(None), executor=self._pool)

    def cached_thumbnail(self, clip_path: str) -> str | None:
        return self.cache.cached_thumbnail(clip_path)

    def request_thumbnail(self, clip_path: str) -> None:
        self._submit("thumb", clip_path, lambda: self.cache.thumbnail(clip_path),
                     lambda path: self.thumbnail_ready.emit(clip_path, path or ""))

    def request_preview(self, clip_path: str, duration: float | None = None) -> None:
        cached = self.cache.cached_preview(clip_path)
        if cached:
            self.preview_ready.emit(clip_path, cached)
            return
        self._submit("preview", clip_path, lambda: self.cache.preview(clip_path, duration),
                     lambda frames: self.preview_ready.emit(clip_path, frames or []))

    def request_duration(self, clip_path: str) -> None:
        self._submit("duration", clip_path, lambda: probe.duration(clip_path),
                     lambda seconds: self.duration_ready.emit(clip_path, float(seconds or 0)))

    def discard(self, clip_path: str) -> None:
        self.cache.discard(clip_path)

    def prune(self, clip_paths) -> None:
        if self._closed:
            return
        paths = list(clip_paths)
        workers.run(lambda: self.cache.prune(paths), executor=self._pool)

    def shutdown(self) -> None:
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)


class RecorderController(QObject):
    # The recorder dying while it records is started again once; dying
    # again this soon after that restart is left stopped (and said so).
    RECOVER_WINDOW = 60.0

    # A State value, or "restarting" from a restart's stop until it runs again
    # (or fails); and error text.
    state_changed = Signal(str, str)
    saved = Signal(str)                  # path of the new clip
    info_changed = Signal(object)        # GsrInfo

    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self.info = gsr.GsrInfo(command=context.config.recorder.command)
        self.recorder = backend.recorder(
            on_state=lambda state, error: workers.post(self._on_state, (state, error)),
            on_saved=lambda path: workers.post(self._on_saved, path))
        self._restart_pending = False
        self._restarting = False
        # False once stopped, so a start still finding the recorder doesn't launch
        # after all.
        self._wanted = False
        # The state last passed on, so a stop isn't announced twice.
        self._reported = State.STOPPED
        # When the recorder was last started again after dying, and whether that is
        # the restart underway.
        self._recovered_at = float("-inf")
        self._recovering = False
        # (when, game) of the last save asked for, to tag the clip it brings.
        self._game_hint: tuple[float, str] = (0.0, "")
        # What the recorder said it can record when last asked: its monitors' names.
        self.capture_options: list[gsr.CaptureOption] = []

    @property
    def state(self) -> State:
        return self.recorder.state

    @property
    def phase(self) -> str:
        """What to show: the state, or "restarting" while a restart is underway."""
        return "restarting" if self._restarting else self.recorder.state.value

    @property
    def running(self) -> bool:
        return self.recorder.running

    def detect(self, then=None) -> None:
        """Find the recorder and ask what it can record, off the UI thread."""
        command = self.context.config.recorder.command

        def probe():
            info = backend.detect(command)
            return info, backend.list_capture_options(command) if info.available else []

        def done(result):
            info, self.capture_options = result
            if info != self.info:
                if info.available:
                    logs.RECORDER.info("Found %s %s (%s)", backend.name(), info.version_text,
                                       command or "where it is installed")
                else:
                    logs.RECORDER.warning("%s: %s", backend.name(), info.error or "not found")
            self.info = info
            self.info_changed.emit(self.info)
            if then is not None:
                then(self.info)

        def failed(exc):
            done((gsr.GsrInfo(command, error=f"Couldn't run {backend.name()}: {exc}"), []))

        workers.run(probe, done, failed)

    def problems(self) -> list[str]:
        if not self.info.available:
            return [self.info.error or f"{backend.name()} is not installed."]
        if self.info.too_old:
            return [self.info.error]
        return backend.validate(self._as_recorded())

    def _monitors(self) -> list[monitors.Monitor]:
        return monitors.arrange(self.capture_options, screens.desktop_screens())

    def capture_target(self) -> str:
        """The monitor a recording captures now: the one picked, or the
        primary one while that isn't connected or none has been picked."""
        return monitors.target(self.context.config.recorder.capture, self._monitors())

    def _as_recorded(self):
        """The settings as the recorder gets them, for the monitor recorded now."""
        return presets.resolve(self.context.config.recorder, self._monitors())

    def launch_plan(self):
        """What the recorder would be started with now: GSR's command line,
        or what is set up in OBS."""
        config = self.context.config
        return backend.launch_plan(config, self._monitors(), gsr.audio_tracks(config),
                                   self.info)

    def start(self) -> None:
        if self.running:
            return
        self._wanted = True

        def go(_info=None):
            problems = self.problems()
            if problems:
                self._on_state((State.FAILED, problems[0]))
                return
            self._launch()

        # Asked every time: monitors come and go between starts.
        self.detect(go)

    def _launch(self) -> None:
        if self.running or not self._wanted:
            return
        # Asked every time: devices come and go between starts.
        command = self.context.config.recorder.command
        workers.run(lambda: [name for name, _d in backend.list_audio_devices(command)],
                    self._launch_with, lambda _exc: self._launch_with([]))

    def _launch_with(self, devices: list[str]) -> None:
        if self.running or not self._wanted:
            return
        config = self.context.config
        tracks, stood_in = gsr.available_tracks(gsr.audio_tracks(config), devices)
        for track, instead in stood_in:
            device = track.source.removeprefix("device:")
            role = track.title.removeprefix("Vertex ")
            what = {"default_output": "the default output",
                    "default_input": "the default microphone"}.get(instead)
            self.context.notify(
                "track_missing", f"{role} audio: {device} isn't available",
                f"Recording {what} instead" if what else "Recording without it")
        plan = backend.launch_plan(config, self._monitors(), tracks, self.info)
        logs.RECORDER.info("Starting the replay buffer: %s", backend.describe(plan))
        try:
            self.recorder.start(plan, config.resolved_recording_dir())
        except RecorderError as exc:
            self._on_state((State.FAILED, str(exc)))

    def stop(self) -> None:
        if self.running or self._restarting:
            logs.RECORDER.info("Stopping the replay buffer")
        self._wanted = False
        self._restart_pending = False
        self._restarting = self._recovering = False
        workers.run(self.recorder.stop)

    def toggle(self) -> None:
        if self.running or self._restarting:
            self.stop()
        else:
            self.start()

    def restart_if_running(self) -> None:
        """Pick up changed settings or tracks by restarting the buffer. It shows
        as restarting until it runs again: on its own, the stop and start flash
        past as "Off" and "Starting…" too quickly to notice."""
        if not self.running:
            return
        logs.RECORDER.info("Restarting the replay buffer for new settings or audio tracks")
        self._restart_pending = True
        self._restarting = True
        self.state_changed.emit("restarting", "")
        workers.run(self.recorder.stop, lambda _v: self._restart())

    def _restart(self) -> None:
        if self._restart_pending:
            self._restart_pending = False
            self.start()

    def save(self, seconds: int | None = None) -> str:
        """Ask for a save. Returns a message to show; the clip arrives later."""
        problem = ""
        if not self.running:
            problem = "The replay buffer is not running."
        elif seconds is not None and int(seconds) not in backend.SAVE_PRESETS:
            problem = f"Only the last {sorted(backend.SAVE_PRESETS)} seconds can be saved"
        if problem:
            # Saving from a shortcut or the tray shows nothing else of it.
            self.context.notify("clip_not_saved", "Clip not saved", problem)
            raise RecorderError(problem)
        logs.RECORDER.info("Saving %s",
                           f"the last {seconds} seconds" if seconds else "the replay buffer")
        # Finding GSR to signal reads /proc, and OBS is asked over its socket:
        # off the UI thread.
        workers.run(lambda: self.recorder.save(seconds), None,
                    lambda exc: self.context.notify("clip_not_saved", "Clip not saved",
                                                    str(exc)))
        self._game_hint = (0.0, "")
        if system.WINDOWS and self.context.config.recorder.tag_from_fullscreen:
            workers.run(system.fullscreen_app, self._got_fullscreen, lambda _exc: None)
        span = f"the last {fmt.duration(seconds)}" if seconds else "the replay buffer"
        return f"Saving {span}…"

    def _recover(self, error: str) -> bool:
        """The recorder died while recording: start it again, once. False when it
        wasn't running yet (a start that fails stays failed), or it died again
        within RECOVER_WINDOW of the last such restart."""
        if self._reported != State.RUNNING or self._restarting or not self._wanted:
            return False
        now = time.monotonic()
        if now - self._recovered_at < self.RECOVER_WINDOW:
            logs.RECORDER.error("%s stopped again; leaving the replay buffer off",
                                backend.name())
            return False
        self._recovered_at = now
        logs.RECORDER.warning("Starting the replay buffer again after it stopped (%s)", error)
        self._recovering = self._restarting = True
        self.state_changed.emit("restarting", "")
        self.start()
        return True

    def _on_state(self, payload) -> None:
        state, error = payload
        if state == State.FAILED and self._recover(error):
            return
        restarted = recovered = False
        if self._restarting:
            if state in (State.STOPPED, State.STARTING):
                return
            self._restarting = False
            restarted = state == State.RUNNING
            recovered, self._recovering = self._recovering, False
        if state == State.STOPPED and self._reported == State.STOPPED:
            return      # a stop reports itself, and so does the recorder exiting
        self._reported = state
        if restarted:
            self.context.notify("replay_restarted", "Replay buffer restarted",
                                f"{backend.name()} had stopped" if recovered else "")
        elif state == State.RUNNING:
            seconds = self.context.config.recorder.replay_seconds
            self.context.notify("replay_started", "Replay buffer on",
                                f"Last {fmt.duration(seconds)}")
        elif state == State.STOPPED:
            self.context.notify("replay_stopped", "Replay buffer off")
        elif state == State.FAILED and error:
            self.context.notify("replay_failed", "Replay buffer stopped", error)
        self.state_changed.emit(state.value, error or "")

    def _got_fullscreen(self, window: tuple[str, str] | None) -> None:
        if window is not None:
            game = naming.game_from_window(*window) or naming.DESKTOP_TAG
            self._game_hint = (time.monotonic(), game)

    def _on_saved(self, path: str) -> None:
        when, game = self._game_hint
        library = self.context.library
        logs.RECORDER.info("Saved %s", path)
        name = os.path.basename(path)
        if game and time.monotonic() - when < 60 and library is not None and \
                (tag := library.tag_if_untagged(name, game)):
            logs.CLIPS.info("Tagged %s with %s (on screen when it was saved)", name, tag)
        self._game_hint = (0.0, "")
        self.saved.emit(path)

    def shutdown(self) -> None:
        self._restart_pending = False
        if self.running:
            logs.RECORDER.info("Stopping the replay buffer (quitting)")
            self.recorder.stop(timeout=3)


# Every notice goes in the log of the part it is about, as serious as it looks.
_NOTICE_LOGS = {"clips": logs.RECORDER, "vertex": logs.APP}
_NOTICE_LEVELS = {"info": logging.INFO, "ok": logging.INFO, "warn": logging.WARNING,
                  "error": logging.ERROR}


class Hotkeys(QObject):
    """The global hotkeys in the settings, held with Windows while Vertex
    runs (see vertex.hotkeys). `pressed` names the action; `failed` holds the
    actions whose keys another program has, as of the last `checked`."""

    pressed = Signal(str)
    checked = Signal()               # Windows said which hotkeys it holds
    _result = Signal(object)

    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self.failed: set[str] = set()
        self._paused = False
        self._started = False
        # Both are called from the listener's thread: through signals, they
        # land on the UI thread.
        self._listener = hotkeys.Listener(self.pressed.emit, self._result.emit)
        self._result.connect(self._got_result)
        context.config_changed.connect(self.apply)

    def start(self) -> None:
        self._started = True
        self.apply()

    def apply(self) -> None:
        if self._started:
            self._listener.set({} if self._paused else
                               hotkeys.bindings(self.context.config.hotkeys))

    def pause(self, paused: bool) -> None:
        """Let every hotkey go while new keys are being recorded, so pressing
        one records it rather than running it."""
        if paused != self._paused:
            self._paused = paused
            self.apply()

    def _got_result(self, failed: set[str]) -> None:
        if not self._paused:
            self.failed = set(failed)
            self.checked.emit()

    def shutdown(self) -> None:
        self._listener.close()


class Context(QObject):
    config_changed = Signal()
    library_reset = Signal()             # the library or clips folder changed
    message = Signal(str, str)           # text, level: info | ok | warn | error
    # Everything worth telling the user, by kind (see vertex.notifications):
    # shown in the window, and popped up on the desktop when its kind is on.
    notified = Signal(object)            # notifications.Notice

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        naming.use_patterns(config.patterns())
        self.library: Library | None = None
        self.thumbs: ThumbnailService | None = None
        self.recorder = RecorderController(self)
        self.hotkeys = Hotkeys(self)
        self._save_timer = QTimer(self, singleShot=True, interval=1000)
        self._save_timer.timeout.connect(self.save_config)

    def open_library(self) -> None:
        """(Re)open the library and thumbnail cache from the current config."""
        if self.library is not None:
            self.library.close()
        if self.thumbs is not None:
            self.thumbs.shutdown()
        self.config.ensure_dirs()
        try:
            self.library = Library(self.config.resolved_data_dir())
            logs.CLIPS.info("Library: %s", self.library.path)
        except Exception as exc:     # run without a library rather than not at all
            self.notify("vertex_problem", "Couldn't open the library", str(exc))
            self.library = Library.in_memory()
        self.library.game_names = self.config.game_names
        self.thumbs = ThumbnailService(self.config.resolved_cache_dir(), self)
        self.library_reset.emit()

    def rename_game(self, old: str, new: str, remember: bool = True) -> int:
        """Retag the clips of game `old` as `new`; when `remember`, tag new
        clips that way too. Returns how many clips changed."""
        changed = self.library.rename_game(old, new) if self.library is not None else 0
        if remember:
            self.set_game_names(naming.add_game_name(self.config.game_names, old, new))
        if changed:
            logs.CLIPS.info("Retagged %s from %s to %s", fmt.plural(changed, "clip"), old, new)
        return changed

    def set_game_names(self, names: dict[str, str]) -> None:
        self.config.game_names = names
        if self.library is not None:
            self.library.game_names = names
        self.save_config()

    def save_config(self) -> None:
        self._save_timer.stop()
        try:
            self.config.save()
        except OSError as exc:
            self.notify("vertex_problem", "Couldn't save settings", str(exc))
            return
        # Follows logging switched on or off, or a moved log folder.
        logs.apply(self.config.keep_logs, self.config.resolved_log_dir())
        naming.use_patterns(self.config.patterns())
        self.config_changed.emit()

    def notify(self, kind: str, title: str, body: str = "") -> None:
        """Tell the user something; `kind` is one of notifications.KINDS."""
        if kind not in notifications.BY_ID:
            raise KeyError(f"Unknown notification kind: {kind}")
        notice = notifications.Notice(kind, title, body)
        _NOTICE_LOGS[notifications.BY_ID[kind].category].log(
            _NOTICE_LEVELS[notifications.BY_ID[kind].level], notice.line)
        self.notified.emit(notice)

    def save_config_later(self) -> None:
        self._save_timer.start()

    def shutdown(self) -> None:
        self.hotkeys.shutdown()
        if self._save_timer.isActive():
            self.save_config()
        self.recorder.shutdown()
        if self.thumbs is not None:
            self.thumbs.shutdown()
        if self.library is not None:
            self.library.close()
