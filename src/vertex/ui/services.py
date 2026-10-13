"""The application context: config, library, thumbnails, Sonar and the recorder.

Views never call pactl, ffmpeg or the recorder themselves. They call these
controllers, which run the blocking work on worker threads and report back
through Qt signals on the UI thread.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from vertex import fmt
from vertex.audio.pulse import AudioError, Pactl
from vertex.audio.sonar import Sonar, SonarStatus
from vertex.config import Config
from vertex.core.naming import game_from_app
from vertex.library import Library
from vertex.media import probe
from vertex.media.thumbnails import ThumbnailCache
from vertex.recorder import gsr, monitors, presets
from vertex.recorder.replay import RecorderError, ReplayRecorder, State
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


class SonarController(QObject):
    """Sonar on a single worker thread, so pactl calls happen in order."""

    status_changed = Signal(object)      # SonarStatus
    streams_changed = Signal(list)       # [AppStream]
    recorders_changed = Signal(list)     # [AppCapture]
    devices_changed = Signal(list, list)  # outputs, inputs
    warning = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self.pactl = Pactl()
        self.sonar = Sonar(context.config.sonar, self._state_file(), self.pactl)
        self.status = SonarStatus()
        self._executor = workers.serial_executor("sonar")
        self._watcher = None
        self._busy = 0
        self._closed = False
        self._pending_volume: dict[str, float] = {}

        self._reconcile_timer = QTimer(self, singleShot=True, interval=700)
        self._reconcile_timer.timeout.connect(self._reconcile)
        self._streams_timer = QTimer(self, singleShot=True, interval=250)
        self._streams_timer.timeout.connect(self.refresh_streams)

    def _state_file(self) -> str:
        return os.path.join(self.context.config.resolved_state_dir(), "sonar.json")

    @property
    def enabled(self) -> bool:
        return self.context.config.sonar.enabled

    def _job(self, fn, on_done=None, quiet=False):
        if self._closed:
            return None          # a callback arriving after shutdown
        self._busy += 1
        self.busy_changed.emit(True)

        def finish(value):
            self._busy -= 1
            if not self._busy:
                self.busy_changed.emit(False)
            if on_done is not None:
                on_done(value)

        def failed(exc):
            finish(None)
            if not quiet:
                self.warning.emit(str(exc))

        return workers.run(fn, finish, failed, executor=self._executor)

    # --- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Bring Sonar up if it is enabled, and start watching the server."""
        self.refresh()
        self.refresh_devices()
        if self.enabled:
            self.set_enabled(True)
        self._watch()

    def _watch(self) -> None:
        if self._watcher is not None and self._watcher.running:
            return
        try:
            self._watcher = self.pactl.watch(
                lambda event: workers.post(self._on_event, event),
                lambda reason: workers.post(self._on_watch_lost, reason))
        except AudioError:
            self._watcher = None

    def _on_watch_lost(self, _reason: str) -> None:
        # The audio server restarted; watch again shortly, then repair.
        QTimer.singleShot(2000, self._watch)
        self._reconcile_timer.start()

    def _on_event(self, event) -> None:
        if event.facility == "sink-input":
            if event.kind == "new" and self.enabled:
                self._job(lambda: self.sonar.apply_rules(event.index), quiet=True)
            self._streams_timer.start()
            return
        if event.facility == "source-output":
            self._streams_timer.start()
            return
        if self.sonar.handle(event) == "reconcile":
            self._reconcile_timer.start()
            QTimer.singleShot(400, self.refresh_devices)
        elif event.facility in ("sink", "source") and event.kind == "change":
            # Volume or mute changed — by us or by the system mixer.
            self._streams_timer.start()
            QTimer.singleShot(150, self.refresh)

    def _reconcile(self) -> None:
        if not self.enabled:
            return
        self._job(self.sonar.reconcile, self._after_change, quiet=True)

    def set_enabled(self, enabled: bool) -> None:
        self.context.config.sonar.enabled = enabled
        self.context.save_config()

        def work():
            if enabled:
                return self.sonar.up()
            self.sonar.down()
            return []

        def done(warnings):
            for text in warnings or []:
                self.warning.emit(text)
            self._after_change(None)
            self.context.recorder.restart_if_running()

        self._job(work, done)

    def ensure_up(self, then) -> None:
        """Run `then()` once Sonar is up (bringing it up first if needed)."""
        if not self.enabled:
            then()
            return
        self._job(self.sonar.up, lambda _w: (self._after_change(None), then()))

    def _after_change(self, _value) -> None:
        self.refresh()
        self.refresh_streams()

    def refresh(self) -> None:
        self._job(self.sonar.status, self._got_status, quiet=True)

    def _got_status(self, status: SonarStatus | None) -> None:
        if status is None:
            return
        self.status = status
        self.status_changed.emit(status)

    def refresh_streams(self) -> None:
        """Who is playing where, and who is recording — one job, two signals."""
        def done(result):
            if result is None:
                return
            playing, recording = result
            self.streams_changed.emit(playing)
            self.recorders_changed.emit(recording)

        def work():
            # Every refresh also retries streams that refused to move: an
            # app with several streams could otherwise be left half on its
            # old channel, and show up on both.
            if self.enabled:
                self.sonar.apply_rules()
            return self.sonar.streams(), self.sonar.recorders()

        self._job(work, done, quiet=True)

    def refresh_devices(self) -> None:
        self._job(lambda: (self.sonar.outputs(), self.sonar.inputs()),
                  lambda pair: pair and self.devices_changed.emit(*pair), quiet=True)

    # --- Mixing and routing ---------------------------------------------------

    def set_volume(self, channel_id: str, volume: float) -> None:
        """Coalesced: a dragged slider queues one pactl call, not hundreds."""
        first = channel_id not in self._pending_volume
        self._pending_volume[channel_id] = volume
        self.context.config.sonar.channel(channel_id).volume = volume
        if first:
            def work():
                value = self._pending_volume.pop(channel_id)
                self.sonar.set_volume(channel_id, value)
            self._job(work, quiet=True)
        self.context.save_config_later()

    def set_muted(self, channel_id: str, muted: bool) -> None:
        self._job(lambda: self.sonar.set_muted(channel_id, muted), quiet=True)
        self.context.save_config_later()

    def set_record(self, channel_id: str, record: bool) -> None:
        self.context.config.sonar.channel(channel_id).record = record
        self.context.save_config()
        self.context.recorder.restart_if_running()

    def set_output(self, device: str) -> None:
        self.context.config.sonar.output_device = device
        self.context.save_config()
        self._job(lambda: self.sonar.set_output(device), self._after_change)

    def set_mic(self, device: str) -> None:
        self.context.config.sonar.mic_device = device
        self.context.save_config()
        self._job(lambda: self.sonar.set_mic(device), self._after_change)

    def set_default_channel(self, channel_id: str) -> None:
        self.context.config.sonar.default_channel = channel_id
        self.context.save_config()
        if self.enabled:
            self._job(lambda: self.sonar.up(take_defaults=True), self._after_change)

    def route(self, app_key: str, channel_id: str | None) -> None:
        def work():
            return self.sonar.route(app_key, channel_id)
        self._job(work, lambda _n: (self.context.save_config(), self.refresh_streams()))

    def forget_rule(self, app_key: str) -> None:
        self.context.config.sonar.app_rules.pop(app_key, None)
        self.context.save_config()
        self.refresh_streams()

    def game_apps(self) -> list[str]:
        """Blocking — call from a worker."""
        return self.sonar.game_apps()

    def shutdown(self, take_down: bool = True) -> None:
        self._closed = True
        self._reconcile_timer.stop()
        self._streams_timer.stop()
        if self._watcher is not None:
            self._watcher.stop()
        if take_down and self.enabled:
            try:
                self._executor.submit(self.sonar.down).result(timeout=10)
            except Exception:       # quitting regardless
                pass
        self._executor.shutdown(wait=False, cancel_futures=True)


