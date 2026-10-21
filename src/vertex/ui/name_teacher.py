"""Teaching Vertex how a clip app names its clips: pick the app, or mark up
one of the names, and see what Vertex reads from the user's own clips."""

from __future__ import annotations

import datetime
import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt
from vertex.core import naming
from vertex.core.name_patterns import (
    PRESETS,
    WHEN_KINDS,
    Mark,
    NamePattern,
    PatternError,
    formats_for,
    from_marks,
)
from vertex.ui import icons, theme
from vertex.ui.widgets import FlowLayout, IconButton, Toggle, button, label

OWN = "Something else"
OWN_APP = "Your clips"
MARK_LABELS = {"game": "Game", "date": "Date", "time": "Time", "datetime": "Date and time",
               "skip": "Ignore"}
PREVIEW_ROWS = 6


def _restyle(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class NameTeacher(QWidget):
    """`changed` comes whenever `pattern()` may have changed."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._names: list[str] = []
        self._folder = ""
        self._app = ""                      # a preset's app, OWN, or "" for none
        self._marks: list[Mark] = []
        self._own_pattern: NamePattern | None = None    # one taught before
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(label("Which app recorded them? Vertex knows how these name "
                               "their clips.", "Muted", wrap=True))
        apps = QWidget()
        flow = FlowLayout(apps)
        self.app_buttons: dict[str, QPushButton] = {}
        for app in [preset.app for preset in PRESETS] + [OWN]:
            choice = button(f"{app}…" if app == OWN else app,
                            on_click=lambda _c=False, a=app: self.choose(a))
            flow.addWidget(choice)
            self.app_buttons[app] = choice
        layout.addWidget(apps)

        self.own = QWidget()
        own = QVBoxLayout(self.own)
        own.setContentsMargins(0, 0, 0, 0)
        own.setSpacing(10)
        own.addWidget(label("Pick one of your clips or paste its name. Then select a part "
                            "of the name and say what it is.", "Muted", wrap=True))
        row = QHBoxLayout()
        self.sample = QLineEdit()
        self.sample.setPlaceholderText("A clip's file name")
        self.sample.textEdited.connect(self._sample_edited)
        # Qt drops a line edit's selection when it loses focus, and a click
        # elsewhere can take it away: the last selection is kept until the
        # user clears it in the field itself.
        self._selection = (-1, "")
        self.sample.selectionChanged.connect(self._selected)
        row.addWidget(self.sample, 1)
        row.addWidget(button("Pick a clip…", on_click=self._pick))
        row.addWidget(button("Paste", on_click=self._paste))
        own.addLayout(row)
        own.addWidget(label("The selected part is the", "Muted"))
        marks_host = QWidget()
        marks = FlowLayout(marks_host)
        self.mark_buttons = {}
        for kind, text in MARK_LABELS.items():
            mark = button(text, on_click=lambda _c=False, k=kind: self._mark(k))
            mark.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            marks.addWidget(mark)
            self.mark_buttons[kind] = mark
        marks.addWidget(button("Start over", "ghost", on_click=self._clear_marks))
        own.addWidget(marks_host)
        read_as = QHBoxLayout()
        self.read_as = label("", wrap=True)
        read_as.addWidget(self.read_as, 1)
        self.format = QComboBox()
        self.format.activated.connect(self._format_chosen)
        self.format.hide()
        read_as.addWidget(self.format)
        own.addLayout(read_as)
        self.own.hide()
        layout.addWidget(self.own)

        self.options = QWidget()
        options = QVBoxLayout(self.options)
        options.setContentsMargins(0, 0, 0, 0)
        self.split_words = Toggle()
        self.split_words.toggled.connect(lambda _on: self._refresh())
        self.spaces = Toggle()
        self.spaces.toggled.connect(lambda _on: self._refresh())
        for toggle, text in ((self.split_words, "Split joined words in game names: "
                                                "FirstLight → First Light"),
                             (self.spaces, "Dashes and underscores in game names are spaces")):
            line = QHBoxLayout()
            line.addWidget(toggle)
            line.addWidget(label(text), 1)
            options.addLayout(line)
        self.options.hide()
        layout.addWidget(self.options)

        self.note = label("", wrap=True)
        self.note.hide()
        layout.addWidget(self.note)
        self.preview_title = label("", "Muted")
        layout.addWidget(self.preview_title)
        self.preview_host = QWidget()
        self.preview = QGridLayout(self.preview_host)
        self.preview.setContentsMargins(0, 0, 0, 0)
        self.preview.setHorizontalSpacing(18)
        self.preview.setColumnStretch(0, 1)
        layout.addWidget(self.preview_host)
        self._refresh()

    # --- What it is shown and gives ------------------------------------------------

    @property
    def names(self) -> list[str]:
        return list(self._names)

    def set_names(self, names, folder: str = "") -> None:
        """The user's own clip names (in `folder`), to preview with and to
        start a name from."""
        self._names, self._folder = sorted(names), folder
        if not self.sample.text() and self._names:
            self.sample.setText(self._names[0])
        self._refresh()

    def set_pattern(self, pattern: NamePattern | None) -> None:
        """Show a pattern taught before."""
        preset = next((p for p in PRESETS if pattern and p.pattern.template ==
                       pattern.template), None)
        if pattern is None:
            self._app = ""
        elif preset is not None:
            self._app = preset.app
        else:
            self._app = OWN
            self._marks = []
        self._own_pattern = pattern if self._app == OWN else None
        self._show_choice(pattern)

    def leave_out(self, apps) -> None:
        """Hide the buttons of apps that are taught already."""
        for app, choice in self.app_buttons.items():
            choice.setVisible(app not in apps)

    def pattern(self) -> NamePattern | None:
        """The pattern as it stands, or None if there isn't one (yet)."""
        split, spaces = self.split_words.isChecked(), "-_" if self.spaces.isChecked() else ""
        if self._app == OWN:
            base = self._own()
            if base is None:
                return None
            return NamePattern(OWN_APP, base.template, split, spaces)
        preset = next((p for p in PRESETS if p.app == self._app), None)
        if preset is None:
            return None
        return NamePattern(preset.app, preset.pattern.template, split, spaces)

    # --- Choosing an app ----------------------------------------------------------

    def choose(self, app: str) -> None:
        self._app = app
        preset = next((p for p in PRESETS if p.app == app), None)
        self._own_pattern = None
        self._show_choice(preset.pattern if preset else None)

    def _show_choice(self, pattern: NamePattern | None) -> None:
        for app, choice in self.app_buttons.items():
            choice.setProperty("kind", "primary" if app == self._app else "")
            _restyle(choice)
        if pattern is not None:
            for toggle, on in ((self.split_words, pattern.split_words),
                               (self.spaces, bool(pattern.spaces))):
                toggle.blockSignals(True)
                toggle.setChecked(on)
                toggle.blockSignals(False)
        self.own.setVisible(self._app == OWN)
        self.options.setVisible(bool(self._app))
        self._refresh()

    # --- Marking up a name ----------------------------------------------------------

    def _pick(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Pick a clip", self._folder,
                                                    "Videos (*.mp4 *.mkv);;All files (*)")
        if path:
            self._set_sample(os.path.basename(path))

    def _paste(self) -> None:
        text = QApplication.clipboard().text().strip().splitlines()
        if text:
            self._set_sample(os.path.basename(text[0].strip().strip('"')))

    def _set_sample(self, name: str) -> None:
        self.sample.setText(name)
        self._sample_edited()

    def _selected(self) -> None:
        if self.sample.hasSelectedText():
            self._selection = (self.sample.selectionStart(), self.sample.selectedText())
        elif self.sample.hasFocus():
            self._selection = (-1, "")

    def _sample_edited(self, _text: str = "") -> None:
        self._selection = (-1, "")
        self._marks = []
        self._own_pattern = None
        self._refresh()

    def _clear_marks(self) -> None:
        self._selection = (-1, "")
        self._marks = []
        self._own_pattern = None
        self._refresh()

    def _mark(self, kind: str) -> None:
        start, text = self._selection
        if start < 0 or not text:
            self._say("Select a part of the name first, then say what it is.", "WARN")
            return
        mark_format = ""
        if kind in WHEN_KINDS:
            formats = formats_for(kind, text)
            if not formats:
                what = {"date": "a date", "time": "a time", "datetime": "a date and time"}
                self._say(f"Vertex can't read “{text}” as {what[kind]}.", "WARN")
                return
            mark_format = formats[0]
        new = Mark(start, start + len(text), kind, mark_format)
        # A part can be marked once; a new mark replaces what it overlaps.
        reads = {"datetime": {"date", "time", "datetime"}, "date": {"date", "datetime"},
                 "time": {"time", "datetime"}, "game": {"game"}}.get(kind, set())
        self._marks = [m for m in self._marks if m.kind not in reads and
                       (m.end <= new.start or m.start >= new.end)] + [new]
        self._own_pattern = None
        self._selection = (-1, "")
        self.sample.deselect()
        self._refresh()

    def _format_chosen(self, index: int) -> None:
        mark = self._last_when()
        if mark is not None:
            self._marks[self._marks.index(mark)] = Mark(mark.start, mark.end, mark.kind,
                                                         self.format.itemText(index))
            self._own_pattern = None
            self._refresh()

    def _last_when(self) -> Mark | None:
        return next((m for m in reversed(self._marks) if m.kind in WHEN_KINDS), None)

    def _own(self) -> NamePattern | None:
        if self._own_pattern is not None and not self._marks:
            return self._own_pattern
        if not self._marks or not self.sample.text():
            return None
        try:
            return from_marks(self.sample.text(), self._marks, OWN_APP)
        except PatternError:
            return None

    # --- Showing it ---------------------------------------------------------------

    def _say(self, text: str, colour: str = "") -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))
        theme.style(self.note, lambda: f"color: {theme.colour(colour)};" if colour else "")

    def _describe_marks(self) -> None:
        stem = self.sample.text()
        if not self._marks:
            pattern = self._own_pattern
            self.read_as.setText(f"Read as: {pattern.template}" if pattern else
                                 "Nothing marked yet.")
            self.format.hide()
            return
        pieces, at = [], 0
        for mark in sorted(self._marks, key=lambda m: m.start):
            pieces.append(stem[at:mark.start])
            name = MARK_LABELS[mark.kind]
            pieces.append(f"[{name}: {mark.format}]" if mark.format else f"[{name}]")
            at = mark.end
        pieces.append(stem[at:])
        self.read_as.setText("Read as: " + "".join(pieces))
        last = self._last_when()
        formats = formats_for(last.kind, stem[last.start:last.end]) if last else []
        self.format.clear()
        self.format.addItems(formats)
        if last is not None:
            self.format.setCurrentText(last.format)
        self.format.setVisible(len(formats) > 1)

    def _refresh(self) -> None:
        if self._app == OWN:
            self._describe_marks()
        pattern = self.pattern()
        preset = next((p for p in PRESETS if p.app == self._app), None)
        if preset is not None and not preset.checked:
            self._say("Check the preview below matches your clips", "WARN")
        elif self._app == OWN and self._marks and pattern is None:
            self._say("Those marks don't fit together. Start over and mark the parts again.",
                      "WARN")
        else:
            self._say("")
        self._show_preview(pattern)
        self.changed.emit()

    def _show_preview(self, pattern: NamePattern | None) -> None:
        while self.preview.count():
            self.preview.takeAt(0).widget().deleteLater()
        names = self._names
        if pattern is None or not names:
            self.preview_title.hide()
            self.preview_host.hide()
            return
        readings = [(name, pattern.read(name)) for name in names]
        read = sum(1 for _n, reading in readings if reading is not None)
        self.preview_title.setText(f"What Vertex reads: {read} of "
                                   f"{fmt.plural(len(names), 'clip')}")
        # The ones it doesn't read first: they are the ones to look at.
        readings.sort(key=lambda item: item[1] is not None)
        for row, (name, reading) in enumerate(readings[:PREVIEW_ROWS]):
            self.preview.addWidget(label(name, "Muted"), row, 0)
            if reading is None:
                missed = label("Not read")
                theme.style(missed, lambda w=missed: f"color: {theme.WARN};")
                self.preview.addWidget(missed, row, 1)
                continue
            self.preview.addWidget(label(reading.game or "No game"), row, 1)
            when = datetime.datetime.fromtimestamp(reading.when).strftime("%Y-%m-%d %H:%M") \
                if reading.when else "No date"
            self.preview.addWidget(label(when, "Muted"), row, 2)
        self.preview_title.show()
        self.preview_host.show()


