"""Settings: folders and app behaviour, recording, legacy devices, import."""

from __future__ import annotations

import copy
import shlex

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vertex import desktop, paths
from vertex.config import (
    AUDIO_CODECS,
    BITRATE_MODES,
    COLOR_RANGES,
    CONTAINERS,
    ENCODERS,
    FRAMERATE_MODES,
    QUALITIES,
    REPLAY_STORAGES,
    VIDEO_CODECS,
    Config,
)
from vertex.recorder import gsr, monitors
from vertex.ui import theme, workers
from vertex.ui.dialogs.importing import CopyClipsDialog, TagImportDialog
from vertex.ui.settings import monitors as monitor_map
from vertex.ui.widgets import (
    Banner,
    PathField,
    Section,
    Segmented,
    Toggle,
    button,
    label,
)

LABELS = {
    "very_high": "Very high", "qp": "Constant quality (QP)", "vbr": "Variable bitrate",
    "cbr": "Constant bitrate", "vfr": "Variable", "cfr": "Constant",
    "content": "Match content", "ram": "Memory", "disk": "Disk", "gpu": "GPU", "cpu": "CPU",
    "auto": "Automatic", "aac": "AAC", "opus": "Opus", "mp4": "MP4", "mkv": "MKV",
    "hevc": "HEVC", "av1": "AV1", "h264": "H.264", "vp8": "VP8", "vp9": "VP9",
    "hevc_10bit": "HEVC 10-bit", "av1_10bit": "AV1 10-bit", "hevc_hdr": "HEVC HDR",
    "av1_hdr": "AV1 HDR", "screen": "Automatic", "portal": "Portal (asks once)",
    "focused": "Focused window (X11)", "region": "Region", "limited": "Limited",
    "full": "Full",
}


def combo(values, current: str, editable: bool = False) -> QComboBox:
    widget = QComboBox()
    widget.setEditable(editable)
    for value in values:
        widget.addItem(LABELS.get(value, value.replace("_", " ").capitalize()), value)
    index = widget.findData(current)
    if index < 0 and current:
        widget.addItem(current, current)
        index = widget.count() - 1
    widget.setCurrentIndex(max(0, index))
    return widget


def scroll_page(*sections) -> QScrollArea:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 12, 24)
    layout.setSpacing(16)
    for section in sections:
        layout.addWidget(section)
    layout.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidget(page)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    return scroll