class RecorderController(QObject):
    # A State value, or "restarting" from a restart's stop until it runs again
    # (or fails); and error text.
    state_changed = Signal(str, str)
    saved = Signal(str)                  # path of the new clip
    info_changed = Signal(object)        # GsrInfo

    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self.info = gsr.GsrInfo(command=context.config.recorder.command)
        self.recorder = ReplayRecorder(
            on_state=lambda state, error: workers.post(self._on_state, (state, error)),
            on_saved=lambda path: workers.post(self._on_saved, path))
        self._game_hint: tuple[float, str] = (0.0, "")
        self._restart_pending = False
        self._restarting = False
        # False once stopped, so a start still finding GSR or Sonar doesn't
        # launch after all.
        self._wanted = False
        # What GSR said it can record when last asked: its monitors' names.
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
        """Find GSR and ask what it can record, off the UI thread."""
        command = self.context.config.recorder.command

        def probe():
            info = gsr.detect(command)
            return info, gsr.list_capture_options(command) if info.available else []

        def done(result):
            self.info, self.capture_options = result
            self.info_changed.emit(self.info)
            if then is not None:
                then(self.info)

        def failed(exc):
            done((gsr.GsrInfo(command, error=f"Could not run GPU Screen Recorder: {exc}"), []))

        workers.run(probe, done, failed)

    def problems(self) -> list[str]:
        if not self.info.available:
            return [self.info.error or "GPU Screen Recorder is not installed."]
        if self.info.too_old:
            return [self.info.error]
        return gsr.validate(self._as_recorded())

    def _monitors(self) -> list[monitors.Monitor]:
        return monitors.arrange(self.capture_options, screens.desktop_screens())

    def capture_target(self) -> str:
        """The monitor a recording captures now: the one picked, or the
        primary one while that isn't connected or none has been picked."""
        return monitors.target(self.context.config.recorder.capture, self._monitors())

    def _as_recorded(self):
        """The settings as GSR gets them, for the monitor recorded now."""
        return presets.resolve(self.context.config.recorder, self._monitors())

    def argv(self) -> list[str]:
        config = self.context.config
        return gsr.build_argv(self._as_recorded(), gsr.audio_tracks(config),
                              config.resolved_recording_dir(), self.info)

    def start(self) -> None:
        if self.running:
            return
        self._wanted = True

        def go(_info=None):
            problems = self.problems()
            if problems:
                self._on_state((State.FAILED, problems[0]))
                return
            self.context.sonar.ensure_up(self._launch)

        # Asked every time: monitors come and go between starts.
        self.detect(go)

    def _launch(self) -> None:
        if self.running or not self._wanted:
            return
        try:
            self.recorder.start(self.argv(), self.context.config.resolved_recording_dir())
        except RecorderError as exc:
            self._on_state((State.FAILED, str(exc)))

    def stop(self) -> None:
        self._wanted = False
        self._restart_pending = False
        self._restarting = False
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
        if not self.running:
            raise RecorderError("The replay buffer is not running.")
        self.recorder.save(seconds)
        if self.context.config.recorder.tag_from_game_channel and self.context.sonar.enabled:
            workers.run(self.context.sonar.game_apps, self._got_game_apps,
                        lambda _exc: None)
        span = f"the last {fmt.duration(seconds)}" if seconds else "the replay buffer"
        return f"Saving {span}…"

    def _got_game_apps(self, names: list[str]) -> None:
        games = {game_from_app(name) for name in names or []} - {""}
        # Only a single, unambiguous game is worth writing down.
        self._game_hint = (time.monotonic(), games.pop() if len(games) == 1 else "")

    def _on_state(self, payload) -> None:
        state, error = payload
        if self._restarting:
            if state in (State.STOPPED, State.STARTING):
                return
            self._restarting = False
            if state == State.RUNNING:
                self.context.message.emit("Replay buffer restarted with the new settings. "
                                          "It starts empty.", "ok")
        self.state_changed.emit(state.value, error or "")

    def _on_saved(self, path: str) -> None:
        when, game = self._game_hint
        library = self.context.library
        if game and time.monotonic() - when < 60 and library is not None:
            library.tag_if_untagged(os.path.basename(path), game)
        self._game_hint = (0.0, "")
        self.saved.emit(path)

    def shutdown(self) -> None:
        self._restart_pending = False
        if self.running:
            self.recorder.stop(timeout=3)


class Context(QObject):
    config_changed = Signal()
    library_reset = Signal()             # the library or clips folder changed
    message = Signal(str, str)           # text, level: info | ok | warn | error

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.library: Library | None = None
        self.thumbs: ThumbnailService | None = None
        self.sonar = SonarController(self)
        self.recorder = RecorderController(self)
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
        except Exception as exc:     # run without a library rather than not at all
            self.message.emit(f"Could not open the library: {exc}", "error")
            self.library = Library.in_memory()
        self.thumbs = ThumbnailService(self.config.resolved_cache_dir(), self)
        self.library_reset.emit()

    def save_config(self) -> None:
        self._save_timer.stop()
        try:
            self.config.save()
        except OSError as exc:
            self.message.emit(f"Could not save settings: {exc}", "error")
            return
        self.config_changed.emit()

    def save_config_later(self) -> None:
        self._save_timer.start()

    def shutdown(self) -> None:
        if self._save_timer.isActive():
            self.save_config()
        self.recorder.shutdown()
        self.sonar.shutdown(take_down=True)
        if self.thumbs is not None:
            self.thumbs.shutdown()
        if self.library is not None:
            self.library.close()