# --- The apps Vertex reads names with ----------------------------------------------


def _same(one: NamePattern, other: NamePattern) -> bool:
    """Whether `other` takes `one`'s place: the same app, or for names marked
    by hand, the same marks."""
    return one.app == other.app and (one.app != OWN_APP or one.template == other.template)


class _Grip(QLabel):
    """The handle a source row is dragged by."""

    def __init__(self, sources: NameSources, row: QWidget):
        super().__init__()
        self._sources, self._row = sources, row
        theme.themed(self, lambda: self.setPixmap(
            icons.icon("grip", "TEXT_DIM", 16).pixmap(QSize(16, 16))), "icon")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to change the order")

    def mousePressEvent(self, event):
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        self._sources._drag(self._row, event.globalPosition().toPoint().y())

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._sources._dropped()


class NameSources(QWidget):
    """The apps Vertex reads clip names with, tried top to bottom, and adding
    another one, taught from the clips none of them reads yet.

    `changed` comes when the list changes, `added` when an app joins it, and
    `draft_changed` while one is being taught."""

    changed = Signal()
    added = Signal()
    draft_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._patterns: list[NamePattern] = []
        self._rows: list[QWidget] = []
        self._names: list[str] = []
        self._folder = ""
        self._moved = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.hint = label("Tried in this order", "Muted", wrap=True)
        layout.addWidget(self.hint)
        self.rows_host = QWidget()
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(6)
        layout.addWidget(self.rows_host)
        self.always = QFrame()
        self.always.setObjectName("AlwaysRow")
        theme.style(self.always, lambda: (
            f"#AlwaysRow {{ border: 1px dashed {theme.SEAM}; "
            f"border-radius: {theme.RADIUS_SMALL}px; }}"))
        always = QHBoxLayout(self.always)
        always.setContentsMargins(12, 8, 12, 8)
        always.addWidget(label("Built in: SteelSeries Moments, GPU Screen Recorder", "Muted"), 1)
        self.always_count = label("", "Muted")
        always.addWidget(self.always_count)
        layout.addWidget(self.always)
        bar = QHBoxLayout()
        self.add_button = button("Add another app", icon="plus", on_click=self.start_adding)
        bar.addWidget(self.add_button)
        bar.addStretch(1)
        self.status = label("")
        bar.addWidget(self.status)
        layout.addLayout(bar)

        self.adding = QWidget()
        adding = QVBoxLayout(self.adding)
        adding.setContentsMargins(0, 8, 0, 0)
        adding.setSpacing(12)
        self.adding_title = label("", "Subheading")
        adding.addWidget(self.adding_title)
        self.teacher = NameTeacher()
        self.teacher.changed.connect(self._draft_changed)
        adding.addWidget(self.teacher)
        done = QHBoxLayout()
        done.addStretch(1)
        self.cancel = button("Cancel", on_click=self.stop_adding)
        done.addWidget(self.cancel)
        self.add_to_list = button("Add to the list", "primary", on_click=self._add)
        done.addWidget(self.add_to_list)
        adding.addLayout(done)
        self.adding.hide()
        layout.addWidget(self.adding)
        self._build_rows()
        self._refresh()

    # --- What it holds ----------------------------------------------------------

    def patterns(self) -> list[NamePattern]:
        return list(self._patterns)

    def set_patterns(self, patterns) -> None:
        self._patterns = list(patterns)
        self._build_rows()
        self._refresh()

    def set_names(self, names, folder: str = "") -> None:
        """The user's own clip names (in `folder`), to count and teach from."""
        self._names, self._folder = sorted(names), folder
        self._refresh()
        if not self._patterns and self.unread() and self.adding.isHidden():
            self.start_adding()           # nothing to show yet but what to teach

    def unread(self) -> list[str]:
        """The names none of the apps (nor what Vertex always knows) reads."""
        return [name for name in self._names
                if naming.reader_of(name, self._patterns) is None]

    def draft(self) -> NamePattern | None:
        """The app being added, as taught so far."""
        return None if self.adding.isHidden() else self.teacher.pattern()

    # --- Adding and removing ------------------------------------------------------

    def start_adding(self) -> None:
        self.teacher.set_pattern(None)
        self.teacher.leave_out({p.app for p in self._patterns if p.app != OWN_APP})
        self.adding.show()
        self.add_button.hide()
        self._teach_from()
        self.draft_changed.emit()

    def stop_adding(self) -> None:
        self.adding.hide()
        self.add_button.show()
        self.draft_changed.emit()

    def _add(self) -> None:
        pattern = self.teacher.pattern()
        if pattern is None:
            return
        self._patterns = [p for p in self._patterns if not _same(pattern, p)] + [pattern]
        self.stop_adding()
        self._build_rows()
        self._refresh()
        self.changed.emit()
        self.added.emit()

    def _remove(self, row: QWidget) -> None:
        index = self._rows.index(row)
        del self._patterns[index]
        self._build_rows()
        self._refresh()
        self.changed.emit()

    def _draft_changed(self) -> None:
        self.add_to_list.setEnabled(self.teacher.pattern() is not None)
        self.draft_changed.emit()

    def _teach_from(self) -> None:
        """The clips nothing reads are the ones to teach from; once every clip
        is read, any of them."""
        self.teacher.set_names(self.unread() or self._names, self._folder)

    # --- Order --------------------------------------------------------------------

    def _drag(self, row: QWidget, y: int) -> None:
        """Move the dragged row to where the pointer is."""
        index = self._rows.index(row)
        target = index
        for other, widget in enumerate(self._rows):
            middle = widget.mapToGlobal(widget.rect().center()).y()
            if other < index and y < middle:
                target = min(target, other)
            elif other > index and y > middle:
                target = other
        if target == index:
            return
        self._rows.insert(target, self._rows.pop(index))
        self._patterns.insert(target, self._patterns.pop(index))
        self.rows.removeWidget(row)
        self.rows.insertWidget(target, row)
        self._moved = True

    def _dropped(self) -> None:
        if self._moved:
            self._moved = False
            self._refresh()
            self.changed.emit()

    # --- Showing it ---------------------------------------------------------------

    def _build_rows(self) -> None:
        for row in self._rows:
            row.deleteLater()
        self._rows = []
        for pattern in self._patterns:
            row = QFrame()
            row.setObjectName("SourceRow")
            theme.style(row, lambda: (
                f"#SourceRow {{ background: {theme.CARD_BG}; "
                f"border-radius: {theme.RADIUS_SMALL}px; }}"))
            line = QHBoxLayout(row)
            line.setContentsMargins(10, 6, 6, 6)
            line.setSpacing(10)
            line.addWidget(_Grip(self, row))
            name = label(pattern.app)
            name.setStyleSheet("font-weight: 600;")
            line.addWidget(name)
            if pattern.app == OWN_APP:
                line.addWidget(label(pattern.template, "Muted"))
            line.addStretch(1)
            row.count = label("", "Muted")
            line.addWidget(row.count)
            remove = IconButton("close", f"Stop reading {pattern.app} names", 12, "TEXT_MUTED")
            remove.clicked.connect(lambda _c=False, r=row: self._remove(r))
            line.addWidget(remove)
            self.rows.addWidget(row)
            self._rows.append(row)
        self.rows_host.setVisible(bool(self._rows))
        another = "Add another app" if self._rows else "Add an app"
        self.adding_title.setText(another)
        self.add_button.setText(another)
        self.hint.setVisible(len(self._rows) > 1)

    def _refresh(self) -> None:
        readers = [naming.reader_of(name, self._patterns) for name in self._names]
        # A row's count only says something while the clips are shared out:
        # one row reading them all is what the line under the list says.
        def count_of(count: int) -> str:
            return f"reads {fmt.plural(count, 'clip')}" if 0 < count < len(self._names) else ""
        for index, row in enumerate(self._rows):
            row.count.setText(count_of(readers.count(index)))
        self.always_count.setText(count_of(readers.count(naming.BUILT_IN)))
        unread = readers.count(None)
        if not self._names:
            self.status.setText("")
        elif unread:
            self.status.setText(f"{unread} of {fmt.plural(len(self._names), 'clip')} "
                                f"aren't read yet")
            theme.style(self.status, lambda: f"color: {theme.WARN};")
        else:
            self.status.setText(f"Vertex reads all {fmt.plural(len(self._names), 'clip')}")
            theme.style(self.status, lambda: f"color: {theme.TEXT_MUTED};")
        if not self.adding.isHidden():
            self._teach_from()
        self.add_to_list.setEnabled(self.teacher.pattern() is not None)
