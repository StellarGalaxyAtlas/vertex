"""Bring an existing library in: copy recordings over, then review their tags.

Both dialogs show the whole plan before anything is written, and cancelling
leaves no trace.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt, paths
from vertex.core import importing
from vertex.ui import theme, workers
from vertex.ui.widgets import button, label


class FolderList(QWidget):
    """The folders a copy found clips in, each ticked: untick one (another
    app's exports, say) to leave it out. Hidden while there is only one."""

    changed = Signal()
    MAX_HEIGHT = 240

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        top = QHBoxLayout()
        self.heading = label("", "Muted", wrap=True)
        top.addWidget(self.heading, 1)
        self.every = button("Deselect all", "ghost", on_click=self._tick_every)
        top.addWidget(self.every, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setColumnStretch(0, 1)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.host)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        # On the dialog's own ground, not the darker one of a list.
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget "
                                  "{ background: transparent; }")
        layout.addWidget(self.scroll)
        self.boxes: dict[str, QCheckBox] = {}
        self.hide()

    def show_plan(self, plan: importing.CopyPlan | None) -> None:
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        self.boxes = {}
        if plan is None or len(plan.folders) < 2:
            self.hide()
            return
        self.heading.setText(f"Found {fmt.plural(plan.found, 'clip')} in "
                             f"{len(plan.folders)} folders. Untick a folder to leave it out.")
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for row, folder in enumerate(plan.folders):
            name = folder.path or f"{os.path.basename(os.path.normpath(plan.source))} " \
                                  f"(this folder)"
            box = QCheckBox(name)
            box.setChecked(folder.path not in plan.left_out)
            box.toggled.connect(self._toggled)
            self.boxes[folder.path] = box
            self.grid.addWidget(box, row, 0)
            self.grid.addWidget(label(fmt.plural(folder.clips, "clip"), "Muted"), row, 1, right)
            self.grid.addWidget(label(fmt.size(folder.bytes), "Muted"), row, 2, right)
        self.scroll.setFixedHeight(min(self.host.sizeHint().height(), self.MAX_HEIGHT))
        self._name_every()
        self.show()

    def _toggled(self, _on: bool) -> None:
        self._name_every()
        self.changed.emit()

    def _name_every(self) -> None:
        ticked = all(box.isChecked() for box in self.boxes.values())
        self.every.setText("Deselect all" if ticked else "Select all")

    def _tick_every(self) -> None:
        tick = self.every.text() == "Select all"
        for box in self.boxes.values():
            box.blockSignals(True)
            box.setChecked(tick)
            box.blockSignals(False)
        self._toggled(tick)

    def left_out(self) -> set[str]:
        return {path for path, box in self.boxes.items() if not box.isChecked()}

    def set_enabled(self, enabled: bool) -> None:
        for box in self.boxes.values():
            box.setEnabled(enabled)
        self.every.setEnabled(enabled)


