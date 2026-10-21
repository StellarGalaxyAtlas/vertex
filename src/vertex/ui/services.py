"""The application context: config, library, thumbnails, the recorder,
hotkeys (Windows) and Sonar (Linux).

Views never call pactl, ffmpeg or the recorder themselves. They call these
controllers, which run the blocking work on worker threads and report back
through Qt signals on the UI thread.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from vertex import fmt, hotkeys, logs, notifications, platform
from vertex.audio import channels, devices, levels
from vertex.audio.pulse import AudioError, Pactl
from vertex.audio.sonar import Sonar, SonarStatus
from vertex.config import Config
from vertex.core import naming
from vertex.core.naming import game_from_app
from vertex.library import Library
from vertex.media import probe, track_volume
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


class SonarController(QObject):
    """Sonar on a single worker thread, so pactl calls happen in order."""

    status_changed = Signal(object)      # SonarStatus
    streams_changed = Signal(list)       # [AppStream]
    recorders_changed = Signal(list)     # [AppCapture]
    devices_changed = Signal(list, list)  # outputs, inputs
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
        # The real devices connected, as last seen.
        self.outputs: list = []
        self.inputs: list = []

        self._reconcile_timer = QTimer(self, singleShot=True, interval=700)
        self._reconcile_timer.timeout.connect(self._reconcile)
        self._streams_timer = QTimer(self, singleShot=True, interval=250)
        self._streams_timer.timeout.connect(self.refresh_streams)
        # Volumes are logged once they settle, not for every step of a drag.
        self._volumes_to_log: dict[str, float] = {}
        self._volume_log_timer = QTimer(self, singleShot=True, interval=1500)
        self._volume_log_timer.timeout.connect(self._log_volumes)
        self._last_failure = ""

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
                self.context.notify("sonar_problem", "Sonar", str(exc))
            elif str(exc) != self._last_failure:
                # Background refreshes fail in a row while the server is away:
                # once in the log is enough.
                logs.SONAR.warning("%s", exc)
            self._last_failure = str(exc)

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

    def _on_watch_lost(self, reason: str) -> None:
        # The audio server restarted; watch again shortly, then repair.
        logs.SONAR.warning("Lost the audio server (%s); connecting again",
                           reason or "no reason given")
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

    def set_enabled(self, enabled: bool, then=None) -> None:
        """Bring Sonar up or down; `then()` runs once it has."""
        self.context.config.sonar.enabled = enabled
        self.context.save_config()

        def work():
            if enabled:
                return self.sonar.up()
            self.sonar.down()
            return []

        def done(warnings):
            self.context.notify("sonar_switched", "Sonar is on" if enabled else "Sonar is off")
            for text in warnings or []:
                self.context.notify("sonar_problem", "Sonar", text)
            self._after_change(None)
            self.context.recorder.restart_if_running()
            if then is not None:
                then()

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
        before, self.status = self.status, status
        if before.active and status.active:
            names = self.context.config.sonar.device_names
            for kind, title, old, new in (
                    ("output_changed", "Sonar plays through", before.output, status.output),
                    ("mic_changed", "Vertex Mic records", before.mic, status.mic)):
                if old and new and old != new:
                    self.context.notify(kind, title, names.get(new, new))
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
        self._job(lambda: (self.sonar.outputs(), self.sonar.inputs()), self._got_devices,
                  quiet=True)

    def _got_devices(self, pair) -> None:
        if not pair:
            return
        outputs, inputs = pair
        for kind, before, now in (("output", self.outputs, outputs),
                                  ("microphone", self.inputs, inputs)):
            if not before:
                continue      # the first look: nothing came or went
            seen = {device.name for device in before}
            names = {device.name for device in now}
            for device in now:
                if device.name not in seen:
                    logs.SONAR.info("Connected %s: %s", kind, device.label)
            for device in before:
                if device.name not in names:
                    logs.SONAR.info("Disconnected %s: %s", kind, device.label)
        self.outputs, self.inputs = list(outputs), list(inputs)
        # New devices join the device manager's lists, at the bottom.
        if self.sonar.learn_devices(outputs, inputs):
            self.context.save_config()
        self.devices_changed.emit(outputs, inputs)

    # --- Device manager ---------------------------------------------------------

    def set_device_order(self, kind: str, priority: list[str], excluded: list[str]) -> None:
        """The order devices are picked in (kind "output" or "mic")."""
        sonar = self.context.config.sonar
        setattr(sonar, f"{kind}_priority", list(priority))
        setattr(sonar, f"{kind}_excluded", list(excluded))
        names = sonar.device_names
        logs.SONAR.info("New %s order: %s%s", "output" if kind == "output" else "microphone",
                        ", ".join(names.get(name, name) for name in priority) or "none",
                        f" (never picked: {', '.join(names.get(n, n) for n in excluded)})"
                        if excluded else "")
        self._device_settings_changed()

    def set_show_disconnected(self, shown: bool) -> None:
        self.context.config.sonar.show_disconnected = shown
        self.context.save_config()

    def set_device_volume(self, kind: str, name: str, volume: float) -> None:
        self._log_volume(self.context.config.sonar.device_names.get(name, name), volume)
        self._job(lambda: self.sonar.set_device_volume(kind, name, volume), quiet=True)
        QTimer.singleShot(200, self.refresh_devices)

    def _device_settings_changed(self) -> None:
        # A new order can mean another device.
        self.context.save_config()
        if self.enabled:
            self._job(self.sonar.reconcile, self._after_change, quiet=True)

    # --- Mixing and routing ---------------------------------------------------

    def set_volume(self, channel_id: str, volume: float) -> None:
        """Coalesced: a dragged slider queues one pactl call, not hundreds."""
        first = channel_id not in self._pending_volume
        self._pending_volume[channel_id] = volume
        self.context.config.sonar.channel(channel_id).volume = volume
        self._log_volume(channels.BY_ID[channel_id].label, volume)
        if first:
            def work():
                value = self._pending_volume.pop(channel_id)
                self.sonar.set_volume(channel_id, value)
            self._job(work, quiet=True)
        self.context.save_config_later()

    def _log_volume(self, what: str, volume: float) -> None:
        self._volumes_to_log[what] = volume
        self._volume_log_timer.start()

    def _log_volumes(self) -> None:
        for what, volume in self._volumes_to_log.items():
            logs.SONAR.info("%s volume %d%%", what, round(volume * 100))
        self._volumes_to_log.clear()

    def set_muted(self, channel_id: str, muted: bool) -> None:
        logs.SONAR.info("%s %s", channels.BY_ID[channel_id].label, "muted" if muted else "unmuted")
        self._job(lambda: self.sonar.set_muted(channel_id, muted), quiet=True)
        self.context.save_config_later()

    def set_channel_output(self, channel_id: str, device: str, lasting: bool = False) -> None:
        """Play a channel through `device`: every output channel while linked,
        for now; `lasting` (setup) puts it on top of the device manager's list."""
        self._job(lambda: self.sonar.set_channel_output(channel_id, device, lasting),
                  self._devices_changed)

    def set_linked(self, linked: bool, channel_id: str) -> None:
        """One device for every output channel (`channel_id`'s), or one each."""
        self._job(lambda: self.sonar.set_linked(linked, channel_id), self._devices_changed)

    def set_second_output(self, device: str) -> None:
        self._job(lambda: self.sonar.set_second_output(device), self._devices_changed)

    def set_also_second(self, channel_id: str, also: bool) -> None:
        self._job(lambda: self.sonar.set_also_second(channel_id, also), self._devices_changed)

    def cycle_device(self, step: int, channel_id: str = "") -> list[tuple[str, str]]:
        """Switch to the next (1) or previous (-1) connected device in the
        device manager's list, skipping excluded ones, for now: the list keeps
        its order. With no channel, every output channel moves; unlinked,
        `channel_id` moves alone. Returns (channel id or "outputs", device)
        for each switch."""
        sonar, status = self.context.config.sonar, self.status
        if channel_id == channels.MIC.id:
            following = devices.cycle(sonar.mic_priority, sonar.mic_excluded,
                                      [d.name for d in self.inputs], status.mic, step)
            if not following:
                return []
            self.set_mic(following)
            return [(channel_id, following)]
        connected = [d.name for d in self.outputs]
        if sonar.linked:
            following = devices.cycle(sonar.output_priority, sonar.output_excluded,
                                      connected, status.output, step)
            if not following:
                return []
            self.set_channel_output(channels.GAME.id, following)
            return [("outputs", following)]
        moved = []
        for channel in channels.OUTPUTS:
            if channel_id and channel.id != channel_id:
                continue
            entry = status.channels.get(channel.id)
            current = (entry.output if entry is not None else "") or status.output
            following = devices.cycle(sonar.output_priority, sonar.output_excluded,
                                      connected, current, step)
            if following:
                self.set_channel_output(channel.id, following)
                moved.append((channel.id, following))
        return moved

    def pick_device(self, device: str, channel_id: str = "") -> list[tuple[str, str]]:
        """Switch to `device`, for now, the way `cycle_device` moves: returns
        the same pairs, or [] when it isn't plugged in."""
        if channel_id == channels.MIC.id:
            if device not in [d.name for d in self.inputs]:
                return []
            self.set_mic(device)
            return [(channel_id, device)]
        if device not in [d.name for d in self.outputs]:
            return []
        if self.context.config.sonar.linked:
            self.set_channel_output(channels.GAME.id, device)
            return [("outputs", device)]
        moved = [channel.id for channel in channels.OUTPUTS
                 if not channel_id or channel.id == channel_id]
        for target in moved:
            self.set_channel_output(target, device)
        return [(target, device) for target in moved]

    def _devices_changed(self, warnings) -> None:
        for text in warnings or []:
            self.context.notify("sonar_problem", "Sonar", text)
        self.context.save_config()
        self._after_change(None)

    def set_mic(self, device: str, lasting: bool = False) -> None:
        """Feed Vertex Mic from `device`, for now; `lasting` as above."""
        self._job(lambda: self.sonar.set_mic(device, lasting), self._devices_changed)

    def set_default_channel(self, channel_id: str) -> None:
        self.context.config.sonar.default_channel = channel_id
        logs.SONAR.info("Default output channel: %s", channels.BY_ID[channel_id].label)
        self.context.save_config()
        if self.enabled:
            self._job(lambda: self.sonar.up(take_defaults=True), self._after_change)

    def route(self, app_key: str, channel_id: str | None) -> None:
        if channel_id is None:
            logs.SONAR.info("%s goes back to the default channel", app_key)
        else:
            logs.SONAR.info("%s plays on %s from now on", app_key, channels.BY_ID[channel_id].label)

        def work():
            return self.sonar.route(app_key, channel_id)
        self._job(work, lambda _n: (self.context.save_config(), self.refresh_streams()))

    def forget_rule(self, app_key: str) -> None:
        if self.context.config.sonar.app_rules.pop(app_key, None):
            logs.SONAR.info("Forgot where %s plays", app_key)
        self.context.save_config()
        self.refresh_streams()

    def game_apps(self) -> list[str]:
        """Blocking — call from a worker."""
        return self.sonar.game_apps()

    def shutdown(self, take_down: bool = True) -> None:
        self._closed = True
        if self._volume_log_timer.isActive():
            self._log_volumes()
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
        # Whether Sonar's devices were all there when last seen.
        self._sonar_active: bool | None = None
        # The state last passed on, so a stop isn't announced twice.
        self._reported = State.STOPPED
        # When the recorder was last started again after dying, and whether that is
        # the restart underway.
        self._recovered_at = float("-inf")
        self._recovering = False
        # (when, game, where it was seen: "channel" or "screen") of the last
        # save asked for, to tag the clip it brings.
        self._game_hint: tuple[float, str, str] = (0.0, "", "")
        # The volume of each track the recorder records, in the clip's order.
        self._volumes: list[int] = []
        if context.sonar is not None:
            context.sonar.status_changed.connect(self._sonar_status)
        # What the recorder said it can record when last asked: its monitors' names.
        self.capture_options: list[gsr.CaptureOption] = []
        self._enabled = context.config.recorder.enabled
        context.config_changed.connect(self._config_changed)

    @property
    def enabled(self) -> bool:
        """Whether Vertex records at all: off, it only manages clips."""
        return self.context.config.recorder.enabled

    def _config_changed(self) -> None:
        """Recording turned off stops the buffer; turned on, the recorder is
        looked for."""
        if self.enabled == self._enabled:
            return
        self._enabled = self.enabled
        logs.RECORDER.info("Recording %s", "on" if self.enabled else "off")
        if self.enabled:
            self.detect()
        else:
            self.stop()

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
        if self.running or not self.enabled:
            return
        self._wanted = True

        def go(_info=None):
            problems = self.problems()
            if problems:
                self._on_state((State.FAILED, problems[0]))
                return
            if self.context.sonar is not None:
                self.context.sonar.ensure_up(self._launch)
            else:
                self._launch()

        # Asked every time: monitors come and go between starts.
        self.detect(go)

    def _launch(self) -> None:
        if self.running or not self._wanted:
            return
        # Asked every time: devices come and go between starts, and Sonar's
        # channels are only devices while it runs.
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
            if instead and channels.BY_NODE.get(device.removesuffix(".monitor")):
                continue     # Sonar is off: its channels standing in is the plan
            role = track.title.removeprefix("Vertex ")
            what = {"default_output": "the default output",
                    "default_input": "the default microphone"}.get(instead)
            self.context.notify(
                "track_missing", f"{role} audio: {device} isn't available",
                f"Recording {what} instead" if what else "Recording without it")
        self._volumes = [track.volume for track in tracks]
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

    def _sonar_status(self, status: SonarStatus) -> None:
        """Sonar's devices came or went (turned off, crashed, back): tracks
        recording one switch between it and its stand-in, which takes a
        restart. A buffer that died with them starts again."""
        was, self._sonar_active = self._sonar_active, status.active
        if was is None or was == status.active:
            return
        nodes = {channel.node for channel in channels.ALL}
        if not any(track.source.removeprefix("device:").removesuffix(".monitor") in nodes
                   for track in gsr.audio_tracks(self.context.config)):
            return
        if self.running:
            self.restart_if_running()
        elif self._wanted and self.state == State.FAILED:
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
        if not self.enabled:
            problem = "Recording is off. Turn it on in Settings › Recording."
        elif not self.running:
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
        self._game_hint = (0.0, "", "")
        rec, sonar = self.context.config.recorder, self.context.sonar
        if sonar is not None and rec.tag_from_game_channel and sonar.enabled:
            workers.run(sonar.game_apps, self._got_game_apps, lambda _exc: None)
        if platform.FULLSCREEN_GAME and rec.tag_from_fullscreen:
            workers.run(platform.fullscreen_app, self._got_fullscreen, lambda _exc: None)
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

    def _got_game_apps(self, names: list[str]) -> None:
        games = {game_from_app(name) for name in names or []} - {""}
        # Only a single, unambiguous game is worth writing down.
        self._game_hint = (time.monotonic(), games.pop() if len(games) == 1 else "", "channel")

    def _got_fullscreen(self, window: tuple[str, str] | None) -> None:
        if window is not None:
            game = naming.game_from_window(*window) or naming.DESKTOP_TAG
            self._game_hint = (time.monotonic(), game, "screen")

    def _on_saved(self, path: str) -> None:
        logs.RECORDER.info("Saved %s", path)
        hint, self._game_hint = self._game_hint, (0.0, "", "")
        volumes = track_volume.changes(self._volumes) if backend.volume_after_save() else {}
        if not volumes:
            self._tag_saved(path, hint)
            return

        def failed(exc: Exception) -> None:
            logs.RECORDER.error("Couldn't set the tracks' volume in %s: %s", path, exc)
            self._tag_saved(path, hint)

        workers.run(lambda: track_volume.apply(path, volumes),
                    lambda _changed: self._tag_saved(path, hint), failed)

    def _tag_saved(self, path: str, hint: tuple[float, str, str]) -> None:
        """Tag a clip just saved with its game, and name it after the game if
        it was playing on the Game channel."""
        when, game, seen = hint
        library = self.context.library
        name = os.path.basename(path)
        tagged = game and time.monotonic() - when < 60 and library is not None and \
            library.tag_recorded(name, game)
        if not tagged:
            self.saved.emit(path)
            return
        if seen == "screen":
            logs.CLIPS.info("Tagged %s with %s (on screen when it was saved)", name, tagged)
            self.saved.emit(path)
            return
        logs.CLIPS.info("Tagged %s with %s (playing on the Game channel)", name, tagged)
        workers.run(lambda: _name_after_game(path, tagged),
                    lambda new_path: self._renamed(path, new_path),
                    lambda exc: self._renamed(path, path, exc))

    def _renamed(self, path: str, new_path: str, error: Exception | None = None) -> None:
        library = self.context.library
        if error is not None:
            logs.CLIPS.error("Couldn't name %s after its game: %s", path, error)
        elif new_path != path and library is not None:
            old, new = os.path.basename(path), os.path.basename(new_path)
            # The library may have listed the new name already, from its own
            # name: the tag and edits of the old one carry over either way.
            library.copy_edits(old, new)
            library.forget(old)
            logs.CLIPS.info("Named %s %s", old, new)
        self.saved.emit(new_path)

    def shutdown(self) -> None:
        self._restart_pending = False
        if self.running:
            logs.RECORDER.info("Stopping the replay buffer (quitting)")
            self.recorder.stop(timeout=3)


