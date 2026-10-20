"""First-run setup: the clips folder, Vertex Sonar, Vertex Moments, and the
clips someone already has."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vertex import APP_NAME, fmt, paths
from vertex.config import Config, default_config
from vertex.core import importing
from vertex.library.database import DB_NAME, Library
from vertex.recorder import gsr, notifier
from vertex.ui import icons, theme, workers
from vertex.ui.dialogs.importing import FolderList
from vertex.ui.name_teacher import NameTeacher
from vertex.ui.settings.clip_choices import ClipChoices, ClipSize
from vertex.ui.sonar_view import DeviceField
from vertex.ui.widgets import (
    ChoiceCard,
    PathField,
    Section,
    Toggle,
    button,
    hline,
    label,
)

FOLDER_NAMES = {"clip_path": "Clips folder", "data_path": "Library folder"}

# What each step is called, and the sentence under its name.
STEPS = {
    "folders": ("Welcome to Vertex",
                "A few quick choices and you're ready to go. You can change any of them "
                "later in Settings."),
    "sonar": ("Vertex Sonar",
              "Separate volumes for game, chat and media, plus a shared Vertex Mic."),
    "moments": ("Vertex Moments",
                "Records in the background so you can save what just happened."),
    "library": ("Clips you already have",
                "Import clips from SteelSeries Moments or another folder."),
    "tags": ("Tag your clips",
             "Check the games and dates read from file names."),
}


@dataclass
class SetupResult:
    config: Config
    enable_sonar: bool
    start_recorder: bool
    # Tags for clips brought along, written into the library once it is open.
    games: dict[str, str] = field(default_factory=dict)      # file name → game
    dates: dict[str, float] = field(default_factory=dict)    # file name → recorded


def library_snapshot(data_dir: str) -> tuple[list[str], list[str]]:
    """(games in use, clips that already have one) from a library on disk.

    Never creates a library: when an install is re-pointed, the library folder
    can be the one that is missing.
    """
    if not data_dir or not os.path.isfile(os.path.join(data_dir, DB_NAME)):
        return [], []
    library = Library(data_dir)
    try:
        return library_tags(library)
    finally:
        library.close()


def library_tags(library: Library) -> tuple[list[str], list[str]]:
    tagged = [name for name, (game, _people) in library.tags().items() if game]
    return library.known_games(), tagged


def default_export_dir(clip_dir: str) -> str:
    return os.path.join(clip_dir, APP_NAME, "Exports")


class FirstRunView(QWidget):
    finished = Signal(object)    # SetupResult
    cancelled = Signal()

    def __init__(self, context, config: Config | None = None, missing=(),
                 again: bool = False, parent=None):
        """`again`: run from Settings on a running Vertex, with its settings
        filled in and a Cancel that leaves them as they were."""
        super().__init__(parent)
        self.context = context
        self.again = again
        self.config = config or default_config()
        if config is not None:
            # Re-pointing an existing install: keep its settings, fill blanks.
            defaults = default_config()
            for key in ("clip_path", "export_path", "data_path", "state_path", "cache_path"):
                if not getattr(self.config, key):
                    setattr(self.config, key, getattr(defaults, key))
        self.gsr_info: gsr.GsrInfo | None = None
        self.notifier_path: str | None = None     # GSR's notifier, once looked for
        self.copy_plan: importing.CopyPlan | None = None
        self.tag_plan: importing.ImportPlan | None = None
        self._scan_token = 0
        self._tag_token = 0
        self._copying = False
        self._cancel = workers.Cancel()
        self._copy_note = ""
        self._stopped_note = ""

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        column = QVBoxLayout()
        column.setContentsMargins(0, 28, 0, 24)
        column.setSpacing(10)
        outer.addLayout(column, 4)
        outer.addStretch(1)

        self.mark = QLabel()
        theme.themed(self.mark, self._show_mark, "icon")
        column.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignHCenter)
        self.step_label = label("", "Dim")
        self.step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.step_label)
        self.heading = label("", "Heading")
        self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.heading)
        self.intro = label("", "Muted", wrap=True)
        self.intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.intro)
        column.addSpacing(6)

        self.stack = QStackedWidget()
        column.addWidget(self.stack, 1)
        self.pages: dict[str, QWidget] = {}
        for key, build in (("folders", lambda: self._folders(missing)),
                           ("sonar", self._sonar), ("moments", self._moments),
                           ("library", self._library), ("tags", self._tags)):
            self.pages[key] = self._page(build())
            self.stack.addWidget(self.pages[key])

        actions = QHBoxLayout()
        self.back_button = button("Back", "ghost", on_click=lambda: self._go(-1))
        self.next_button = button("Continue", "primary", on_click=lambda: self._go(1))
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        if again:
            self.cancel_button = button("Cancel", on_click=self.cancelled.emit)
            actions.addWidget(self.cancel_button)
        actions.addWidget(self.next_button)
        column.addLayout(actions)
        self._show("folders")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # On a short window the steps need the room more than the logo does.
        self.mark.setVisible(self.height() >= 700)

    @staticmethod
    def _page(content: QWidget) -> QScrollArea:
        """A step's content, top-aligned and scrolling when the window is short."""
        page = QWidget()
        holder = QVBoxLayout(page)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(content)
        holder.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll

    @staticmethod
    def _column(*widgets: QWidget) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for widget in widgets:
            layout.addWidget(widget)
        return host

    # --- Step 1: the clips folder -----------------------------------------------

    def _folders(self, missing) -> QWidget:
        section = Section("Your clips folder", "New clips are saved here")
        if missing:
            named = "\n".join(f"{FOLDER_NAMES.get(key, key)}: {path}" for key, path in missing)
            warning = label(f"Some folders couldn't be found. Nothing was deleted.\n\n{named}",
                            wrap=True)
            theme.style(warning, lambda: f"color: {theme.WARN};")
            section.add(warning)
        self.clip_path = PathField(self.config.clip_path)
        self.export_path = PathField(self.config.export_path)
        section.add_row("Clips", self.clip_path)
        section.add_row("Exports", self.export_path, "Videos you export from the editor.")
        self.clip_path.setMinimumWidth(360)
        self.export_path.setMinimumWidth(360)
        # Exports live inside the clips folder by default, and move with it
        # until they are given a folder of their own.
        self._exports_follow = \
            self.export_path.value() == default_export_dir(self.clip_path.value())
        self._moving_exports = False
        self.clip_path.changed.connect(self._clips_moved)
        self.export_path.changed.connect(self._exports_changed)
        return section

    def _clips_moved(self, clips: str) -> None:
        if self._exports_follow and clips:
            self._moving_exports = True
            self.export_path.set_value(default_export_dir(clips))
            self._moving_exports = False

    def _exports_changed(self, _path: str) -> None:
        if not self._moving_exports:
            self._exports_follow = False

    # --- Step 2: Vertex Sonar -----------------------------------------------------

    def _sonar(self) -> QWidget:
        section = Section()
        self.sonar_enabled = Toggle(self.config.sonar.enabled if self.again else True)
        section.add_row("Use Vertex Sonar", self.sonar_enabled)
        section.add(hline())
        self.output = QComboBox()
        self.mic = QComboBox()
        for combo in (self.output, self.mic):
            combo.addItem("System default", "")
        output = DeviceField("Output device", "Headset or speakers", self.output)
        output.set_colour("headphones", "TEXT_MUTED")
        mic = DeviceField("Input device", "In chat apps, pick Vertex Mic", self.mic)
        mic.set_colour(icons.channel_icon_name("mic"), "MIC")
        row = QHBoxLayout()
        row.setSpacing(16)
        for device_field in (output, mic):
            # Descriptions wrap to different heights; the drop-downs stay level.
            fields = device_field.layout()
            fields.insertStretch(fields.count() - 1, 1)
            row.addWidget(device_field, 1)
        section.body.addLayout(row)
        self.sonar_enabled.toggled.connect(self.output.setEnabled)
        self.sonar_enabled.toggled.connect(self.mic.setEnabled)
        self.sonar_note = label("", wrap=True)
        theme.style(self.sonar_note, lambda: f"color: {theme.WARN};")
        self.sonar_note.hide()
        section.add(self.sonar_note)
        clips = label("Game, chat and mic are saved as separate tracks in clips.", "Dim",
                      wrap=True)
        sonar = self.context.sonar.sonar
        workers.run(lambda: (sonar.outputs(), sonar.inputs()), self._got_devices,
                    lambda exc: self._no_audio(str(exc)))
        return self._column(section, clips)

    def _got_devices(self, pair) -> None:
        outputs, inputs = pair
        status = self.context.sonar.status
        for combo, devices, current in (
                (self.output, outputs, status.output or self.config.sonar.output_device),
                (self.mic, inputs, status.mic or self.config.sonar.mic_device)):
            for device in devices:
                combo.addItem(device.label, device.name)
            if self.again and combo.findData(current) > 0:
                combo.setCurrentIndex(combo.findData(current))

    def _no_audio(self, error: str) -> None:
        self.sonar_enabled.setChecked(False)
        self.sonar_enabled.setEnabled(False)
        self.sonar_note.setText(f"No audio server found ({error}).")
        self.sonar_note.show()

    # --- Step 3: Vertex Moments -------------------------------------------------

    def _moments(self) -> QWidget:
        self.install = Section()
        row = QHBoxLayout()
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.install_title = label("")
        self.install_title.setStyleSheet("font-weight: 600;")
        text.addWidget(self.install_title)
        self.install_text = label("", "Muted", wrap=True)
        text.addWidget(self.install_text)
        row.addLayout(text, 1)
        self.install_button = button("How to install it", "primary",
                                     on_click=lambda: QDesktopServices.openUrl(
                                         QUrl(gsr.INSTALL_URL)))
        row.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.recheck_button = button("Check again", on_click=self._find_recorder)
        row.addWidget(self.recheck_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.install.body.addLayout(row)
        self.install.hide()

        section = Section("Recording")
        self.gsr_status = label("Looking for GPU Screen Recorder…", "Dim", wrap=True)
        section.add(self.gsr_status)
        # Its notifier, which shows Vertex's notifications over games.
        self.notifier_row = QWidget()
        notifier_line = QHBoxLayout(self.notifier_row)
        notifier_line.setContentsMargins(0, 0, 0, 0)
        notifier_line.setSpacing(10)
        self.notifier_status = label("", wrap=True)
        notifier_line.addWidget(self.notifier_status, 1)
        self.notifier_check = button("Check again", on_click=self._find_recorder)
        notifier_line.addWidget(self.notifier_check, 0, Qt.AlignmentFlag.AlignVCenter)
        self.notifier_row.hide()
        section.add(self.notifier_row)
        # The same choices as Settings › Recording, built by the same code.
        self.choices = ClipChoices(self)
        self.choices.capture = self.config.recorder.capture
        self.choices.add_to(section)
        self.choices.changed.connect(self._choices_changed)
        self.choices.quality_picked.connect(self._quality_picked)
        self.choices.monitors_changed.connect(self._choices_changed)
        self.rec_autostart = Toggle(self.config.recorder.autostart if self.again else False)
        self._autostart_touched = self.again
        self.rec_autostart.clicked.connect(lambda: setattr(self, "_autostart_touched", True))
        section.add_row("Start the replay buffer with Vertex", self.rec_autostart)
        # Settings' clip size, which follows the choices above.
        self.clip_size = section.add(ClipSize())
        self.moments_error = label("", wrap=True)
        theme.style(self.moments_error, lambda: f"color: {theme.DANGER};")
        self.moments_error.hide()
        section.add(self.moments_error)
        self.choices.show_capture()
        self._choices_changed()
        self._find_recorder()
        return self._column(self.install, section)

    def _choices_changed(self) -> None:
        self.choices.apply(self.config.recorder)
        self.choices.show(self.config.recorder)
        self.clip_size.estimate(self.config, self.choices.recorded)

    def _quality_picked(self) -> None:
        # As in Settings: picking a level drops a bitrate set by hand.
        if self.choices.video_quality.currentData() != "custom":
            self.config.recorder.bitrate_kbps = 0
        self._choices_changed()

    def _find_recorder(self) -> None:
        command = self.config.recorder.command
        self.recheck_button.setEnabled(False)
        self.notifier_check.setEnabled(False)

        def probe():
            info = gsr.detect(command)
            usable = info.available and not info.too_old
            return (info, gsr.list_capture_options(command) if usable else [],
                    notifier.find())

        workers.run(probe, self._got_recorder)

    def _got_recorder(self, result) -> None:
        info, options, notifier_path = result
        self.notifier_path = notifier_path
        self._show_notifier(bool(notifier_path))
        self.gsr_info = info
        self.recheck_button.setEnabled(True)
        usable = info.available and not info.too_old
        self.install.setVisible(not usable)
        self.rec_autostart.setEnabled(usable)
        self.choices.set_capture_options(options)
        self._choices_changed()
        if usable:
            self.gsr_status.setText(f"Recording with GPU Screen Recorder {info.version_text}.")
            theme.style(self.gsr_status, lambda: f"color: {theme.OK};")
            if not self._autostart_touched:
                self.rec_autostart.setChecked(True)
            return
        self.rec_autostart.setChecked(False)
        theme.style(self.gsr_status, lambda: f"color: {theme.WARN};")
        later = "Or carry on and set it up later in Settings."
        if info.too_old:
            self.gsr_status.setText(f"GPU Screen Recorder {info.version_text} is too old.")
            minimum = ".".join(map(str, gsr.MIN_VERSION))
            self.install_title.setText("Update GPU Screen Recorder")
            self.install_text.setText(f"Version {minimum} or newer is needed (you have "
                                      f"{info.version_text}). {later}")
            self.install_button.setText("How to update it")
        elif not info.missing:
            self.gsr_status.setText("GPU Screen Recorder didn't start.")
            self.install_title.setText("GPU Screen Recorder didn't start")
            self.install_text.setText(f"{info.error} {later}")
            self.install_button.setText("How to install it")
        else:
            self.gsr_status.setText("GPU Screen Recorder isn't installed.")
            self.install_title.setText("Install GPU Screen Recorder")
            self.install_text.setText(f"Vertex records with GPU Screen Recorder, which isn't "
                                      f"installed. {later}")
            self.install_button.setText("How to install it")

    def _show_notifier(self, found: bool) -> None:
        self.notifier_check.setEnabled(True)
        self.notifier_check.setVisible(not found)
        if found:
            self.notifier_status.setText("In-game notifications available")
            theme.style(self.notifier_status, lambda: f"color: {theme.OK};")
        else:
            # Only a warning: everything else works without it.
            self.notifier_status.setText(
                "Optional: for ShadowPlay-style notifications over games, also install "
                "gpu-screen-recorder-notification.")
            theme.style(self.notifier_status, lambda: f"color: {theme.WARN};")
        self.notifier_row.show()

    def _check_recording(self) -> bool:
        self.choices.apply(self.config.recorder)
        problems = gsr.validate(self.choices.recorded(self.config.recorder))
        self.moments_error.setText(problems[0] if problems else "")
        self.moments_error.setVisible(bool(problems))
        return not problems

    # --- Step 4: clips someone already has ------------------------------------------

    def _library(self) -> QWidget:
        choose = Section()
        if self.again:
            self.fresh = ChoiceCard("Nothing to bring in", "Your library stays as it is.")
        else:
            self.fresh = ChoiceCard("Start fresh", "Begin with an empty library")
        self.existing = ChoiceCard("I already have clips",
                                   "From SteelSeries Moments or anywhere else")
        ChoiceCard.join(self.fresh, self.existing)
        self.fresh.setChecked(True)
        pair = QHBoxLayout()
        pair.setSpacing(12)
        pair.addWidget(self.fresh, 1)
        pair.addWidget(self.existing, 1)
        choose.body.addLayout(pair)

        self.where = Section("Where are they?")
        self.source = PathField(placeholder="The folder with your clips")
        self.where.add(self.source)
        self.source_summary = label("", "Muted", wrap=True)
        self.where.add(self.source_summary)
        self.in_place = ChoiceCard("Use them where they are", "Make this your clips folder")
        self.copy_in = ChoiceCard("Copy them to your clips folder", "")
        ChoiceCard.join(self.in_place, self.copy_in)
        self.in_place.setChecked(True)
        pair = QHBoxLayout()
        pair.setSpacing(12)
        pair.addWidget(self.in_place, 1)
        pair.addWidget(self.copy_in, 1)
        self.where.body.addLayout(pair)
        self.folders = FolderList()
        self.folders.changed.connect(self._folders_changed)
        self.where.add(self.folders)
        self.copy_summary = label("", "Muted", wrap=True)
        self.where.add(self.copy_summary)
        self.progress_row = QWidget()
        progress = QHBoxLayout(self.progress_row)
        progress.setContentsMargins(0, 0, 0, 0)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        progress.addWidget(self.progress, 1)
        self.stop_button = button("Stop", on_click=lambda: self._cancel.set())
        progress.addWidget(self.stop_button)
        self.progress_row.hide()
        self.where.add(self.progress_row)
        self.where.hide()

        for card in (self.fresh, self.existing, self.in_place, self.copy_in):
            card.chosen.connect(self._library_changed)
        self._scan_timer = QTimer(self, singleShot=True, interval=400)
        self._scan_timer.timeout.connect(self._scan)
        self.source.changed.connect(lambda _path: self._scan_timer.start())
        return self._column(choose, self.where)

    def _bringing_clips(self) -> bool:
        return self.existing.isChecked()

    def _library_changed(self) -> None:
        self.where.setVisible(self._bringing_clips())
        self._describe_modes()
        self._refresh_buttons()
        if self._bringing_clips() and self.source.value() and self.copy_plan is None:
            self._scan()

    def _describe_modes(self) -> None:
        clips = paths.tilde(self.clip_path.value()) or "your clips folder"
        self.copy_in.text.setText(f"Copy to {clips}")
        self.copy_summary.setVisible(self.copy_in.isChecked())
        self.folders.show_plan(self.copy_plan if self.copy_in.isChecked() else None)
        self._describe_found()

    def _scan(self) -> None:
        self._scan_timer.stop()
        self._scan_token += 1
        token = self._scan_token
        self.copy_plan = None
        self.folders.show_plan(None)
        source, target = self.source.value(), self.clip_path.value()
        self._refresh_buttons()
        if not source:
            self.source_summary.setText("")
            self.copy_summary.setText("")
            return
        self._say(self.source_summary, "Looking…")

        def scan():
            if not os.path.isdir(source):
                return None
            return importing.plan_copy(source, target)

        def done(plan):
            if token == self._scan_token:
                self._scanned(plan)

        def failed(exc):
            if token == self._scan_token:
                self._say(self.source_summary, f"Couldn't read that folder: {exc}", "DANGER")

        workers.run(scan, done, failed)

    def _scanned(self, plan: importing.CopyPlan | None) -> None:
        self.copy_summary.setText("")
        if plan is None:
            self._say(self.source_summary, "That folder doesn't exist.", "WARN")
            self._refresh_buttons()
            return
        if not plan.found:
            self._say(self.source_summary, "There are no clips in this folder.", "WARN")
            self._refresh_buttons()
            return
        self.copy_plan = plan
        self._describe_found()
        if self.copy_in.isChecked():
            self.folders.show_plan(plan)
        self._describe_copy()

    def _describe_found(self) -> None:
        plan = self.copy_plan
        if plan is None:
            return
        text = f"Found {fmt.plural(plan.found, 'clip')}."
        inside = plan.found - sum(f.clips for f in plan.folders if not f.path)
        if inside and self.in_place.isChecked():
            # The library shows the clips folder itself, not the folders in it.
            self._say(self.source_summary, f"{text} {inside} of them are in folders inside "
                                           f"it, which Vertex doesn't show: copy them to "
                                           f"bring those in.", "WARN")
            return
        self._say(self.source_summary, text, "OK")

    def _folders_changed(self) -> None:
        if self.copy_plan is not None:
            self.copy_plan.leave_out(self.folders.left_out())
            self._describe_copy()

    def _describe_copy(self) -> None:
        plan = self.copy_plan
        if not plan.files:
            self._say(self.copy_summary, "Every folder is left out" if plan.left_out and
                      not plan.present else "Already in your clips folder")
        elif not plan.fits:
            self._say(self.copy_summary, f"Copying needs {plan.total_human}, and only "
                                         f"{plan.free_human} is free there.", theme.DANGER)
        else:
            present = f" {fmt.plural(len(plan.present), 'clip')} already there will be " \
                      f"skipped." if plan.present else ""
            self._say(self.copy_summary, f"Copies {fmt.plural(len(plan.files), 'clip')} "
                                         f"({plan.total_human}); {plan.free_human} is free "
                                         f"there.{present}")
        if self._stopped_note:
            self._say(self.copy_summary, f"{self._stopped_note} {self.copy_summary.text()}",
                      "WARN")
            self._stopped_note = ""
        self._refresh_buttons()

    def _show_mark(self) -> None:
        pixmap = QPixmap(str(paths.mark_path(theme.logo_ink())))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            scaled = pixmap.scaledToHeight(int(56 * ratio),
                                           Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            self.mark.setPixmap(scaled)

    @staticmethod
    def _say(widget: QLabel, text: str, colour: str = "") -> None:
        """`colour`: a token of the scheme in use ("WARN"), or none."""
        widget.setText(text)
        theme.style(widget, lambda: f"color: {theme.colour(colour)};" if colour else "")

    def _library_ready(self) -> bool:
        if not self._bringing_clips():
            return True
        plan = self.copy_plan
        if plan is None:
            return False
        return self.in_place.isChecked() or not plan.files or plan.fits

    def _start_copy(self) -> None:
        plan = self.copy_plan
        self._copying = True
        self._cancel.clear()
        self.progress.setValue(0)
        self.progress_row.show()
        for widget in (self.source, self.fresh, self.existing, self.in_place, self.copy_in):
            widget.setEnabled(False)
        self.folders.set_enabled(False)
        self._refresh_buttons()
        total = max(1, plan.total_bytes)

        def progress(index, name, done_bytes):
            workers.post(self._copy_progress, (index, name, done_bytes / total))

        workers.run(lambda: importing.copy_clips(plan, progress, self._cancel.is_set),
                    self._copied)

    def _copy_progress(self, payload) -> None:
        index, name, fraction = payload
        self.progress.setValue(int(fraction * 1000))
        self._say(self.copy_summary, f"Copying {index} of {len(self.copy_plan.files)}: {name}")

    def _copied(self, result) -> None:
        copied, failed = result
        planned = len(self.copy_plan.files)
        self._copying = False
        self.progress_row.hide()
        for widget in (self.source, self.fresh, self.existing, self.in_place, self.copy_in):
            widget.setEnabled(True)
        self.folders.set_enabled(True)
        if self._cancel.is_set() and len(copied) + len(failed) < planned:
            self._stopped_note = f"Stopped after copying {fmt.plural(len(copied), 'clip')}."
            self._scan()
            return
        self._copy_note = f"Copied {fmt.plural(len(copied), 'clip')}."
        if failed:
            name, error = failed[0]
            self._copy_note += f" {len(failed)} couldn't be copied — the first, {name}: {error}"
        self._scan()
        self._show("tags")

    def _library_folder(self) -> str:
        """The folder the clips being brought along end up in."""
        if self.in_place.isChecked():
            return self.source.value()
        return self.clip_path.value()

    # --- Step 5: tags -------------------------------------------------------------

    def _tags(self) -> QWidget:
        self.tags_note = label("", "Muted", wrap=True)
        self.tags_note.hide()
        self.tags_status = label("", "Muted", wrap=True)
        self.names = Section("Teach Vertex your file names",
                             "For clips whose names Vertex doesn't read yet.")
        self.teacher = NameTeacher()
        self.names.add(self.teacher)
        self.names.hide()
        self._teach_timer = QTimer(self, singleShot=True, interval=300)
        self._teach_timer.timeout.connect(self._plan_tags)
        self.teacher.changed.connect(self._teach_timer.start)
        self.games = Section("Games found in file names")
        self.games_host = QWidget()
        self.games_grid = QGridLayout(self.games_host)
        self.games_grid.setContentsMargins(0, 0, 0, 0)
        self.games_grid.setHorizontalSpacing(14)
        self.games_grid.setVerticalSpacing(8)
        self.games_grid.setColumnStretch(0, 1)
        self.games.add(self.games_host)
        self.others = Section("Clips without a game in their name")
        self.others_text = label("", "Muted", wrap=True)
        self.others.add(self.others_text)
        self.stray_game = QLineEdit()
        self.others.add(self.stray_game)
        self.game_fields: dict[str, QLineEdit] = {}
        return self._column(self.tags_note, self.tags_status, self.names, self.games,
                            self.others)

    def _plan_tags(self) -> None:
        self._tag_token += 1
        token = self._tag_token
        self.tag_plan = None
        folder = self._library_folder()
        self.tags_note.setText(self._copy_note)
        self.tags_note.setVisible(bool(self._copy_note))
        self.tags_status.setText("Reading your clips…")
        self.tags_status.show()
        self.games.hide()
        self.others.hide()
        self._refresh_buttons()
        library = self.context.library
        if library is not None:
            # Run again: the library is open, and used from this thread only.
            snapshot = library_tags(library)
        else:
            snapshot = None
            data_dir = self.config.resolved_data_dir()

        patterns = self._patterns()

        def plan():
            known, tagged = snapshot if snapshot is not None else library_snapshot(data_dir)
            return importing.plan_import(folder, known, tagged, patterns)

        def done(result):
            if token == self._tag_token:
                self._show_tags(result)

        def failed(exc):
            if token == self._tag_token:
                self._show_tags(importing.ImportPlan(folder=folder))
                self.tags_status.setText(f"Couldn't read {paths.tilde(folder)}: {exc}")
                self.tags_status.show()

        workers.run(plan, done, failed)

    def _patterns(self) -> list:
        """The patterns the clips are read with: the one being taught first."""
        taught = self.teacher.pattern()
        kept = [p for p in self.config.patterns() if taught is None or p.app != taught.app]
        return ([taught] if taught is not None else []) + kept

    def _show_tags(self, plan: importing.ImportPlan) -> None:
        self.tag_plan = plan
        names = [n for names in plan.games.values() for n in names] + plan.strays + \
            plan.already
        if set(names) != set(self.teacher.names):
            self.teacher.set_names(names, plan.folder)
        # Shown while there are names to teach, and kept once teaching began.
        self.names.setVisible(bool(plan.strays) or self.teacher.pattern() is not None)
        while self.games_grid.count():
            item = self.games_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.game_fields = {}
        ordered = sorted(plan.games.items(), key=lambda kv: (-len(kv[1]), kv[0].casefold()))
        for row, (game, names) in enumerate(ordered):
            entry = QLineEdit(plan.stored_as.get(game, game))
            entry.setPlaceholderText(plan.stored_as.get(game, game))
            self.games_grid.addWidget(entry, row, 0)
            self.games_grid.addWidget(label(fmt.plural(len(names), "clip"), "Muted"), row, 1)
            self.game_fields[game] = entry
        self.games.setVisible(bool(plan.games))
        one = len(plan.strays) == 1
        self.others_text.setText(
            f"{fmt.plural(len(plan.strays), 'clip')} {'doesn' if one else 'don'}'t name a "
            f"game. Give {'it' if one else 'them all'} one here, or tag "
            f"{'it' if one else 'them one by one'} in your library later.")
        self.stray_game.setPlaceholderText(f"Leave {'it' if one else 'them'} untagged")
        self.others.setVisible(bool(plan.strays))
        status = ""
        if not plan.games and not plan.strays:
            status = ("All clips are already tagged"
                      if plan.already else "There are no clips here to tag.")
        elif len(plan.already) == 1:
            status = "1 clip already has a game and keeps it."
        elif plan.already:
            status = f"{len(plan.already)} clips already have a game and keep it."
        self.tags_status.setText(status)
        self.tags_status.setVisible(bool(status))
        self._refresh_buttons()

    def _confirmed_tags(self) -> tuple[dict[str, str], dict[str, float]]:
        plan = self.tag_plan
        if plan is None:
            return {}, {}
        # A field left empty keeps the name as read from the file names.
        overrides = {game: entry.text() for game, entry in self.game_fields.items()
                     if entry.text().strip()}
        games = plan.assignments(overrides)
        stray_game = self.stray_game.text().strip()
        if stray_game:
            games.update({name: stray_game for name in plan.strays})
        return games, plan.dates

    # --- Navigation ---------------------------------------------------------------

    @property
    def steps(self) -> list[str]:
        """The steps, in order: the last one only when clips are brought along."""
        order = ["folders", "sonar", "moments", "library"]
        if self._bringing_clips():
            order.append("tags")
        return order

    def current(self) -> str:
        page = self.stack.currentWidget()
        return next(key for key, widget in self.pages.items() if widget is page)

    def _show(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        title, intro = STEPS[key]
        self.heading.setText(title)
        self.intro.setText(intro)
        if key == "library":
            self._describe_modes()
            if self._bringing_clips() and self.source.value():
                self._scan()
        elif key == "tags":
            self._plan_tags()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        key, order = self.current(), self.steps
        last = order.index(key) == len(order) - 1
        self.step_label.setText(f"Step {order.index(key) + 1} of {len(order)}")
        self.back_button.setVisible(key != "folders")
        self.back_button.setEnabled(not self._copying)
        if self.again:
            self.cancel_button.setEnabled(not self._copying)
        self.next_button.setText(("Save and close" if self.again else "Open Vertex") if last
                                 else "Continue")
        ready = not self._copying
        if key == "library":
            ready = ready and self._library_ready()
        elif key == "tags":
            ready = self.tag_plan is not None
        self.next_button.setEnabled(ready)

    def _go(self, delta: int) -> None:
        key, order = self.current(), self.steps
        if delta < 0:
            self._show(order[max(0, order.index(key) - 1)])
            return
        if key == "folders" and not self.clip_path.value():
            self.clip_path.edit.setFocus()
            return
        if key == "moments" and not self._check_recording():
            return
        if key == "library" and self._bringing_clips():
            if not self._library_ready() or self._copying:
                return
            self._copy_note = ""
            if self.copy_in.isChecked() and self.copy_plan.files:
                self._start_copy()
                return
        if key == order[-1]:
            self._finish()
            return
        self._show(order[order.index(key) + 1])

    def _finish(self) -> None:
        config = self.config
        clips = self.clip_path.value()
        exports = self.export_path.value() or default_export_dir(clips)
        if self._bringing_clips() and self.in_place.isChecked():
            # The exports folder follows the clips folder unless it was changed.
            if exports == default_export_dir(clips):
                exports = default_export_dir(self.source.value())
            clips = self.source.value()
        config.clip_path, config.export_path = clips, exports
        defaults = default_config()
        for key in ("data_path", "state_path", "cache_path"):
            if not getattr(config, key):
                setattr(config, key, getattr(defaults, key))
        self.choices.apply(config.recorder)
        config.recorder.autostart = self.rec_autostart.isChecked()
        config.sonar.output_device = self.output.currentData() or ""
        config.sonar.mic_device = self.mic.currentData() or ""
        if self._bringing_clips():
            config.name_patterns = [p.to_dict() for p in self._patterns()]
        games, dates = self._confirmed_tags() if self._bringing_clips() else ({}, {})
        self.finished.emit(SetupResult(config, self.sonar_enabled.isChecked(),
                                       self.rec_autostart.isChecked(), games, dates))