class CopyClipsDialog(QDialog):
    """Copy the recordings from another folder into the clips folder."""

    def __init__(self, parent, target: str, source: str = ""):
        super().__init__(parent)
        self.target = target
        self.plan: importing.CopyPlan | None = None     # set while it can be copied
        self._shown: importing.CopyPlan | None = None   # the plan on screen
        self.copied: list[str] = []
        self._cancel = workers.Cancel()
        self._running = False
        self.setWindowTitle("Import clips")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("Import clips", "Subheading"))
        layout.addWidget(label(
            f"Copies videos from a folder and the folders in it into {paths.tilde(target)}. "
            f"Existing files are skipped.",
            "Muted", wrap=True))
        row = QHBoxLayout()
        self.source = QLineEdit(paths.tilde(source) if source else "")
        self.source.setPlaceholderText("Folder to import from")
        row.addWidget(self.source, 1)
        row.addWidget(button("Browse…", on_click=self._browse))
        layout.addLayout(row)
        self.folders = FolderList()
        self.folders.changed.connect(self._leave_out)
        layout.addWidget(self.folders)
        self.summary = label("", "Muted", wrap=True)
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = button("Cancel", on_click=self._close)
        self.copy_button = button("Copy", "primary", on_click=self._start)
        self.copy_button.setEnabled(False)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.copy_button)
        layout.addLayout(buttons)
        self.source.editingFinished.connect(self._scan)
        if source:
            self._scan()

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "From",
                                                  paths.normalize(self.source.text()) or
                                                  paths.normalize("~"))
        if chosen:
            self.source.setText(paths.tilde(chosen))
            self._scan()

    def _say(self, text: str, colour: str = "TEXT_MUTED") -> None:
        """`colour`: a token of the scheme in use."""
        self.summary.setText(text)
        theme.style(self.summary, lambda: f"color: {theme.colour(colour)};")

    def _scan(self) -> None:
        source = paths.normalize(self.source.text())
        self.plan = None
        self.copy_button.setEnabled(False)
        self.folders.show_plan(None)
        if not source:
            return
        if not os.path.isdir(source):
            self._say("That folder does not exist.", "WARN")
            return
        if os.path.realpath(source) == os.path.realpath(self.target):
            self._say("That is the clips folder itself.", "WARN")
            return
        try:
            plan = importing.plan_copy(source, self.target)
        except OSError as exc:
            self._say(f"Couldn't read the folder: {exc}", "DANGER")
            return
        self.folders.show_plan(plan)
        self._summarise(plan)

    def _leave_out(self) -> None:
        if self._shown is not None:
            self._shown.leave_out(self.folders.left_out())
            self._summarise(self._shown)

    def _summarise(self, plan: importing.CopyPlan) -> None:
        self._shown, self.plan = plan, None
        self.copy_button.setEnabled(False)
        present = f" {fmt.plural(len(plan.present), 'clip')} already there will be skipped." \
            if plan.present else ""
        if not plan.files:
            self._say(f"Nothing new to copy.{present}")
            return
        if not plan.fits:
            self._say(f"{fmt.plural(len(plan.files), 'clip')} ({plan.total_human}) — but only "
                      f"{plan.free_human} is free there.", theme.DANGER)
            return
        self.plan = plan
        self._say(f"{fmt.plural(len(plan.files), 'clip')} to copy, {plan.total_human} "
                  f"({plan.free_human} free).{present}")
        self.copy_button.setEnabled(True)

    def _start(self) -> None:
        if self.plan is None or self._running:
            return
        self._running = True
        self.copy_button.setEnabled(False)
        self.source.setEnabled(False)
        self.folders.set_enabled(False)
        self.progress.show()
        total = max(1, self.plan.total_bytes)
        plan = self.plan

        def progress(index, name, done_bytes):
            workers.post(self._progress, (index, name, done_bytes / total))

        workers.run(lambda: importing.copy_clips(plan, progress, self._cancel.is_set),
                    self._done)

    def _progress(self, payload) -> None:
        index, name, fraction = payload
        self.progress.setValue(int(fraction * 1000))
        self._say(f"Copying {index} of {len(self.plan.files)}: {name}")

    def _done(self, result) -> None:
        self._running = False
        self.copied, failed = result
        self.progress.setValue(1000)
        text = f"Copied {fmt.plural(len(self.copied), 'clip')}."
        if failed:
            text += f" {len(failed)} failed — first: {failed[0][0]}: {failed[0][1]}"
        self._say(text, "WARN" if failed else "OK")
        self.close_button.setText("Done")

    def _close(self) -> None:
        if self._running:
            self._cancel.set()
            return
        if self.copied:
            self.accept()
        else:
            self.reject()


class TagImportDialog(QDialog):
    """Tag the clips in a folder with the games their file names record."""

    def __init__(self, parent, library, folder: str):
        super().__init__(parent)
        self.library = library
        self.written = 0
        self.setWindowTitle("Tag clips from their names")
        self.setMinimumSize(560, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("Tag clips from their names", "Subheading"))
        try:
            self.plan = importing.plan_import(folder, library.known_games(),
                                              library.tags().keys(), names=library.game_names)
        except OSError as exc:
            self.plan = importing.ImportPlan(folder=folder)
            layout.addWidget(label(f"Couldn't read {folder}: {exc}", "Muted", wrap=True))
        plan = self.plan
        layout.addWidget(label(
            f"{fmt.plural(plan.taggable, 'clip')} carry a game in their name. Every game is "
            f"shown as it will be saved — change any of them, or clear one to skip it. "
            f"{fmt.plural(len(plan.already), 'clip')} already tagged and "
            f"{fmt.plural(len(plan.strays), 'clip')} without a game are left alone.",
            "Muted", wrap=True))
        self.fields: dict[str, QLineEdit] = {}
        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setHorizontalSpacing(14)
        for game, names in sorted(plan.games.items(), key=lambda kv: -len(kv[1])):
            field = QLineEdit(plan.stored_as.get(game, game))
            self.fields[game] = field
            form.addRow(label(f"{game}  ({len(names)})", "Muted"), field)
        scroll = QScrollArea()
        scroll.setWidget(form_host)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(button("Cancel", on_click=self.reject))
        apply = button(f"Tag {fmt.plural(plan.taggable, 'clip')}", "primary",
                       on_click=self._apply)
        apply.setEnabled(bool(plan.taggable or plan.dates))
        buttons.addWidget(apply)
        layout.addLayout(buttons)

    def _apply(self) -> None:
        overrides = {game: field.text() for game, field in self.fields.items()}
        self.written = self.library.apply_import(self.plan.assignments(overrides),
                                                 self.plan.dates)
        self.accept()
