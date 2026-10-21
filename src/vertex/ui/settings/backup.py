"""Settings › Backup: export a backup, back up every day, and restore one,
picking what to put back from every setting, by category."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vertex import APP_NAME, backup, fmt, setting_groups
from vertex.core import storage
from vertex.setting_groups import LIBRARY
from vertex.ui import theme
from vertex.ui.widgets import IconButton, Section, TextDialog, Toggle, button, label

LIBRARY_TITLE = "Games, people, titles, favorites, trims and volumes"


def when(timestamp: float) -> str:
    """'Today, 09:12', 'Yesterday, 18:40', '19 Oct 2026, 10:02'."""
    day = time.strftime("%Y-%m-%d", time.localtime(timestamp))
    today = time.strftime("%Y-%m-%d")
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 24 * 3600))
    at = time.strftime("%H:%M", time.localtime(timestamp))
    named = {today: "Today", yesterday: "Yesterday"}.get(day, fmt.date(timestamp))
    return f"{named}, {at}"


def _left(widget: QWidget) -> QHBoxLayout:
    """`widget` at its own width, on the left."""
    row = QHBoxLayout()
    row.addWidget(widget)
    row.addStretch(1)
    return row


def trash_note() -> str:
    return ("What you have now goes to the Trash first, so you can undo this."
            if storage.trash_available() else
            "What you have now is kept beside it as a .bak file, so you can undo this.")


class BackupPage(QObject):
    """The tab's two sections. `export_requested` and `open_requested` come
    from the buttons, `restore_requested` with the path of an automatic
    backup."""

    export_requested = Signal()
    open_requested = Signal()
    restore_requested = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        make = Section("Make a backup", "Your settings and library (games, people, titles, "
                                        "trims) in one file. Clips aren't in it.")
        make.body.addLayout(_left(button("Export backup…", "primary", "export",
                                         on_click=self.export_requested.emit)))
        self.daily = Toggle()
        make.add_row("Back up every day",
                     self.daily, f"Keeps the last {backup.AUTOMATIC_KEPT} in the library folder")
        restore = Section("Restore", "Put back a backup, all of it or what you pick.")
        restore.body.addLayout(_left(button("Restore from a file…", icon="folder",
                                            on_click=self.open_requested.emit)))
        self.list_title = label("Automatic backups", "Muted")
        restore.add(self.list_title)
        self.rows_host = QWidget()
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(6)
        restore.add(self.rows_host)
        self.sections = [make, restore]
        self.set_backups([])

    def set_backups(self, found: list[tuple[str, backup.Contents]]) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for path, contents in found:
            self.rows.addWidget(self._row(path, contents))
        if not found:
            self.rows.addWidget(label("None yet. Vertex makes one a day while "
                                      "“Back up every day” is on.", "Dim", wrap=True))

    def _row(self, path: str, contents: backup.Contents) -> QWidget:
        row = QFrame()
        row.setObjectName("BackupRow")
        theme.style(row, lambda: f"#BackupRow {{ background: {theme.CARD_BG}; "
                                 f"border-radius: {theme.RADIUS_SMALL}px; }}")
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 6, 6, 6)
        line.setSpacing(10)
        line.addWidget(label(when(contents.created)))
        line.addWidget(label(fmt.plural(contents.clips, "clip"), "Muted"), 1)
        line.addWidget(button("Restore…", on_click=lambda: self.restore_requested.emit(path)))
        return row


class Category(QFrame):
    """A category's box, which ticks all of it, and its settings' boxes,
    shown when it is opened."""

    changed = Signal()

    def __init__(self, title: str, rows: list[tuple[str, backup.Choice]], opened: bool):
        super().__init__()
        self.setObjectName("PickCategory")
        theme.style(self, lambda: f"#PickCategory {{ background: {theme.CARD_BG}; "
                                  f"border-radius: {theme.RADIUS_SMALL}px; }}")
        column = QVBoxLayout(self)
        column.setContentsMargins(12, 6, 6, 6)
        column.setSpacing(4)
        head = QHBoxLayout()
        self.box = QCheckBox(title)
        self.box.setStyleSheet("font-weight: 600;")
        self.box.setTristate(True)
        self.box.clicked.connect(self._clicked)
        head.addWidget(self.box)
        head.addStretch(1)
        self.count = label("", "Muted")
        head.addWidget(self.count)
        self.toggle = IconButton("chevron-right", "Show its settings", 16)
        self.toggle.clicked.connect(lambda: self.set_open(self.body.isHidden()))
        head.addWidget(self.toggle)
        column.addLayout(head)
        self.body = QWidget()
        lines = QVBoxLayout(self.body)
        lines.setContentsMargins(26, 0, 8, 6)
        lines.setSpacing(6)
        self.boxes: dict[str, QCheckBox] = {}
        for name, choice in rows:
            line = QHBoxLayout()
            box = QCheckBox(name)
            box.setChecked(choice.default)
            box.toggled.connect(self._sync)
            line.addWidget(box)
            line.addStretch(1)
            extra = choice.note or (f"now {choice.now}" if choice.now else "")
            value = label(choice.shown + (f"  ({extra})" if extra else ""),
                          "Muted" if extra else "Dim")
            value.setToolTip(value.text())
            line.addWidget(value)
            lines.addLayout(line)
            self.boxes[choice.key] = box
        column.addWidget(self.body)
        self.set_open(opened)
        self._sync()

    def set_open(self, opened: bool) -> None:
        self.body.setVisible(opened)
        self.toggle.set_icon("chevron-down" if opened else "chevron-right")
        self.toggle.setToolTip("Hide its settings" if opened else "Show its settings")

    def set_all(self, on: bool) -> None:
        for box in self.boxes.values():
            box.blockSignals(True)
            box.setChecked(on)
            box.blockSignals(False)
        self._sync()

    def picked(self) -> list[str]:
        return [key for key, box in self.boxes.items() if box.isChecked()]

    def _clicked(self) -> None:
        # A click on a partly ticked box ticks all of it.
        self.set_all(len(self.picked()) < len(self.boxes))

    def _sync(self) -> None:
        count = len(self.picked())
        self.box.setCheckState(Qt.CheckState.Checked if count == len(self.boxes) else
                               Qt.CheckState.PartiallyChecked if count else
                               Qt.CheckState.Unchecked)
        self.count.setText(f"{count} of {len(self.boxes)}" if len(self.boxes) > 1 else "")
        self.changed.emit()


class RestoreDialog(TextDialog):
    """Which of a backup's settings, and whether its library, to put back."""

    def __init__(self, parent, contents: backup.Contents, offered: dict[str, backup.Choice],
                 left: list[str] = ()):
        """`left`: groups the backup has that this system doesn't."""
        super().__init__(parent)
        self.setWindowTitle("Restore a backup")
        self.setModal(True)
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label(f"Restore the backup from {when(contents.created)}?",
                               "Subheading", wrap=True))
        layout.addWidget(label(f"Pick what to put back. {trash_note()}", "Muted", wrap=True))
        top = QHBoxLayout()
        self.everything = QCheckBox("Everything")
        self.everything.setStyleSheet("font-weight: 600;")
        self.everything.setTristate(True)
        self.everything.clicked.connect(self._everything)
        top.addWidget(self.everything)
        top.addStretch(1)
        self.changes = button("Pick only changes", "ghost", on_click=self._only_changes)
        self.changes.setToolTip("Tick only what differs from what you have now")
        top.addWidget(self.changes)
        layout.addLayout(top)
        host = QWidget()
        host.setObjectName("PickList")
        host.setStyleSheet("#PickList { background: transparent; }")
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(8)
        self.offered = offered
        self.categories: list[Category] = []
        sections = [(group.title, [(item.title, offered[item.key]) for item in group.items
                                   if item.key in offered])
                    for group in setting_groups.groups()]
        if LIBRARY in offered:
            sections.append(("Library", [(LIBRARY_TITLE, offered[LIBRARY])]))
        for title, rows in sections:
            if not rows:
                continue
            category = Category(title, rows, opened=title == "Library")
            category.changed.connect(self._sync)
            self.categories.append(category)
            column.addWidget(category)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # As tall as the closed categories, and scrolling once some are open.
        screen = self.screen().availableGeometry().height() if self.screen() else 900
        scroll.setMinimumHeight(min(host.sizeHint().height(), int(screen * 0.6)))
        layout.addWidget(scroll, 1)
        if left:
            layout.addWidget(label(f"This backup's {fmt.oxford(left)} settings stay in it: "
                                   f"{APP_NAME} has no {fmt.oxford(left)} here.", "Dim",
                                   wrap=True))
        row = QHBoxLayout()
        self.summary = label("", "Muted")
        row.addWidget(self.summary, 1)
        row.addWidget(button("Cancel", on_click=self.reject))
        self.restore = button("Restore", "primary", on_click=self.accept)
        self.restore.setDefault(True)
        row.addWidget(self.restore)
        layout.addLayout(row)
        self._sync()

    def picked(self) -> list[str]:
        return [key for category in self.categories for key in category.picked()]

    def _everything(self) -> None:
        on = len(self.picked()) < sum(len(c.boxes) for c in self.categories)
        for category in self.categories:
            category.set_all(on)

    def _only_changes(self) -> None:
        for category in self.categories:
            for key, box in category.boxes.items():
                box.setChecked(key == LIBRARY or bool(self.offered[key].now))

    def _sync(self) -> None:
        if not hasattr(self, "summary"):
            return
        picked = self.picked()
        total = sum(len(c.boxes) for c in self.categories)
        self.everything.setCheckState(Qt.CheckState.Checked if len(picked) == total else
                                      Qt.CheckState.PartiallyChecked if picked else
                                      Qt.CheckState.Unchecked)
        settings = len([key for key in picked if key != LIBRARY])
        parts = [fmt.plural(settings, "setting")] if settings else []
        if LIBRARY in picked:
            parts.append("the library")
        self.summary.setText(fmt.oxford(parts) if parts else "Nothing picked")
        self.restore.setEnabled(bool(picked))
