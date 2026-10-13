"""First-run setup: folders, Sonar, the replay buffer, and an optional import."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vertex import paths
from vertex.config import Config, default_config
from vertex.recorder import gsr, presets
from vertex.ui import theme, workers
from vertex.ui.widgets import PathField, Section, Toggle, button, label

FOLDER_NAMES = {"clip_path": "Clips folder", "data_path": "Library folder"}


class FirstRunView(QWidget):
    finished = Signal(object, bool, bool)   # config, enable sonar, start recorder

    def __init__(self, context, config: Config | None = None, missing=(), parent=None):
        super().__init__(parent)
        self.context = context
        self.config = config or default_config()
        if config is not None:
            # Re-pointing an existing install: keep its settings, fill blanks.
            defaults = default_config()
            for key in ("clip_path", "export_path", "data_path", "state_path", "cache_path"):
                if not getattr(self.config, key):
                    setattr(self.config, key, getattr(defaults, key))

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        column = QVBoxLayout()
        column.setContentsMargins(0, 40, 0, 30)
        column.setSpacing(16)
        outer.addLayout(column, 4)
        outer.addStretch(1)

        mark = QLabel()
        pixmap = QPixmap(str(paths.mark_path(self.config.logo_variant)))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            scaled = pixmap.scaledToHeight(int(72 * ratio),
                                           Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            mark.setPixmap(scaled)
        column.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
        self.heading = label("Welcome to Vertex", "Heading")
        self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.heading)
        self.step_label = label("", "Muted")
        self.step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.step_label)

        self.stack = QStackedWidget()
        column.addWidget(self.stack, 1)
        self.steps = [self._folders(missing), self._sonar(), self._recording(), self._done()]
        for step in self.steps:
            # Top-aligned: a section stretched to the page height spreads its
            # few rows across it.
            page = QWidget()
            holder = QVBoxLayout(page)
            holder.setContentsMargins(0, 0, 0, 0)
            holder.addWidget(step)
            holder.addStretch(1)
            self.stack.addWidget(page)

        actions = QHBoxLayout()
        self.back_button = button("Back", "ghost", on_click=lambda: self._go(-1))
        self.next_button = button("Continue", "primary", on_click=lambda: self._go(1))
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        actions.addWidget(self.next_button)
        column.addLayout(actions)
        self._show(0)

    # --- Steps -------------------------------------------------------------------

    def _folders(self, missing) -> QWidget:
        section = Section("Where your clips live",
                          "Vertex records into this folder and lists every clip in it. "
                          "Your recordings are never modified; edits are kept in a library "
                          "file of their own.")
        if missing:
            named = "\n".join(f"{FOLDER_NAMES.get(key, key)}: {path}" for key, path in missing)
            warning = label(f"Some folders in your settings are missing — renamed, moved, or "
                            f"on a drive that isn't mounted. Nothing has been deleted.\n\n"
                            f"{named}", wrap=True)
            warning.setStyleSheet(f"color: {theme.WARN};")
            section.add(warning)
        self.clip_path = PathField(self.config.clip_path)
        self.export_path = PathField(self.config.export_path)
        section.add_row("Clips", self.clip_path)
        section.add_row("Exports", self.export_path, "Created when setup finishes")
        self.clip_path.setMinimumWidth(380)
        self.export_path.setMinimumWidth(380)
        return section

    def _sonar(self) -> QWidget:
        section = Section("Sonar", "Vertex can create virtual audio devices — Game, Chat "
                                   "and Media outputs plus a shared Vertex Mic — and "
                                   "record each one as its own track. Every clip then has "
                                   "the same tracks, so you can turn your mic down without "
                                   "touching the game.")
        self.sonar_enabled = Toggle(True)
        section.add_row("Create the virtual devices", self.sonar_enabled,
                        "You can turn this off any time on the Sonar page.")
        self.output = QComboBox()
        self.mic = QComboBox()
        for combo in (self.output, self.mic):
            combo.addItem("System default", "")
            combo.setMinimumWidth(300)
        section.add_row("Play channels through", self.output)
        section.add_row("Microphone", self.mic)
        self.sonar_enabled.toggled.connect(self.output.setEnabled)
        self.sonar_enabled.toggled.connect(self.mic.setEnabled)
        sonar = self.context.sonar.sonar
        workers.run(lambda: (sonar.outputs(), sonar.inputs()), self._got_devices,
                    lambda exc: self._no_audio(str(exc)))
        self.sonar_note = label("", "Dim", wrap=True)
        section.add(self.sonar_note)
        return section

    def _got_devices(self, pair) -> None:
        outputs, inputs = pair
        for combo, devices in ((self.output, outputs), (self.mic, inputs)):
            for device in devices:
                combo.addItem(device.label, device.name)

    def _no_audio(self, error: str) -> None:
        self.sonar_enabled.setChecked(False)
        self.sonar_enabled.setEnabled(False)
        self.sonar_note.setText(f"No PipeWire or PulseAudio server answered ({error}), so "
                                f"Sonar is unavailable for now.")

    def _recording(self) -> QWidget:
        section = Section("The replay buffer",
                          "GPU Screen Recorder keeps the last moments of your screen in "
                          "memory; saving writes them to a clip.")
        self.gsr_status = label("Looking for GPU Screen Recorder…", "Muted", wrap=True)
        section.add(self.gsr_status)
        self.replay_seconds = QComboBox()
        for seconds in presets.DURATIONS:
            self.replay_seconds.addItem(f"{seconds} seconds", seconds)
        current = self.config.recorder.replay_seconds
        if self.replay_seconds.findData(current) < 0:
            self.replay_seconds.addItem(f"{current} seconds", current)
        self.replay_seconds.setCurrentIndex(self.replay_seconds.findData(current))
        section.add_row("Duration", self.replay_seconds)
        self.rec_autostart = Toggle(False)
        section.add_row("Start the buffer whenever Vertex starts", self.rec_autostart)
        section.add(label("To save a clip from inside a game, bind the command "
                          "`vertex save-clip` to a key in your desktop's keyboard settings. "
                          "The tray menu has a Save Clip entry too.", "Dim", wrap=True))
        command = self.config.recorder.command
        workers.run(lambda: gsr.detect(command), self._got_gsr)
        return section

    def _got_gsr(self, info) -> None:
        if info.available and not info.too_old:
            self.gsr_status.setText(f"Found GPU Screen Recorder {info.version_text}.")
            self.gsr_status.setStyleSheet(f"color: {theme.OK};")
            self.rec_autostart.setChecked(True)
        else:
            self.gsr_status.setText(f"{info.error} Clips you already have still work; set "
                                    f"the recorder up later in Settings → Recording.")
            self.gsr_status.setStyleSheet(f"color: {theme.WARN};")

    def _done(self) -> QWidget:
        section = Section("Bring your clips along",
                          "Already have a library — from SteelSeries Moments, say? Copy it "
                          "into the clips folder from Settings → Import once Vertex is open. "
                          "Clips already in the clips folder are picked up by themselves, "
                          "and games are read from Moments-style file names.")
        return section

    # --- Navigation ---------------------------------------------------------------

    def _show(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        titles = ("Welcome to Vertex", "Your audio", "Your recordings", "All set")
        self.heading.setText(titles[index])
        self.step_label.setText(f"Step {index + 1} of {len(self.steps)}")
        self.back_button.setVisible(index > 0)
        self.next_button.setText("Open Vertex" if index == len(self.steps) - 1 else "Continue")

    def _go(self, delta: int) -> None:
        index = self.stack.currentIndex()
        if delta > 0 and index == 0 and not self.clip_path.value():
            self.clip_path.edit.setFocus()
            return
        if delta > 0 and index == len(self.steps) - 1:
            self._finish()
            return
        self._show(max(0, min(len(self.steps) - 1, index + delta)))

    def _finish(self) -> None:
        config = self.config
        config.clip_path = self.clip_path.value()
        config.export_path = self.export_path.value() or default_config().export_path
        defaults = default_config()
        for key in ("data_path", "state_path", "cache_path"):
            if not getattr(config, key):
                setattr(config, key, getattr(defaults, key))
        config.recorder.replay_seconds = self.replay_seconds.currentData()
        config.recorder.autostart = self.rec_autostart.isChecked()
        enable_sonar = self.sonar_enabled.isChecked()
        config.sonar.output_device = self.output.currentData() or ""
        config.sonar.mic_device = self.mic.currentData() or ""
        self.finished.emit(config, enable_sonar, self.rec_autostart.isChecked())
