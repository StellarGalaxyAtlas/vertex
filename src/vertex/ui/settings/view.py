"""Settings: folders and app behaviour, recording, notifications, import."""

from __future__ import annotations

import copy
import dataclasses
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

from vertex import desktop, fmt, paths
from vertex.audio import channels
from vertex.config import (
    AUDIO_CODECS,
    BITRATE_MODES,
    COLOR_RANGES,
    CONTAINERS,
    ENCODERS,
    FRAMERATE_MODES,
    REPLAY_STORAGES,
    VIDEO_CODECS,
    Config,
)
from vertex.core import storage
from vertex.recorder import gsr, monitors, presets
from vertex.ui import screens, theme, workers
from vertex.ui.dialogs.importing import CopyClipsDialog, TagImportDialog
from vertex.ui.settings import monitors as monitor_map
from vertex.ui.settings.notifications import NotificationsPage
from vertex.ui.widgets import (
    Banner,
    Disclosure,
    FieldGrid,
    Meter,
    PathField,
    Section,
    Segmented,
    StorageGauge,
    Toggle,
    button,
    label,
    setting_row,
)

LABELS = {
    "very_high": "Very high", "qp": "Constant quality (QP)", "vbr": "Variable bitrate",
    "cbr": "Constant bitrate", "vfr": "Variable", "cfr": "Constant",
    "content": "Match content", "ram": "Memory", "disk": "Disk", "gpu": "GPU", "cpu": "CPU",
    "auto": "Automatic", "aac": "AAC", "opus": "Opus", "mp4": "MP4", "mkv": "MKV",
    "hevc": "HEVC", "av1": "AV1", "h264": "H.264", "vp8": "VP8", "vp9": "VP9",
    "hevc_10bit": "HEVC 10-bit", "av1_10bit": "AV1 10-bit", "hevc_hdr": "HEVC HDR",
    "av1_hdr": "AV1 HDR", "limited": "Limited", "full": "Full",
}


# Video quality levels by GSR's names (see recorder.presets), as Settings calls them.
QUALITY_NAMES = {"medium": "Low", "high": "Medium", "very_high": "High", "ultra": "Ultra"}