class SettingsView(QWidget):
    saved = Signal(bool)             # folders changed
    imported = Signal()

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.CONTENT_MARGIN, 18, theme.CONTENT_MARGIN - 12, 12)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(label("Settings", "Heading"))
        header.addStretch(1)
        self.revert_button = button("Revert", "ghost", on_click=self.load)
        self.save_button = button("Save", "primary", on_click=self.save)
        header.addWidget(self.revert_button)
        header.addWidget(self.save_button)
        header.setContentsMargins(0, 0, 12, 0)
        layout.addLayout(header)
        self.tabs = Segmented([("general", "General"), ("recording", "Recording"),
                               ("devices", "Older clips"), ("import", "Import")], "general")
        self.tabs.changed.connect(lambda key, _d: self.show_page(key))
        layout.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignLeft)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.banner = Banner()
        layout.addWidget(self.banner)
        self.pages = {}
        # What GSR said it can record; empty until asked, or if it can't be run.
        self._capture_options: list[gsr.CaptureOption] = []
        self._build_general()
        self._build_recording()
        self._build_devices()
        self._build_import()
        self.load()

    def show_page(self, key: str) -> None:
        self.tabs.set_current(key)
        self.stack.setCurrentWidget(self.pages[key])
        if key == "recording":
            self._refresh_recorder()

    # --- Pages ----------------------------------------------------------------

    def _build_general(self) -> None:
        folders = Section("Folders", "Where clips are recorded and scanned from, and where "
                                     "exports go. Your recordings are never modified.")
        self.clip_path = PathField(placeholder="~/Videos/Game Recordings")
        self.export_path = PathField(placeholder="~/Videos/Game Recordings/Vertex/Exports")
        folders.add_row("Clips", self.clip_path)
        folders.add_row("Exports", self.export_path)
        self.data_path = PathField(placeholder=str(paths.default_data_dir()))
        self.state_path = PathField(placeholder=str(paths.default_state_dir()))
        self.cache_path = PathField(placeholder=str(paths.default_cache_dir()))
        folders.add_row("Library", self.data_path, "Tags, titles, trims and mixes")
        folders.add_row("State", self.state_path)
        folders.add_row("Cache", self.cache_path, "Thumbnails; safe to delete")
        for field in (self.clip_path, self.export_path, self.data_path, self.state_path,
                      self.cache_path):
            field.setMinimumWidth(420)

        behaviour = Section("Behaviour")
        self.close_to_tray = Toggle()
        behaviour.add_row("Keep running in the tray when the window is closed",
                          self.close_to_tray, "Sonar routing and the replay buffer keep "
                          "working; quit from the tray menu.")
        self.autostart = Toggle()
        behaviour.add_row("Start Vertex when you log in", self.autostart,
                          "Starts hidden in the tray.")
        install = button("Add to start menu", on_click=self._install_desktop)
        behaviour.add_row("Start menu entry and icon", install,
                          "Also available as `vertex install-desktop`.")

        look = Section("Appearance", "The logo ships in two inks; the app cannot see the "
                                     "panel its icon sits on, so you pick.")
        self.logo = Segmented([("light", "Light ink (dark panels)"),
                               ("dark", "Dark ink (light panels)")], "light")
        look.add(self.logo)
        self.pages["general"] = scroll_page(folders, behaviour, look)
        self.stack.addWidget(self.pages["general"])

    def _build_recording(self) -> None:
        status = Section("GPU Screen Recorder", "Vertex runs GPU Screen Recorder's replay "
                                                "buffer and saves clips into the clips folder.")
        self.gsr_status = label("", "Muted", wrap=True)
        status.add(self.gsr_status)
        self.command = QLineEdit()
        self.command.setPlaceholderText("gpu-screen-recorder")
        self.command.setMinimumWidth(380)
        status.add_row("Command", self.command, "For the Flatpak: flatpak run "
                       "--command=gpu-screen-recorder com.dec05eba.gpu_screen_recorder")
        self.rec_autostart = Toggle()
        status.add_row("Start the replay buffer with Vertex", self.rec_autostart)

        hotkey = Section("Saving a clip", "Desktops bind global shortcuts to commands. Bind "
                                          "this one to a key in your desktop's keyboard "
                                          "settings and it saves the replay buffer from "
                                          "anywhere, in or out of a game:")
        row = QHBoxLayout()
        command = QLineEdit("vertex save-clip")
        command.setReadOnly(True)
        command.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        row.addWidget(command, 1)
        row.addWidget(button("Copy", on_click=lambda: QGuiApplication.clipboard().setText(
            "vertex save-clip")))
        hotkey.body.addLayout(row)
        hotkey.add(label("Save only the end of the buffer with `vertex save-clip --last 30` "
                         "(10, 30, 60, 300, 600 or 1800 seconds).", "Dim", wrap=True))
        self.tag_from_game = Toggle()
        hotkey.add_row("Tag new clips with the game on the Game channel", self.tag_from_game,
                       "Needs Sonar. Only when exactly one app is playing there.")

        video = Section("Video")
        self.capture = QComboBox()
        self.capture.setMinimumWidth(260)
        video.add_row("Capture", self.capture, "Click a monitor to record it. Automatic "
                      "records the first monitor GPU Screen Recorder finds; portal works "
                      "on any Wayland desktop and asks once which screen to share.")
        self.monitor_map = monitor_map.MonitorMap()
        self.monitor_map.picked.connect(self._pick_monitor)
        self.capture.currentIndexChanged.connect(
            lambda _i: self.monitor_map.set_current(self.capture.currentData() or ""))
        video.add(self.monitor_map)
        # Plugging in, unplugging or rearranging monitors redraws the map.
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._watch_screen)
        app.screenRemoved.connect(self._screens_changed)
        for screen in app.screens():
            self._watch_screen(screen, initial=True)
        self.region = QLineEdit()
        self.region.setPlaceholderText("1920x1080+0+0")
        video.add_row("Region", self.region, "Only for Region capture: WxH+X+Y")
        self.resolution = QLineEdit()
        self.resolution.setPlaceholderText("Original")
        video.add_row("Resolution limit", self.resolution, "e.g. 1920x1080; blank keeps the "
                      "source size")
        self.fps = QSpinBox()
        self.fps.setRange(1, 500)
        video.add_row("Frame rate", self.fps)
        self.framerate_mode = combo(FRAMERATE_MODES, "vfr")
        video.add_row("Frame rate mode", self.framerate_mode)
        self.video_codec = combo(VIDEO_CODECS, "auto")
        video.add_row("Codec", self.video_codec, "H.264 plays everywhere a clip is shared")
        self.bitrate_mode = combo(BITRATE_MODES, "auto")
        video.add_row("Bitrate mode", self.bitrate_mode, "Constant bitrate keeps the "
                      "buffer's memory use predictable")
        self.quality = combo(QUALITIES, "very_high")
        video.add_row("Quality", self.quality, "For constant quality and variable bitrate")
        self.bitrate = QSpinBox()
        self.bitrate.setRange(500, 500000)
        self.bitrate.setSuffix(" kbps")
        self.bitrate.setSingleStep(1000)
        video.add_row("Bitrate", self.bitrate, "For constant bitrate")
        self.container = combo(CONTAINERS, "mp4")
        video.add_row("Container", self.container)
        self.color_range = combo(COLOR_RANGES, "limited")
        video.add_row("Color range", self.color_range)
        self.encoder = combo(ENCODERS, "gpu")
        video.add_row("Encoder", self.encoder)
        self.keyint = QDoubleSpinBox()
        self.keyint.setRange(0.5, 10)
        self.keyint.setSingleStep(0.5)
        self.keyint.setSuffix(" s")
        video.add_row("Keyframe interval", self.keyint, "Shorter means more precise trims")
        self.cursor = Toggle()
        video.add_row("Record the cursor", self.cursor)
        self.restore_portal = Toggle()
        video.add_row("Remember the portal choice", self.restore_portal)

        replay = Section("Replay buffer")
        self.replay_seconds = QSpinBox()
        self.replay_seconds.setRange(gsr.REPLAY_MIN, 3600)
        self.replay_seconds.setSuffix(" s")
        replay.add_row("Keep the last", self.replay_seconds)
        self.replay_storage = combo(REPLAY_STORAGES, "ram")
        replay.add_row("Buffer in", self.replay_storage, "Disk saves memory on long buffers")
        self.output_dir = PathField(placeholder="The clips folder")
        self.output_dir.setMinimumWidth(380)
        replay.add_row("Save clips to", self.output_dir)

        audio = Section("Audio", "With Sonar on, every recorded channel is its own track — "
                                 "choose which on the Sonar page.")
        self.audio_codec = combo(AUDIO_CODECS, "aac")
        audio.add_row("Codec", self.audio_codec)
        self.audio_bitrate = QSpinBox()
        self.audio_bitrate.setRange(0, 512)
        self.audio_bitrate.setSpecialValueText("Automatic")
        self.audio_bitrate.setSuffix(" kbps")
        audio.add_row("Bitrate", self.audio_bitrate)
        self.audio_sources = QPlainTextEdit()
        self.audio_sources.setPlaceholderText("default_output\ndefault_input")
        self.audio_sources.setFixedHeight(84)
        self.audio_sources.setMinimumWidth(320)
        audio.add_row("Tracks without Sonar", self.audio_sources,
                      "One per line: default_output, default_input, device:<name>, "
                      "app:<name>; join sources into one track with |")
        self.audio_devices = label("", "Dim", wrap=True)
        audio.add(self.audio_devices)

        advanced = Section("Advanced")
        self.extra_args = QLineEdit()
        self.extra_args.setPlaceholderText("-tune quality -low-power yes")
        advanced.add_row("Extra arguments", self.extra_args)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.preview.setFixedHeight(96)
        advanced.add(label("The command Vertex will run:", "Dim"))
        advanced.add(self.preview)

        for widget in (self.command, self.region, self.resolution, self.extra_args):
            widget.textChanged.connect(self._update_preview)
        for widget in (self.fps, self.bitrate, self.replay_seconds, self.audio_bitrate):
            widget.valueChanged.connect(self._update_preview)
        self.keyint.valueChanged.connect(self._update_preview)
        for widget in (self.capture, self.framerate_mode, self.video_codec, self.bitrate_mode,
                       self.quality, self.container, self.color_range, self.encoder,
                       self.replay_storage, self.audio_codec):
            widget.currentIndexChanged.connect(self._update_preview)
            widget.editTextChanged.connect(self._update_preview)
        self.audio_sources.textChanged.connect(self._update_preview)
        for toggle in (self.cursor, self.restore_portal):
            toggle.toggled.connect(self._update_preview)

        self.pages["recording"] = scroll_page(status, hotkey, replay, video, audio, advanced)
        self.stack.addWidget(self.pages["recording"])

    def _build_devices(self) -> None:
        section = Section("Capture devices of older clips",
                          "Clips recorded before Sonar name their tracks after whatever "
                          "device recorded them. Name those devices here and the editor "
                          "labels their lanes Game, Chat and Microphone. Clips recorded "
                          "through Sonar don't need this.")
        self.legacy = {}
        for key, title in (("game_device", "Game audio"), ("chat_device", "Chat audio"),
                           ("mic_device", "Microphone")):
            field = QComboBox()
            field.setEditable(True)
            field.setMinimumWidth(380)
            self.legacy[key] = field
            section.add_row(title, field)
        self.pages["devices"] = scroll_page(section)
        self.stack.addWidget(self.pages["devices"])

    def _build_import(self) -> None:
        copy_section = Section("Copy clips in", "Bring recordings from another folder — "
                                                "a SteelSeries Moments library, say — into "
                                                "the clips folder.")
        copy_section.add(button("Copy clips…", on_click=self._copy_clips))
        tag_section = Section("Tag from file names", "SteelSeries Moments names clips after "
                                                     "the game. Review the games found in the "
                                                     "clips folder and tag them in one go.")
        tag_section.add(button("Review tags…", on_click=self._tag_clips))
        self.pages["import"] = scroll_page(copy_section, tag_section)
        self.stack.addWidget(self.pages["import"])

    # --- Load / collect / save -------------------------------------------------

    def load(self) -> None:
        config = self.context.config
        self.clip_path.set_value(config.clip_path)
        self.export_path.set_value(config.export_path)
        self.data_path.set_value(config.data_path)
        self.state_path.set_value(config.state_path)
        self.cache_path.set_value(config.cache_path)
        self.close_to_tray.setChecked(config.close_to_tray)
        self.autostart.setChecked(desktop.autostart_enabled())
        self.logo.set_current(config.logo_variant)

        rec = config.recorder
        self.command.setText(rec.command)
        self.rec_autostart.setChecked(rec.autostart)
        self.tag_from_game.setChecked(rec.tag_from_game_channel)
        self._show_capture(rec.capture)
        self.region.setText(rec.region)
        self.resolution.setText(rec.resolution)
        self.fps.setValue(rec.fps)
        _set_combo(self.framerate_mode, rec.framerate_mode)
        _set_combo(self.video_codec, rec.video_codec)
        _set_combo(self.bitrate_mode, rec.bitrate_mode)
        _set_combo(self.quality, rec.quality)
        self.bitrate.setValue(rec.bitrate_kbps)
        _set_combo(self.container, rec.container)
        _set_combo(self.color_range, rec.color_range)
        _set_combo(self.encoder, rec.encoder)
        self.keyint.setValue(rec.keyframe_interval)
        self.cursor.setChecked(rec.cursor)
        self.restore_portal.setChecked(rec.restore_portal_session)
        self.replay_seconds.setValue(rec.replay_seconds)
        _set_combo(self.replay_storage, rec.replay_storage)
        self.output_dir.set_value(rec.output_dir)
        _set_combo(self.audio_codec, rec.audio_codec)
        self.audio_bitrate.setValue(rec.audio_bitrate)
        self.audio_sources.setPlainText("\n".join(rec.audio_sources))
        self.extra_args.setText(rec.extra_args)
        for key, field in self.legacy.items():
            field.setEditText(getattr(config, key))
        self._update_preview()

    def collect(self) -> Config:
        config = copy.deepcopy(self.context.config)
        config.clip_path = self.clip_path.value()
        config.export_path = self.export_path.value()
        config.data_path = self.data_path.value()
        config.state_path = self.state_path.value()
        config.cache_path = self.cache_path.value()
        config.close_to_tray = self.close_to_tray.isChecked()
        config.logo_variant = self.logo.current
        rec = config.recorder
        rec.command = self.command.text().strip() or "gpu-screen-recorder"
        rec.autostart = self.rec_autostart.isChecked()
        rec.tag_from_game_channel = self.tag_from_game.isChecked()
        rec.capture = self.capture.currentData() or "screen"
        rec.region = self.region.text().strip()
        rec.resolution = self.resolution.text().strip()
        rec.fps = self.fps.value()
        rec.framerate_mode = self.framerate_mode.currentData()
        rec.video_codec = self.video_codec.currentData()
        rec.bitrate_mode = self.bitrate_mode.currentData()
        rec.quality = self.quality.currentData()
        rec.bitrate_kbps = self.bitrate.value()
        rec.container = self.container.currentData()
        rec.color_range = self.color_range.currentData()
        rec.encoder = self.encoder.currentData()
        rec.keyframe_interval = self.keyint.value()
        rec.cursor = self.cursor.isChecked()
        rec.restore_portal_session = self.restore_portal.isChecked()
        rec.replay_seconds = self.replay_seconds.value()
        rec.replay_storage = self.replay_storage.currentData()
        rec.output_dir = self.output_dir.value()
        rec.audio_codec = self.audio_codec.currentData()
        rec.audio_bitrate = self.audio_bitrate.value()
        rec.audio_sources = [line.strip() for line in
                             self.audio_sources.toPlainText().splitlines() if line.strip()]
        rec.extra_args = self.extra_args.text().strip()
        for key, field in self.legacy.items():
            setattr(config, key, field.currentText().strip())
        return config

    def is_dirty(self) -> bool:
        return self.collect().to_dict() != self.context.config.to_dict() or \
            self.autostart.isChecked() != desktop.autostart_enabled()

    def save(self) -> bool:
        new = self.collect()
        problems = gsr.validate(new.recorder)
        if problems:
            self.banner.show_message("Recording: " + problems[0], "error", 10000)
            self.show_page("recording")
            return False
        if not new.is_complete():
            self.banner.show_message("Set the clips, exports, library, state and cache "
                                     "folders (blank uses the defaults).", "error", 10000)
            if not new.resolved_clip_dir() or not new.resolved_export_dir():
                self.show_page("general")
                return False
        old = self.context.config
        folders_changed = any(getattr(new, key) != getattr(old, key) for key in
                              ("clip_path", "data_path", "cache_path", "state_path"))
        recorder_changed = new.recorder != old.recorder
        for key in ("clip_path", "export_path", "data_path", "state_path", "cache_path",
                    "close_to_tray", "logo_variant", "game_device", "chat_device",
                    "mic_device"):
            setattr(old, key, getattr(new, key))
        old.recorder = new.recorder
        old.ensure_dirs()
        self.context.save_config()
        if self.autostart.isChecked() != desktop.autostart_enabled():
            desktop.set_autostart(self.autostart.isChecked())
        if recorder_changed:
            self.context.recorder.detect()
            self.context.recorder.restart_if_running()
        self.banner.show_message("Saved.", "ok", 3000)
        self.saved.emit(folders_changed)
        return True

    # --- Recorder helpers ---------------------------------------------------------

    def _refresh_recorder(self) -> None:
        command = self.command.text().strip() or "gpu-screen-recorder"

        def probe():
            info = gsr.detect(command)
            if not info.available:
                return info, [], []
            return info, gsr.list_capture_options(command), gsr.list_audio_devices(command)

        workers.run(probe, self._show_recorder, lambda _exc: None)

    def _show_recorder(self, result) -> None:
        info, captures, devices = result
        if info.available:
            note = "" if info.supports_track_names else \
                " — update to 5.15+ to name clip tracks by Sonar channel"
            self.gsr_status.setText(f"Found GPU Screen Recorder {info.version_text}{note}.")
            self.gsr_status.setStyleSheet(f"color: {theme.OK if not note else theme.WARN};")
        else:
            self.gsr_status.setText(info.error)
            self.gsr_status.setStyleSheet(f"color: {theme.WARN};")
        self._capture_options = captures
        self._show_capture(self.capture.currentData() or "screen")
        if devices:
            names = ", ".join(name for name, _desc in devices[:12])
            self.audio_devices.setText(f"Devices GPU Screen Recorder can record: {names}"
                                       f"{'…' if len(devices) > 12 else ''}")
        sources = [name for name, _desc in devices if name.endswith(".monitor") or
                   not name.startswith("default_")]
        for field in self.legacy.values():
            text = field.currentText()
            field.clear()
            field.addItems(sources)
            field.setEditText(text)

    # --- Capture --------------------------------------------------------------------

    def _show_capture(self, current: str) -> None:
        """Draw the monitors and list every capture option, keeping `current`."""
        arranged = monitors.arrange(self._capture_options, monitor_map.desktop_screens())
        self.monitor_map.set_monitors(arranged)
        items = [("screen", LABELS["screen"])]
        for monitor in arranged:
            size = monitor_map.resolution(monitor)
            items.append((monitor.name, f"Monitor {monitor.name} ({size})" if size
                          else f"Monitor {monitor.name}"))
        if self._capture_options:
            # A window is recorded by its id, which changes every time it opens.
            others = [o for o in self._capture_options
                      if o.kind not in ("monitor", "window", "screen")]
        else:
            others = [gsr.CaptureOption(value, value) for value in ("portal", "focused", "region")]
        for option in others:
            text = f"Camera {option.value}" if option.kind == "camera" else \
                LABELS.get(option.value, option.value)
            items.append((option.value, text))
        if current and current not in [value for value, _text in items]:
            items.append((current, LABELS.get(current) or f"{current} (not found)"))
        self.capture.blockSignals(True)
        self.capture.clear()
        for value, text in items:
            self.capture.addItem(text, value)
        self.capture.setCurrentIndex(max(0, self.capture.findData(current)))
        self.capture.blockSignals(False)
        self.monitor_map.set_current(self.capture.currentData() or "")

    def _pick_monitor(self, name: str) -> None:
        index = self.capture.findData(name)
        if index >= 0:
            self.capture.setCurrentIndex(index)

    def _watch_screen(self, screen, initial: bool = False) -> None:
        screen.geometryChanged.connect(self._screens_changed)
        if not initial:
            self._screens_changed()

    def _screens_changed(self, *_args) -> None:
        # Qt may still list a screen while announcing its removal; look once it's gone.
        QTimer.singleShot(0, self._rearrange)

    def _rearrange(self) -> None:
        self._show_capture(self.capture.currentData() or "screen")
        if self.stack.currentWidget() is self.pages.get("recording"):
            self._refresh_recorder()     # GSR's list changes with the monitors

    def _update_preview(self) -> None:
        try:
            config = self.collect()
            argv = gsr.build_argv(config.recorder, gsr.audio_tracks(config),
                                  config.resolved_recording_dir(), self.context.recorder.info)
            self.preview.setPlainText(shlex.join(argv))
        except ValueError as exc:
            self.preview.setPlainText(f"(not valid yet: {exc})")

    # --- Actions -----------------------------------------------------------------

    def _install_desktop(self) -> None:
        written = desktop.install(self.logo.current)
        self.banner.show_message(f"Added to the start menu ({len(written)} files).", "ok")

    def _copy_clips(self) -> None:
        target = self.context.config.resolved_clip_dir()
        dialog = CopyClipsDialog(self, target)
        if dialog.exec() and dialog.copied:
            self.imported.emit()
            self.banner.show_message(f"Copied {len(dialog.copied)} clips. Review their tags "
                                     "next.", "ok")

    def _tag_clips(self) -> None:
        if self.context.library is None:
            return
        dialog = TagImportDialog(self, self.context.library,
                                 self.context.config.resolved_clip_dir())
        if dialog.exec():
            self.imported.emit()
            self.banner.show_message(f"Tagged {dialog.written} clips.", "ok")


def _set_combo(widget: QComboBox, value: str) -> None:
    index = widget.findData(value)
    if index < 0:
        widget.addItem(LABELS.get(value, value), value)
        index = widget.count() - 1
    widget.setCurrentIndex(index)

