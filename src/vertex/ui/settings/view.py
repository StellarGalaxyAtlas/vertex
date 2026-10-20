"""Settings: folders and app behaviour, recording, notifications, shortcuts, import
and setup, reset."""

from __future__ import annotations

import copy
import os

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase
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

from vertex import desktop, logs, paths
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
    default_config,
)
from vertex.core import storage
from vertex.media import roles
from vertex.recorder import backend, gsr, obs
from vertex.ui import theme, workers
from vertex.ui.dialogs.importing import CopyClipsDialog, TagImportDialog
from vertex.ui.settings.clip_choices import ClipChoices, ClipSize, fill
from vertex.ui.settings.notifications import NotificationsPage
from vertex.ui.settings.reset import ResetPage
from vertex.ui.settings.schemes import SchemePicker
from vertex.ui.settings.shortcuts import ShortcutsPage
from vertex.ui.widgets import (
    Banner,
    Columns,
    Disclosure,
    FieldGrid,
    PathField,
    Section,
    SideNav,
    StorageGauge,
    Toggle,
    button,
    label,
    setting_row,
)

# What applies as soon as it changes. The rest of the recorder's settings
# restart the replay buffer, so they wait for Apply.
APPLY_AT_ONCE = ("clip_path", "export_path", "data_path", "state_path", "cache_path",
                 "keep_logs", "log_path", "close_to_tray", "colour_scheme", "notifications",
                 "notify_over_games")
RECORDER_AT_ONCE = ("autostart",)