def _name_after_game(path: str, game: str) -> str:
    """Rename a clip just saved after its game, Moments style, never over
    another file. Returns its path now."""
    folder, name = os.path.split(path)
    new_name = naming.moments_name(name, game)
    if not new_name:
        return path
    stem, extension = os.path.splitext(new_name)
    target, number = os.path.join(folder, new_name), 1
    while os.path.exists(target):
        number += 1
        target = os.path.join(folder, f"{stem}_{number}{extension}")
    os.rename(path, target)
    return target


# Every notice goes in the log of the part it is about, as serious as it looks.
_NOTICE_LOGS = {"clips": logs.RECORDER, "sonar": logs.SONAR, "vertex": logs.APP}
_NOTICE_LEVELS = {"info": logging.INFO, "ok": logging.INFO, "warn": logging.WARNING,
                  "error": logging.ERROR}


class LevelFeed(QObject):
    """The channels' live levels, for the meters by their faders.
    Read only while a page with meters is on screen and Sonar is on."""

    levels = Signal(dict)                # channel id → how far up its meter goes

    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self._levels = levels.Levels()
        self._wanted: set[str] = set()
        self._running = False
        # Starting and stopping in turn, never side by side.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="levels")
        self._timer = QTimer(self, interval=1000 // 25)
        self._timer.timeout.connect(self._tick)
        context.sonar.status_changed.connect(lambda _s: self._update())

    def want(self, page: str, shown: bool) -> None:
        """A page with meters came on screen, or left it."""
        if shown:
            self._wanted.add(page)
        else:
            self._wanted.discard(page)
        self._update()

    def _update(self) -> None:
        run = bool(self._wanted) and self.context.config.sonar.enabled and \
            self.context.sonar.status.active
        if run == self._running:
            return
        self._running = run
        if run:
            sources = {channel.id: channel.record_source for channel in channels.ALL}
            workers.run(lambda: self._levels.start(sources), None, lambda _exc: None,
                        executor=self._executor)
            self._timer.start()
        else:
            self._timer.stop()
            workers.run(self._levels.stop, None, lambda _exc: None, executor=self._executor)
            self.levels.emit({})

    def _tick(self) -> None:
        self.levels.emit({key: levels.meter_fraction(peak)
                          for key, peak in self._levels.take().items()})

    def shutdown(self) -> None:
        self._timer.stop()
        self._running = False
        self._executor.shutdown(wait=True)
        self._levels.stop()


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
        self._listener = hotkeys.listener(self.pressed.emit, self._result.emit)
        self._result.connect(self._got_result)
        context.config_changed.connect(self.apply)

    def start(self) -> None:
        self._started = True
        self.apply()

    def apply(self) -> None:
        if self._started:
            self._listener.set({} if self._paused else
                               hotkeys.bindings(self.context.config.hotkeys,
                                                self.context.config.recorder.enabled))

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
        # Sonar and its meters, where Sonar can run (platform.SONAR); None elsewhere.
        self.sonar = SonarController(self) if platform.SONAR else None
        self.recorder = RecorderController(self)
        self.levels = LevelFeed(self) if self.sonar is not None else None
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
        if self.sonar is not None:
            self.levels.shutdown()
            self.sonar.shutdown(take_down=True)
        if self.thumbs is not None:
            self.thumbs.shutdown()
        if self.library is not None:
            self.library.close()
