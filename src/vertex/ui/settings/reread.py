"""What reading the clips' names again would change, under the apps Vertex
reads them with: one line per game, ticked, opening to its clips."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from vertex import fmt
from vertex.core.importing import RereadGroup
from vertex.ui import theme
from vertex.ui.widgets import IconButton, button, label

FILES_SHOWN = 10         # clips listed under an opened line, then "…N more"


def _when(timestamp: float) -> str:
    return f"{fmt.date(timestamp)}, {time.strftime('%H:%M', time.localtime(timestamp))}"


class _Line(QFrame):
    """One group: tick, old game → new game, how many clips, and its clips."""

    def __init__(self, group: RereadGroup, ticked: bool, on_tick, parent=None):
        super().__init__(parent)
        self.group = group
        self.setObjectName("RereadLine")
        theme.style(self, lambda: (f"#RereadLine {{ background: {theme.CARD_BG}; "
                                   f"border-radius: {theme.RADIUS_SMALL}px; }}"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 6, 6)
        outer.setSpacing(4)
        line = QHBoxLayout()
        line.setSpacing(10)
        self.tick = QCheckBox()
        self.tick.setChecked(ticked)
        self.tick.toggled.connect(lambda on: on_tick(self, on))
        line.addWidget(self.tick)
        if group.game:
            was = label(group.game_was or "untagged", "" if group.game_was else "Muted")
            now = label(group.game)
            for part in (was, now):
                if not part.objectName():
                    part.setStyleSheet("font-weight: 600;")
            line.addWidget(was)
            line.addWidget(label("→", "Muted"))
            line.addWidget(now)
            self.tick.setToolTip(f"Tag these clips {group.game}")
        else:
            line.addWidget(label("Dates only"))
        line.addStretch(1)
        count = fmt.plural(len(group.changes), "clip")
        if group.game and group.dates:
            count += " and their dates" if group.dates == len(group.changes) else \
                f", {fmt.plural(group.dates, 'date')}"
        line.addWidget(label(count, "Muted"))
        self.opener = IconButton("chevron-right", "Show the clips", 14, "TEXT_MUTED")
        self.opener.setCheckable(True)
        self.opener.toggled.connect(self._open)
        line.addWidget(self.opener)
        outer.addLayout(line)
        shown = [f"{c.filename} · {_when(c.when)}" if c.when else c.filename
                 for c in group.changes[:FILES_SHOWN]]
        if len(group.changes) > FILES_SHOWN:
            shown.append(f"…{len(group.changes) - FILES_SHOWN} more")
        self.files = label("\n".join(shown), "Muted", wrap=True)
        self.files.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.files.setContentsMargins(26, 0, 0, 4)
        self.files.hide()
        outer.addWidget(self.files)

    def _open(self, opened: bool) -> None:
        self.files.setVisible(opened)
        self.opener.set_icon("chevron-down" if opened else "chevron-right", "TEXT_MUTED")


class RereadList(QWidget):
    """The changes, each group ticked unless the user unticked it (kept while
    Vertex runs, so a list worked out again doesn't tick it back).
    `apply` carries the games and the dates to write, by file name."""

    apply = Signal(dict, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(6)
        self.heading = label("", "Subheading")
        layout.addWidget(self.heading)
        self.hint = label("Games you typed yourself show here too, since Vertex can't tell "
                          "them apart: untick them.", "Dim", wrap=True)
        layout.addWidget(self.hint)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        layout.addLayout(self.rows)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.apply_button = button("", "primary", on_click=self._apply)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)
        self._lines: list[_Line] = []
        self._unticked: set[tuple[str, str]] = set()
        self.set_groups([])

    def set_groups(self, groups: list[RereadGroup]) -> None:
        for line in self._lines:
            line.deleteLater()
        self._lines = []
        for group in groups:
            ticked = (group.game_was, group.game) not in self._unticked
            line = _Line(group, ticked, self._ticked)
            self.rows.addWidget(line)
            self._lines.append(line)
        total = sum(len(group.changes) for group in groups)
        self.heading.setText(f"Reading the names again changes {fmt.plural(total, 'clip')}"
                             if total else "Your tags and dates match what the names say")
        for widget in (self.hint, self.apply_button):
            widget.setVisible(bool(total))
        self._count()

    def _ticked(self, line: _Line, on: bool) -> None:
        key = (line.group.game_was, line.group.game)
        (self._unticked.discard if on else self._unticked.add)(key)
        self._count()

    def _chosen(self) -> list[RereadGroup]:
        return [line.group for line in self._lines if line.tick.isChecked()]

    def _count(self) -> None:
        chosen = sum(len(group.changes) for group in self._chosen())
        self.apply_button.setText(f"Apply {fmt.plural(chosen, 'change')}")
        self.apply_button.setEnabled(bool(chosen))

    def _apply(self) -> None:
        games, dates = {}, {}
        for group in self._chosen():
            for change in group.changes:
                if change.game:
                    games[change.filename] = change.game
                if change.when:
                    dates[change.filename] = change.when
        self.apply.emit(games, dates)