LABELS = {
    "very_high": "Very high", "qp": "Constant quality (QP)", "vbr": "Variable bitrate",
    "cbr": "Constant bitrate", "vfr": "Variable", "cfr": "Constant",
    "content": "Match content", "ram": "Memory", "disk": "Disk", "gpu": "GPU", "cpu": "CPU",
    "auto": "Automatic", "aac": "AAC", "opus": "Opus", "mp4": "MP4", "mkv": "MKV",
    "hevc": "HEVC", "av1": "AV1", "h264": "H.264", "vp8": "VP8", "vp9": "VP9",
    "hevc_10bit": "HEVC 10-bit", "av1_10bit": "AV1 10-bit", "hevc_hdr": "HEVC HDR",
    "av1_hdr": "AV1 HDR", "limited": "Limited", "full": "Full",
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
    """A page of sections, one under the other. A tuple of sections goes side
    by side once the page is wide enough."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 12, 24)
    layout.setSpacing(16)
    for section in sections:
        layout.addWidget(Columns(*section) if isinstance(section, tuple) else section)
    layout.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidget(page)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    return scroll


class SettingsView(QWidget):
    saved = Signal(bool)             # folders changed
    imported = Signal()
    setup_requested = Signal()       # run first-run setup again
    reset_requested = Signal(str)    # settings | library | cache, confirmed
    test_requested = Signal()        # a sample notification over games

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        outer = QHBoxLayout(self)
        outer.setContentsMargins(theme.CONTENT_MARGIN, 18, theme.CONTENT_MARGIN - 12, 12)
        outer.setSpacing(28)
        # The pages, in a column on the left.
        nav = QVBoxLayout()
        nav.setSpacing(14)
        title = label("Settings", "Heading")
        title.setContentsMargins(14, 0, 0, 0)
        nav.addWidget(title)
        self.tabs = SideNav([("general", "General", "settings"),
                             ("recording", "Recording", "record"),
                             ("notifications", "Notifications", "bell"),
                             ("shortcuts", "Shortcuts", "keyboard"),
                             ("import", "Import and setup", "folder"),
                             ("reset", "Reset and delete", "trash")], "general")
        self.tabs.setFixedWidth(240)
        self.tabs.changed.connect(lambda key, _d: self.show_page(key))
        nav.addWidget(self.tabs, 1)
        outer.addLayout(nav)
        layout = QVBoxLayout()
        layout.setSpacing(14)
        outer.addLayout(layout, 1)
        header = QHBoxLayout()
        header.addStretch(1)
        # Only for recording changes, which restart the replay buffer; the
        # rest applies as it changes.
        self.pending = label("Recording changes restart the replay buffer", "Muted")
        self.revert_button = button("Revert", "ghost", on_click=self.load)
        self.apply_button = button("Apply", "primary", on_click=self.apply_recording)
        header.addWidget(self.pending)
        header.addSpacing(6)
        header.addWidget(self.revert_button)
        header.addWidget(self.apply_button)
        header.setContentsMargins(0, 0, 12, 0)
        layout.addLayout(header)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.banner = Banner(self)
        self.pages = {}
        self._loading = False
        # The disk the clips go to, once measured.
        self._storage: storage.StorageStats | None = None
        # The audio devices GSR said it can record: (name, description).
        self._audio_devices: list[tuple[str, str]] = []
        self._build_general()
        self._build_recording()
        self.notifications = NotificationsPage(self.test_requested.emit)
        first, *kinds = self.notifications.sections
        self.pages["notifications"] = scroll_page(first, *_pairs(kinds))
        self.stack.addWidget(self.pages["notifications"])
        top, *groups = ShortcutsPage().sections
        self.pages["shortcuts"] = scroll_page(top, *_pairs(groups))
        self.stack.addWidget(self.pages["shortcuts"])
        self._build_import()
        resets = ResetPage(self)
        resets.reset_requested.connect(self.reset_requested)
        self.pages["reset"] = scroll_page(tuple(resets.sections))
        self.stack.addWidget(self.pages["reset"])
        self._apply_on_change()
        self.load()

    def _apply_on_change(self) -> None:
        for field in (self.clip_path, self.export_path, self.data_path, self.state_path,
                      self.cache_path, self.log_path):
            field.committed.connect(lambda _v: self.apply_now())
        for switch in (self.keep_logs, self.close_to_tray, self.autostart,
                       self.notifications.over_games, *self.notifications.switches.values(),
                       self.rec_autostart):
            switch.toggled.connect(lambda _on: self.apply_now())
        self.schemes.picked.connect(lambda _s: self.apply_now())
        self.output_dir.changed.connect(lambda _v: self._show_pending())

    def show_page(self, key: str) -> None:
        self.tabs.set_current(key)
        self.stack.setCurrentWidget(self.pages[key])
        if key == "recording":
            self._refresh_recorder()
            self._refresh_storage()

    # --- Pages ----------------------------------------------------------------

    def _build_general(self) -> None:
        appearance = Section("Appearance")
        self.schemes = SchemePicker()
        self.schemes.picked.connect(theme.use)
        appearance.add(self.schemes)

        folders = Section("Folders")
        # The defaults for this account and system: Videos is wherever, and
        # whatever, Windows or the desktop calls it.
        defaults = default_config()
        self.clip_path = PathField(placeholder=paths.tilde(defaults.clip_path))
        self.export_path = PathField(placeholder=paths.tilde(defaults.export_path))
        folders.add_row("Clips", self.clip_path)
        folders.add_row("Exports", self.export_path)
        self.data_path = PathField(placeholder=str(paths.default_data_dir()))
        self.state_path = PathField(placeholder=str(paths.default_state_dir()))
        self.cache_path = PathField(placeholder=str(paths.default_cache_dir()))
        self.keep_logs = Toggle()
        self.log_path = PathField(placeholder=str(paths.default_log_dir()))
        self.keep_logs.toggled.connect(self.log_path.setEnabled)
        # Vertex's own folders: set up once, and best left alone.
        self.folders_advanced = Disclosure("Advanced", "Library, state, cache and log folders")
        self.folders_advanced.body_layout.setSpacing(12)
        for title, field, hint in (
                ("Library", self.data_path, "Tags, titles, trims and mixes"),
                ("State", self.state_path, ""),
                ("Cache", self.cache_path, "Thumbnails")):
            self.folders_advanced.add(setting_row(title, field, hint))
        self.folders_advanced.add(setting_row(
            "Keep logs", self.keep_logs, "What Vertex did, for when something goes wrong"))
        self.folders_advanced.add(setting_row("Logs", self.log_path, ""))
        folders.add(self.folders_advanced)
        for field in (self.clip_path, self.export_path, self.data_path, self.state_path,
                      self.cache_path, self.log_path):
            field.setMinimumWidth(420)

        behaviour = Section("Behavior")
        self.close_to_tray = Toggle()
        behaviour.add_row("Close to tray", self.close_to_tray,
                          "The replay buffer keeps running")
        self.autostart = Toggle()
        behaviour.add_row("Start with your computer", self.autostart,
                          "Starts minimized to the tray")
        self.pages["general"] = scroll_page(appearance, (folders, behaviour))
        self.stack.addWidget(self.pages["general"])

    def _build_recording(self) -> None:
        status = Section(backend.name())
        self.gsr_status = label("", "Muted", wrap=True)
        status.add(self.gsr_status)
        # Shown while the recorder is missing, too old or doesn't start.
        self.gsr_help = QWidget()
        help_row = QHBoxLayout(self.gsr_help)
        help_row.setContentsMargins(0, 0, 0, 0)
        help_row.setSpacing(10)
        self.install_button = button("How to install it", "primary",
                                     on_click=lambda: QDesktopServices.openUrl(
                                         QUrl(backend.install_url())))
        self.command_button = button("Set where OBS is" if backend.is_obs()
                                     else "Set the command", on_click=self._go_to_command)
        recheck = button("Check again", on_click=self._refresh_recorder)
        for widget in (self.install_button, self.command_button, recheck):
            help_row.addWidget(widget)
        help_row.addStretch(1)
        self.gsr_help.hide()
        status.add(self.gsr_help)
        self.rec_autostart = Toggle()
        status.add_row("Start replay buffer with Vertex", self.rec_autostart)

        clips = Section("Recording")
        # The monitor and the drop-downs under it, shared with first-run setup.
        self.choices = ClipChoices(self)
        self.choices.add_to(clips)
        self.capture_note, self.monitor_map = self.choices.capture_note, self.choices.monitor_map
        self.duration, self.video_quality = self.choices.duration, self.choices.video_quality
        self.resolution, self.fps = self.choices.resolution, self.choices.fps
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
        clips.add(label("Each is saved as a separate audio track", "Dim", wrap=True))
        clips.add(self._build_estimate())

        # OBS takes fewer of these than GSR: its rows for the rest are hidden.
        gsr_only = []
        self.recording_advanced = advanced = Disclosure(
            "Advanced", "Codecs, audio and more" if backend.is_obs()
            else "Bitrate, codecs, audio and more")
        video = Section("Video")
        self.bitrate_mode = combo(BITRATE_MODES, "cbr")
        gsr_only.append(video.add_row("Bitrate mode", self.bitrate_mode))
        self.bitrate = QSpinBox()
        self.bitrate.setRange(0, 500000)
        self.bitrate.setSingleStep(1000)
        self.bitrate.setSuffix(" kbps")
        self.bitrate.setSpecialValueText("From video quality")
        gsr_only.append(video.add_row("Bitrate", self.bitrate, "Constant bitrate only"))
        self.video_codec = combo(obs.CODECS if backend.is_obs() else VIDEO_CODECS, "auto")
        video.add_row("Codec", self.video_codec, "H.264 is the most compatible")
        self.framerate_mode = combo(FRAMERATE_MODES, "vfr")
        gsr_only.append(video.add_row("Frame rate mode", self.framerate_mode))
        self.container = combo(CONTAINERS, "mp4")
        video.add_row("Container", self.container)
        self.color_range = combo(COLOR_RANGES, "limited")
        gsr_only.append(video.add_row("Color range", self.color_range))
        self.encoder = combo(ENCODERS, "gpu")
        video.add_row("Encoder", self.encoder)
        self.keyint = QDoubleSpinBox()
        self.keyint.setRange(0.5, 10)
        self.keyint.setSingleStep(0.5)
        self.keyint.setSuffix(" s")
        gsr_only.append(video.add_row("Keyframe interval", self.keyint,
                                      "Shorter means more precise trims"))

        replay = Section("Replay buffer")
        self.replay_storage = combo(REPLAY_STORAGES, "ram")
        gsr_only.append(replay.add_row("Buffer location", self.replay_storage,
                                       "Disk uses less memory"))
        self.output_dir = PathField(placeholder="The clips folder")
        self.output_dir.setMinimumWidth(380)
        replay.add_row("Save clips to", self.output_dir, "Leave blank for the clips folder")
        self.clip_path.changed.connect(self._show_clips_folder)

        audio = Section("Audio")
        self.audio_codec = combo(AUDIO_CODECS, "aac")
        audio.add_row("Codec", self.audio_codec)
        self.audio_bitrate = QSpinBox()
        self.audio_bitrate.setRange(0, 512)
        self.audio_bitrate.setSpecialValueText("Automatic")
        self.audio_bitrate.setSuffix(" kbps")
        audio.add_row("Bitrate", self.audio_bitrate)

        recorder = Section("Recorder")
        self.command = QLineEdit()
        self.command.setMinimumWidth(380)
        if backend.is_obs():
            self.command.setPlaceholderText("Where OBS is installed")
            recorder.add_row("OBS", self.command, "obs64.exe, if OBS is somewhere else")
        else:
            self.command.setPlaceholderText("gpu-screen-recorder")
            recorder.add_row("Command", self.command, "For the Flatpak: flatpak run "
                             "--command=gpu-screen-recorder com.dec05eba.gpu_screen_recorder")
        self.extra_args = QLineEdit()
        self.extra_args.setPlaceholderText("-tune quality -low-power yes")
        self.extra_args.setMinimumWidth(380)
        gsr_only.append(recorder.add_row("Extra arguments", self.extra_args))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.preview.setFixedHeight(120 if backend.is_obs() else 96)
        recorder.add(label("What Vertex sets up in OBS" if backend.is_obs()
                           else "Command preview", "Dim"))
        recorder.add(self.preview)
        for row in gsr_only:
            row.setVisible(not backend.is_obs())
        advanced.add(Columns(video, replay))
        advanced.add(Columns(audio, recorder))

        # The clip settings change what each other offers (sizes up to the
        # monitor's, bitrates for the size and frame rate) and the estimate.
        self.choices.changed.connect(self._clip_settings_changed)
        self.choices.quality_picked.connect(self._pick_quality)
        self.choices.monitors_changed.connect(self._monitors_changed)
        for widget in (self.bitrate_mode, self.replay_storage, self.audio_codec):
            widget.currentIndexChanged.connect(self._clip_settings_changed)
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

        self.pages["recording"] = scroll_page(status, clips, advanced)
        self.stack.addWidget(self.pages["recording"])

    def _build_estimate(self) -> QWidget:
        """How big a clip gets with these settings, and how many fit on the disk."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(24)
        # The clip size is shared with first-run setup.
        self.clip_estimate = ClipSize()
        self.clip_size = self.clip_estimate.figure
        row.addWidget(self.clip_estimate, 1)
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(label("DISK SPACE", "Group"))
        self.disk_room = label()
        self.disk_room.setStyleSheet("font-size: 13pt; font-weight: 600;")
        right.addWidget(self.disk_room)
        self.disk_gauge = StorageGauge()
        right.addWidget(self.disk_gauge)
        right.addStretch(1)
        divider = QFrame()
        divider.setFixedWidth(1)
        theme.style(divider, lambda: f"background: {theme.LINE};")
        row.addWidget(divider)
        row.addLayout(right, 1)
        return box

    def _build_import(self) -> None:
        copy_section = Section("Import clips", "From SteelSeries Moments or another folder")
        copy_section.add(button("Import clips…", on_click=self._copy_clips))
        tag_section = Section("Tag games from file names",
                              "Reads the game from Moments-style file names")
        tag_section.add(button("Review tags…", on_click=self._tag_clips))
        setup = Section("Run setup again", "Starts with your current settings")
        setup.add(button("Run setup again…", on_click=self.setup_requested.emit))
        self.pages["import"] = scroll_page((copy_section, tag_section, setup))
        self.stack.addWidget(self.pages["import"])

    # --- Load / collect / save -------------------------------------------------

    def load(self) -> None:
        self._loading = True
        try:
            self._load()
        finally:
            self._loading = False
        self._show_pending()

    def _load(self) -> None:
        config = self.context.config
        self.clip_path.set_value(config.clip_path)
        self.export_path.set_value(config.export_path)
        self.data_path.set_value(config.data_path)
        self.state_path.set_value(config.state_path)
        self.cache_path.set_value(config.cache_path)
        self.keep_logs.setChecked(config.keep_logs)
        self.log_path.setEnabled(config.keep_logs)
        self.log_path.set_value(config.log_path)
        self.log_path.edit.setPlaceholderText(paths.tilde(
            os.path.join(config.resolved_state_dir(), "logs")))
        self.close_to_tray.setChecked(config.close_to_tray)
        self.schemes.set_value(config.colour_scheme)
        if self.schemes.value() != theme.scheme:      # back from a scheme picked, not saved
            theme.use(self.schemes.value())
        self.autostart.setChecked(desktop.autostart_enabled())
        self.notifications.load(config.notifications, config.notify_over_games)

        rec = config.recorder
        self.command.setText(rec.command)
        self.rec_autostart.setChecked(rec.autostart)
        self.choices.capture = rec.capture
        self.choices.show_capture()
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
        config.keep_logs = self.keep_logs.isChecked()
        config.log_path = self.log_path.value()
        config.close_to_tray = self.close_to_tray.isChecked()
        config.colour_scheme = self.schemes.value()
        config.notifications = self.notifications.choices()
        config.notify_over_games = self.notifications.over_games_choice()
        rec = config.recorder
        rec.command = self.command.text().strip() or backend.default_command()
        rec.autostart = self.rec_autostart.isChecked()
        self.choices.apply(rec)
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

    def pending_recording(self) -> bool:
        """Recording changes waiting for Apply."""
        new, old = self.collect().recorder, self.context.config.recorder
        for key in RECORDER_AT_ONCE:
            setattr(new, key, getattr(old, key))
        return new != old

    def _show_pending(self) -> None:
        pending = not self._loading and self.pending_recording()
        for widget in (self.pending, self.revert_button, self.apply_button):
            widget.setVisible(pending)

    def save(self) -> bool:
        """Apply everything: what applies at once, then the recording changes."""
        return self.apply_now() and self.apply_recording()

    def apply_now(self) -> bool:
        """Apply and save what doesn't wait for Apply: folders, switches, the
        scheme, notifications."""
        if self._loading:
            return True
        new, old = self.collect(), self.context.config
        autostart = self.autostart.isChecked()
        applied = copy.deepcopy(old)
        for key in APPLY_AT_ONCE:
            setattr(applied, key, getattr(new, key))
        for key in RECORDER_AT_ONCE:
            setattr(applied.recorder, key, getattr(new.recorder, key))
        if applied.to_dict() == old.to_dict() and autostart == desktop.autostart_enabled():
            return True
        if not applied.is_complete():
            self.banner.show_message("Set the clips, exports, library, state and cache "
                                     "folders (blank uses the defaults).", "error", 10000)
            self.folders_advanced.set_expanded(True)
            return False
        folders_changed = any(getattr(applied, key) != getattr(old, key) for key in
                              ("clip_path", "data_path", "cache_path", "state_path"))
        _log_changes(old, applied)
        for key in APPLY_AT_ONCE:
            setattr(old, key, getattr(applied, key))
        for key in RECORDER_AT_ONCE:
            setattr(old.recorder, key, getattr(applied.recorder, key))
        old.ensure_dirs()
        self.context.save_config()
        if autostart != desktop.autostart_enabled():
            logs.APP.info("Start with your computer: %s", "on" if autostart else "off")
            desktop.set_autostart(autostart)
        if old.keep_logs and logs.folder() != os.path.abspath(old.resolved_log_dir()):
            self.banner.show_message(f"Logs can't be written to "
                                     f"{paths.tilde(old.resolved_log_dir())}.", "warn", 10000)
        if folders_changed:
            self._refresh_storage()
        self.saved.emit(folders_changed)
        self._show_pending()
        return True

    def apply_recording(self) -> bool:
        """Apply the recording changes, restarting a running replay buffer."""
        if not self.pending_recording():
            return True
        new = self.collect()
        problems = backend.validate(self._as_recorded(new.recorder))
        if problems:
            self.banner.show_message("Recording: " + problems[0], "error", 10000)
            self.show_page("recording")
            return False
        old = self.context.config
        for key in RECORDER_AT_ONCE:
            setattr(new.recorder, key, getattr(old.recorder, key))
        applied = copy.deepcopy(old)
        applied.recorder = new.recorder
        _log_changes(old, applied)
        old.recorder = new.recorder
        self.context.save_config()
        restarting = self.context.recorder.running
        self.context.recorder.detect()
        self.context.recorder.restart_if_running()
        self.banner.show_message("Applied. Replay buffer restarting." if restarting
                                 else "Applied.", "ok", 5000)
        self._refresh_storage()
        self._show_pending()
        return True

    # --- Recorder helpers ---------------------------------------------------------

    def _refresh_recorder(self) -> None:
        command = self.command.text().strip() or backend.default_command()

        def probe():
            info = backend.detect(command)
            if not info.available:
                return info, [], []
            return (info, backend.list_capture_options(command),
                    backend.list_audio_devices(command))

        workers.run(probe, self._show_recorder, lambda _exc: None)

    def _show_recorder(self, result) -> None:
        info, captures, devices = result
        working = info.available and not info.too_old
        if working:
            note = "" if info.supports_track_names or backend.is_obs() else \
                " — update to 5.15+ so clip tracks are named Game, Chat and Microphone"
            self.gsr_status.setText(f"Found {backend.name()} {info.version_text}{note}.")
            theme.style(self.gsr_status, lambda: f"color: {theme.OK if not note else theme.WARN};")
        else:
            # Its own wording here: the recorder's says "set its command in
            # Settings", and this is Settings.
            if info.too_old:
                minimum = ".".join(map(str, backend.min_version()))
                text = (f"{backend.name()} {info.version_text} is too old: Vertex needs "
                        f"{minimum} or newer.")
            elif info.missing and backend.is_obs():
                text = (f"{backend.name()} is not installed. Install it, or set where it is "
                        f"if it's somewhere else.")
            elif info.missing:
                text = ("GPU Screen Recorder is not installed. Install it, or set the "
                        "command that runs it if it's a Flatpak.")
            else:
                text = info.error
            self.gsr_status.setText(text)
            theme.style(self.gsr_status, lambda: f"color: {theme.WARN};")
            self.install_button.setText("How to update it" if info.too_old
                                        else "How to install it")
        self.gsr_help.setVisible(not working)
        self._audio_devices = devices
        self.choices.set_capture_options(captures)
        self._clip_settings_changed()

    def _go_to_command(self) -> None:
        """Open Advanced and put the cursor in the recorder's command."""
        self.recording_advanced.set_expanded(True)
        page = self.pages["recording"]
        page.widget().layout().activate()
        page.ensureWidgetVisible(self.command, 0, 120)
        self.command.setFocus()
        self.command.selectAll()

    # --- Capture --------------------------------------------------------------------

    def _as_recorded(self, rec):
        """The settings as the recorder will get them, for the monitor that is recorded."""
        return self.choices.recorded(rec)

    def _monitors_changed(self) -> None:
        self._clip_settings_changed()
        if self.stack.currentWidget() is self.pages.get("recording"):
            self._refresh_recorder()     # the recorder's list changes with the monitors

    # --- Clip settings ---------------------------------------------------------------

    def _clip_settings_changed(self, *_args) -> None:
        self._show_clip_choices(self.collect().recorder)
        self._update_preview()
        self._show_estimate()

    def _pick_quality(self) -> None:
        # Picking a level drops a bitrate set by hand in Advanced.
        if self.video_quality.currentData() != "custom":
            self.bitrate.blockSignals(True)
            self.bitrate.setValue(0)
            self.bitrate.blockSignals(False)
        self._clip_settings_changed()

    def _show_clip_choices(self, rec) -> None:
        self.choices.show(rec)
        self._show_audio_choices(rec)

    def _show_audio_choices(self, rec) -> None:
        """Each track's devices: none, the default, then the real devices the
        recorder can record. One missing now says what records in its place."""
        outputs, inputs = [], []
        for name, description in self._audio_devices:
            if name.startswith("default_"):
                continue
            if backend.is_output(name):
                outputs.append((f"device:{name}", description.removeprefix("Monitor of ")))
            else:
                inputs.append((f"device:{name}", description))

        for widget, setting, role, default_text, real in (
                (self.game_audio, "game_audio", roles.GAME.id, "Default output", outputs),
                (self.chat_audio, "chat_audio", roles.CHAT.id, "Default output", outputs),
                (self.mic_audio, "mic_audio", roles.MIC.id, "Default microphone", inputs)):
            fallback = gsr.fallback_source(role)
            instead = "default output" if fallback == "default_output" else "default microphone"
            fill(widget, [("", "None"), (fallback, default_text), *real], getattr(rec, setting),
                 lambda value, instead=instead: f"{value.removeprefix('device:')} "
                                                f"(not available: {instead})")

    def _show_estimate(self) -> None:
        size = self.clip_estimate.estimate(self.collect(), self._as_recorded)
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
            plan = backend.launch_plan(config, self.choices.monitor_map.monitors, tracks,
                                       self.context.recorder.info)
            self.preview.setPlainText(backend.describe(plan))
        except ValueError as exc:
            self.preview.setPlainText(f"(not valid yet: {exc})")
        self._show_pending()

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


def _pairs(sections: list) -> list:
    """Sections two by two, to sit side by side on a wide page; an odd one out
    gets the width to itself."""
    return [tuple(sections[i:i + 2]) if i + 1 < len(sections) else sections[i]
            for i in range(0, len(sections), 2)]


def _log_changes(old: Config, new: Config) -> None:
    """One line per setting saved with a new value, as the config file names it."""
    before, after = _flat(old.to_dict()), _flat(new.to_dict())
    for key, value in after.items():
        if before.get(key) == value:
            continue
        logs.APP.info("Setting %s: %s → %s", key, _shown(before.get(key)), _shown(value))


def _flat(data: dict, prefix: str = "") -> dict:
    flat = {}
    for key, value in data.items():
        if isinstance(value, dict) and key != "notifications":
            flat.update(_flat(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def _shown(value) -> str:
    return '""' if value == "" else str(value)


def _set_combo(widget: QComboBox, value: str) -> None:
    index = widget.findData(value)
    if index < 0:
        widget.addItem(LABELS.get(value, value), value)
        index = widget.count() - 1
    widget.setCurrentIndex(index)