def mbps(kbps: int) -> str:
    return f"{kbps / 1000:g} Mbps"


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
                               ("notifications", "Notifications"), ("import", "Import")],
                              "general")
        self.tabs.changed.connect(lambda key, _d: self.show_page(key))
        layout.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignLeft)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.banner = Banner()
        layout.addWidget(self.banner)
        self.pages = {}
        # What GSR said it can record; empty until asked, or if it can't be run.
        self._capture_options: list[gsr.CaptureOption] = []
        # The monitor picked, as saved. Older settings may hold something
        # else ("screen", "portal"…), which records the primary monitor.
        self._capture = "screen"
        # The disk the clips go to, once measured.
        self._storage: storage.StorageStats | None = None
        # The audio devices GSR said it can record: (name, description).
        self._audio_devices: list[tuple[str, str]] = []
        self._build_general()
        self._build_recording()
        self.notifications = NotificationsPage()
        self.pages["notifications"] = scroll_page(*self.notifications.sections)
        self.stack.addWidget(self.pages["notifications"])
        self._build_import()
        self.load()

    def show_page(self, key: str) -> None:
        self.tabs.set_current(key)
        self.stack.setCurrentWidget(self.pages[key])
        if key == "recording":
            self._refresh_recorder()
            self._refresh_storage()

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
        # Vertex's own folders: set up once, and best left alone.
        self.folders_advanced = Disclosure("Advanced", "Where Vertex keeps its library, "
                                                       "state and cache")
        self.folders_advanced.body_layout.setSpacing(12)
        for title, field, hint in (
                ("Library", self.data_path, "Tags, titles, trims and mixes"),
                ("State", self.state_path, "What Vertex remembers between runs"),
                ("Cache", self.cache_path, "Thumbnails; safe to delete")):
            self.folders_advanced.add(setting_row(title, field, hint))
        folders.add(self.folders_advanced)
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

        clips = Section("Recording Settings", "Lower settings make smaller clips and leave "
                                              "more of your computer to the game.")
        self.capture_note = label("", "Muted")
        clips.add_row("Monitor", self.capture_note, "Click the monitor to record.")
        self.monitor_map = monitor_map.MonitorMap()
        self.monitor_map.picked.connect(self._pick_monitor)
        clips.add(self.monitor_map)
        # Plugging in, unplugging or rearranging monitors redraws the map.
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._watch_screen)
        app.screenRemoved.connect(self._screens_changed)
        for screen in app.screens():
            self._watch_screen(screen, initial=True)
        self.duration = QComboBox()
        self.video_quality = QComboBox()
        self.resolution = QComboBox()
        self.fps = QComboBox()
        grid = FieldGrid()
        for title, widget in (("Duration", self.duration), ("Video quality", self.video_quality),
                              ("Resolution", self.resolution), ("Frame rate", self.fps)):
            grid.add(title, widget)
        clips.add(grid)
        self.cursor = Toggle()
        clips.add_row("Record the cursor", self.cursor)
        self.game_audio = QComboBox()
        self.chat_audio = QComboBox()
        self.mic_audio = QComboBox()
        tracks = FieldGrid(field_width=190)
        for title, widget in (("Game audio", self.game_audio), ("Chat audio", self.chat_audio),
                              ("Microphone", self.mic_audio)):
            tracks.add(title, widget)
        clips.add(tracks)
        clips.add(label("Each is its own track in your clips. While Sonar is off, its "
                        "channels record the default output and microphone instead.",
                        "Dim", wrap=True))
        clips.add(self._build_estimate())

        advanced = Disclosure("Advanced", "Bitrate, codecs, audio, where clips go, and the "
                                          "recorder's command")
        video = Section("Video")
        self.bitrate_mode = combo(BITRATE_MODES, "cbr")
        video.add_row("Bitrate mode", self.bitrate_mode, "Constant bitrate keeps clip sizes "
                      "and the buffer's memory use predictable")
        self.bitrate = QSpinBox()
        self.bitrate.setRange(0, 500000)
        self.bitrate.setSingleStep(1000)
        self.bitrate.setSuffix(" kbps")
        self.bitrate.setSpecialValueText("From video quality")
        video.add_row("Bitrate", self.bitrate, "For constant bitrate: set one by hand instead "
                      "of what the video quality comes to")
        self.video_codec = combo(VIDEO_CODECS, "auto")
        video.add_row("Codec", self.video_codec, "H.264 plays everywhere a clip is shared")
        self.framerate_mode = combo(FRAMERATE_MODES, "vfr")
        video.add_row("Frame rate mode", self.framerate_mode)
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

        replay = Section("Replay buffer")
        self.replay_storage = combo(REPLAY_STORAGES, "ram")
        replay.add_row("Buffer in", self.replay_storage, "Disk saves memory on long buffers")
        self.output_dir = PathField(placeholder="The clips folder")
        self.output_dir.setMinimumWidth(380)
        replay.add_row("Save clips to", self.output_dir, "Blank saves them into the clips "
                       "folder set under General")
        self.clip_path.changed.connect(self._show_clips_folder)

        audio = Section("Audio", "How the tracks chosen under Recording Settings are "
                                 "encoded.")
        self.audio_codec = combo(AUDIO_CODECS, "aac")
        audio.add_row("Codec", self.audio_codec)
        self.audio_bitrate = QSpinBox()
        self.audio_bitrate.setRange(0, 512)
        self.audio_bitrate.setSpecialValueText("Automatic")
        self.audio_bitrate.setSuffix(" kbps")
        audio.add_row("Bitrate", self.audio_bitrate)

        recorder = Section("Recorder")
        self.command = QLineEdit()
        self.command.setPlaceholderText("gpu-screen-recorder")
        self.command.setMinimumWidth(380)
        recorder.add_row("Command", self.command, "For the Flatpak: flatpak run "
                         "--command=gpu-screen-recorder com.dec05eba.gpu_screen_recorder")
        self.extra_args = QLineEdit()
        self.extra_args.setPlaceholderText("-tune quality -low-power yes")
        self.extra_args.setMinimumWidth(380)
        recorder.add_row("Extra arguments", self.extra_args)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.preview.setFixedHeight(96)
        recorder.add(label("The command Vertex will run:", "Dim"))
        recorder.add(self.preview)
        for section in (video, replay, audio, recorder):
            advanced.add(section)

        # The clip settings change what each other offers (sizes up to the
        # monitor's, bitrates for the size and frame rate) and the estimate.
        for widget in (self.duration, self.resolution, self.fps, self.bitrate_mode,
                       self.replay_storage, self.audio_codec):
            widget.currentIndexChanged.connect(self._clip_settings_changed)
        self.video_quality.activated.connect(self._pick_quality)
        for widget in (self.bitrate, self.audio_bitrate):
            widget.valueChanged.connect(self._clip_settings_changed)
        for widget in (self.game_audio, self.chat_audio, self.mic_audio):
            widget.currentIndexChanged.connect(self._clip_settings_changed)
        for widget in (self.command, self.extra_args):
            widget.textChanged.connect(self._update_preview)
        self.keyint.valueChanged.connect(self._update_preview)
        for widget in (self.framerate_mode, self.video_codec, self.container, self.color_range,
                       self.encoder):
            widget.currentIndexChanged.connect(self._update_preview)
        self.cursor.toggled.connect(self._update_preview)

        self.pages["recording"] = scroll_page(status, clips, hotkey, advanced)
        self.stack.addWidget(self.pages["recording"])

    def _build_estimate(self) -> QWidget:
        """How big a clip gets with these settings, and how many fit on the disk."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(24)
        halves = []
        for title in ("CLIP SIZE", "DISK SPACE"):
            column = QVBoxLayout()
            column.setSpacing(6)
            column.addWidget(label(title, "Group"))
            figure = label()
            figure.setStyleSheet("font-size: 13pt; font-weight: 600;")
            column.addWidget(figure)
            halves.append((column, figure))
        (left, self.clip_size), (right, self.disk_room) = halves
        self.clip_meter = Meter()
        left.addWidget(self.clip_meter)
        self.clip_detail = label("", "Dim", wrap=True)
        left.addWidget(self.clip_detail)
        left.addStretch(1)
        self.disk_gauge = StorageGauge()
        right.addWidget(self.disk_gauge)
        right.addStretch(1)
        row.addLayout(left, 1)
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background: {theme.LINE};")
        row.addWidget(divider)
        row.addLayout(right, 1)
        return box

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
        self.notifications.load(config.notifications)

        rec = config.recorder
        self.command.setText(rec.command)
        self.rec_autostart.setChecked(rec.autostart)
        self.tag_from_game.setChecked(rec.tag_from_game_channel)
        self._capture = rec.capture
        self._show_capture()
        _set_combo(self.framerate_mode, rec.framerate_mode)
        _set_combo(self.video_codec, rec.video_codec)
        _set_combo(self.bitrate_mode, rec.bitrate_mode)
        self.bitrate.setValue(rec.bitrate_kbps)
        _set_combo(self.container, rec.container)
        _set_combo(self.color_range, rec.color_range)
        _set_combo(self.encoder, rec.encoder)
        self.keyint.setValue(rec.keyframe_interval)
        self.cursor.setChecked(rec.cursor)
        _set_combo(self.replay_storage, rec.replay_storage)
        self.output_dir.set_value(rec.output_dir)
        self._show_clips_folder(config.resolved_clip_dir())
        _set_combo(self.audio_codec, rec.audio_codec)
        self.audio_bitrate.setValue(rec.audio_bitrate)
        self.extra_args.setText(rec.extra_args)
        self._show_clip_choices(rec)
        self._update_preview()
        self._show_estimate()

    def collect(self) -> Config:
        config = copy.deepcopy(self.context.config)
        config.clip_path = self.clip_path.value()
        config.export_path = self.export_path.value()
        config.data_path = self.data_path.value()
        config.state_path = self.state_path.value()
        config.cache_path = self.cache_path.value()
        config.close_to_tray = self.close_to_tray.isChecked()
        config.logo_variant = self.logo.current
        config.notifications = self.notifications.choices()
        rec = config.recorder
        rec.command = self.command.text().strip() or "gpu-screen-recorder"
        rec.autostart = self.rec_autostart.isChecked()
        rec.tag_from_game_channel = self.tag_from_game.isChecked()
        rec.capture = self._capture
        # Empty only while the page is first being filled in.
        for widget, name in ((self.duration, "replay_seconds"), (self.resolution, "resolution"),
                             (self.fps, "fps")):
            if widget.currentData() is not None:
                setattr(rec, name, widget.currentData())
        if self.video_quality.currentData() not in (None, "custom"):
            rec.quality = self.video_quality.currentData()
        rec.framerate_mode = self.framerate_mode.currentData()
        rec.video_codec = self.video_codec.currentData()
        rec.bitrate_mode = self.bitrate_mode.currentData()
        rec.bitrate_kbps = self.bitrate.value()
        rec.container = self.container.currentData()
        rec.color_range = self.color_range.currentData()
        rec.encoder = self.encoder.currentData()
        rec.keyframe_interval = self.keyint.value()
        rec.cursor = self.cursor.isChecked()
        rec.replay_storage = self.replay_storage.currentData()
        rec.output_dir = self.output_dir.value()
        rec.audio_codec = self.audio_codec.currentData()
        rec.audio_bitrate = self.audio_bitrate.value()
        for widget, name in ((self.game_audio, "game_audio"), (self.chat_audio, "chat_audio"),
                             (self.mic_audio, "mic_audio")):
            if widget.currentData() is not None:
                setattr(rec, name, widget.currentData())
        rec.extra_args = self.extra_args.text().strip()
        return config

    def is_dirty(self) -> bool:
        return self.collect().to_dict() != self.context.config.to_dict() or \
            self.autostart.isChecked() != desktop.autostart_enabled()

    def save(self) -> bool:
        new = self.collect()
        problems = gsr.validate(self._as_recorded(new.recorder))
        if problems:
            self.banner.show_message("Recording: " + problems[0], "error", 10000)
            self.show_page("recording")
            return False
        if not new.is_complete():
            self.banner.show_message("Set the clips, exports, library, state and cache "
                                     "folders (blank uses the defaults).", "error", 10000)
            self.folders_advanced.set_expanded(True)
            if not new.resolved_clip_dir() or not new.resolved_export_dir():
                self.show_page("general")
                return False
        old = self.context.config
        folders_changed = any(getattr(new, key) != getattr(old, key) for key in
                              ("clip_path", "data_path", "cache_path", "state_path"))
        recorder_changed = new.recorder != old.recorder
        if new.logo_variant != old.logo_variant:
            # The start-menu icon follows the logo ink.
            variant = new.logo_variant
            workers.run(lambda: desktop.update_icons(variant), None, lambda _exc: None)
        for key in ("clip_path", "export_path", "data_path", "state_path", "cache_path",
                    "close_to_tray", "logo_variant", "notifications"):
            setattr(old, key, getattr(new, key))
        old.recorder = new.recorder
        old.ensure_dirs()
        self.context.save_config()
        if self.autostart.isChecked() != desktop.autostart_enabled():
            desktop.set_autostart(self.autostart.isChecked())
        restarting = recorder_changed and self.context.recorder.running
        if recorder_changed:
            self.context.recorder.detect()
            self.context.recorder.restart_if_running()
        self.banner.show_message("Saved. Restarting the replay buffer to use the new "
                                 "settings." if restarting else "Saved.", "ok", 5000)
        self._refresh_storage()
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
                " — update to 5.15+ so clip tracks are named Game, Chat and Microphone"
            self.gsr_status.setText(f"Found GPU Screen Recorder {info.version_text}{note}.")
            self.gsr_status.setStyleSheet(f"color: {theme.OK if not note else theme.WARN};")
        else:
            self.gsr_status.setText(info.error)
            self.gsr_status.setStyleSheet(f"color: {theme.WARN};")
        self._capture_options = captures
        self._audio_devices = devices
        self._show_capture()
        self._clip_settings_changed()

    # --- Capture --------------------------------------------------------------------

    def _show_capture(self) -> None:
        """Draw the monitors, mark the one that will be recorded, and say which."""
        arranged = monitors.arrange(self._capture_options, screens.desktop_screens())
        self.monitor_map.set_monitors(arranged)
        recorded = monitors.target(self._capture, arranged)
        self.monitor_map.set_current(recorded)
        chosen = next((m for m in arranged if m.name == recorded), None)
        size = monitor_map.resolution(chosen) if chosen else ""
        warn = False
        if chosen is None:
            text, tip, warn = "No monitors found", "", True
        elif recorded == self._capture:
            text, tip = " · ".join(part for part in (recorded, size) if part), ""
        elif not monitors.names_monitor(self._capture):
            text = f"{recorded} · primary monitor" if chosen.primary else recorded
            tip = "No monitor picked yet, so Vertex records this one."
        else:
            text, warn = f"{self._capture} isn't connected · recording {recorded}", True
            tip = (f"{self._capture} isn't connected, so Vertex records {recorded} until it "
                   f"is back. Click a monitor to record that one instead.")
        self.capture_note.setText(text)
        self.capture_note.setToolTip(tip)
        self.capture_note.setStyleSheet(f"color: {theme.WARN};" if warn else "")

    def _as_recorded(self, rec):
        """The settings as GSR will get them, for the monitor that is recorded."""
        return presets.resolve(rec, self.monitor_map.monitors)

    def _pick_monitor(self, name: str) -> None:
        self._capture = name
        self._show_capture()
        self._clip_settings_changed()

    def _watch_screen(self, screen, initial: bool = False) -> None:
        screen.geometryChanged.connect(self._screens_changed)
        if not initial:
            self._screens_changed()

    def _screens_changed(self, *_args) -> None:
        # Qt may still list a screen while announcing its removal; look once it's gone.
        QTimer.singleShot(0, self._rearrange)

    def _rearrange(self) -> None:
        self._show_capture()
        self._clip_settings_changed()
        if self.stack.currentWidget() is self.pages.get("recording"):
            self._refresh_recorder()     # GSR's list changes with the monitors

    # --- Clip settings ---------------------------------------------------------------

    def _clip_settings_changed(self, *_args) -> None:
        self._show_clip_choices(self.collect().recorder)
        self._update_preview()
        self._show_estimate()

    def _pick_quality(self, _index: int) -> None:
        # Picking a level drops a bitrate set by hand in Advanced.
        if self.video_quality.currentData() != "custom":
            self.bitrate.blockSignals(True)
            self.bitrate.setValue(0)
            self.bitrate.blockSignals(False)
        self._clip_settings_changed()

    def _show_clip_choices(self, rec) -> None:
        """Offer the durations, sizes, qualities and frame rates for the monitor
        recorded: sizes up to its own, turned with it, and each quality with the
        bitrate it comes to at the chosen size and frame rate."""
        monitor = presets.recorded_monitor(rec, self.monitor_map.monitors)
        pixels = monitor.pixels if monitor and all(monitor.pixels) else (0, 0)
        _fill(self.duration, [(s, f"{s} seconds") for s in presets.DURATIONS],
              rec.replay_seconds, lambda s: f"{s} seconds")
        _fill(self.fps, [(f, f"{f} fps") for f in presets.FRAME_RATES], rec.fps,
              lambda f: f"{f} fps")

        sizes = []
        for height in presets.HEIGHTS:
            if pixels[0] and height >= min(pixels):
                continue
            width, tall = presets.output_size(f"{height}p", pixels)
            sizes.append((f"{height}p", f"{height}p · {width} × {tall}" if pixels[0]
                          else f"{height}p"))
        sizes.append(("", f"Native · {pixels[0]} × {pixels[1]}" if pixels[0] else "Native"))
        _fill(self.resolution, sizes, rec.resolution, lambda r: r.replace("x", " × "))

        constant = rec.bitrate_mode == "cbr"
        size = presets.output_size(rec.resolution, pixels)
        levels = []
        for level in presets.LEVELS:
            name = QUALITY_NAMES[level]
            if constant:
                name += f" · {mbps(presets.video_kbps(level, size, rec.fps))}"
            levels.append((level, name))
        current = rec.quality
        if constant and rec.bitrate_kbps:
            levels.append(("custom", f"Custom · {mbps(rec.bitrate_kbps)}"))
            current = "custom"
        _fill(self.video_quality, levels, current, lambda q: q.replace("_", " ").capitalize())
        self._show_audio_choices(rec)

    def _show_audio_choices(self, rec) -> None:
        """Each track's devices: none, the default, Sonar's channels (always:
        Sonar may just be off), then the real devices GSR can record. One
        missing now says what records in its place."""
        known = {name for name, _d in self._audio_devices}
        outputs, inputs = [], []
        for name, description in self._audio_devices:
            if name.startswith("default_") or name.startswith(channels.NODE_PREFIX):
                continue
            if name.endswith(".monitor"):
                outputs.append((f"device:{name}", description.removeprefix("Monitor of ")))
            else:
                inputs.append((f"device:{name}", description))

        def options(role, default_text, own, real):
            fallback = gsr.fallback_source(role)
            instead = "default output" if fallback == "default_output" else "default microphone"
            items = [("", "None"), (fallback, default_text)]
            for channel in own:
                text = channel.description
                if known and channel.record_source not in known:
                    text += f" (Sonar off: {instead})"
                items.append((f"device:{channel.record_source}", text))
            return items + real, (lambda value: f"{value.removeprefix('device:')} "
                                                f"(not available: {instead})")

        for widget, setting, role, default_text, own, real in (
                (self.game_audio, "game_audio", channels.GAME.id, "Default output",
                 channels.OUTPUTS, outputs),
                (self.chat_audio, "chat_audio", channels.CHAT.id, "Default output",
                 channels.OUTPUTS, outputs),
                (self.mic_audio, "mic_audio", channels.MIC.id, "Default microphone",
                 (channels.MIC,), inputs)):
            items, describe = options(role, default_text, own, real)
            _fill(widget, items, getattr(rec, setting), describe)

    def _show_estimate(self) -> None:
        config = self.collect()
        rec = config.recorder
        tracks = len(gsr.audio_tracks(config))
        size = presets.clip_bytes(self._as_recorded(rec), tracks)
        largest = presets.clip_bytes(self._as_recorded(dataclasses.replace(
            rec, quality=presets.LEVELS[-1], resolution="", fps=max(presets.FRAME_RATES),
            replay_seconds=max(presets.DURATIONS), bitrate_kbps=0)), tracks)
        constant = rec.bitrate_mode == "cbr"
        self.clip_size.setText(f"{'About' if constant else 'Roughly'} "
                               f"{fmt.size(size, 0)} per clip")
        self.clip_meter.set_fraction(size / largest if largest else 0)
        where = "in memory" if rec.replay_storage == "ram" else "on disk"
        detail = f"The replay buffer holds about {fmt.size(size, 0)} {where} while it runs."
        if not constant:
            detail = f"It depends on what is on screen. {detail}"
        self.clip_detail.setText(detail)
        if self._storage is None:
            self.disk_room.setText("Measuring…")
        else:
            room = self._storage.disk_free // size if size else 0
            self.disk_room.setText(f"Room for about {room:,} more clips")

    def _refresh_storage(self) -> None:
        folder = self.collect().resolved_recording_dir()
        workers.run(lambda: storage.storage_stats(folder), self._got_storage,
                    lambda _exc: None)

    def _got_storage(self, stats) -> None:
        self._storage = stats
        self.disk_gauge.set_stats(stats)
        self._show_estimate()

    def _show_clips_folder(self, folder: str) -> None:
        self.output_dir.edit.setPlaceholderText(paths.tilde(folder) if folder
                                                else "The clips folder")

    def _update_preview(self) -> None:
        try:
            config = self.collect()
            # What will record, with stand-ins for devices that are missing now.
            tracks, _stood_in = gsr.available_tracks(
                gsr.audio_tracks(config), [name for name, _d in self._audio_devices])
            argv = gsr.build_argv(self._as_recorded(config.recorder), tracks,
                                  config.resolved_recording_dir(), self.context.recorder.info)
            self.preview.setPlainText(shlex.join(argv))
        except ValueError as exc:
            self.preview.setPlainText(f"(not valid yet: {exc})")

    # --- Actions -----------------------------------------------------------------

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


def _fill(widget: QComboBox, items, current, describe) -> None:
    """Fill a drop-down and keep `current` chosen. A value it doesn't offer,
    from older settings, stays chosen too, written out by `describe`."""
    widget.blockSignals(True)
    widget.clear()
    for value, text in items:
        widget.addItem(text, value)
    if widget.findData(current) < 0:
        widget.addItem(describe(current), current)
    widget.setCurrentIndex(widget.findData(current))
    widget.blockSignals(False)


def _set_combo(widget: QComboBox, value: str) -> None:
    index = widget.findData(value)
    if index < 0:
        widget.addItem(LABELS.get(value, value), value)
        index = widget.count() - 1
    widget.setCurrentIndex(index)

