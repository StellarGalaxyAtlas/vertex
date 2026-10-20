"""The game names the user fixed by renaming a game in the library, each
with a way to stop using it."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from vertex.ui import theme
from vertex.ui.widgets import IconButton, label


class GameNames(QWidget):
    """One row per name: what Vertex reads → the tag it writes, and ✕.
    `removed` carries the name read, once its row is gone."""

    removed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        layout.addLayout(self.rows)
        self.empty = label("None yet. To rename a game, right-click it in the library's "
                           "games menu.", "Muted", wrap=True)
        layout.addWidget(self.empty)
        self._rows: list[QFrame] = []

    def set_names(self, names: dict[str, str]) -> None:
        for row in self._rows:
            row.deleteLater()
        self._rows = []
        for old, new in sorted(names.items(), key=lambda item: item[0].casefold()):
            row = QFrame()
            row.setObjectName("GameNameRow")
            theme.style(row, lambda: (
                f"#GameNameRow {{ background: {theme.CARD_BG}; "
                f"border-radius: {theme.RADIUS_SMALL}px; }}"))
            line = QHBoxLayout(row)
            line.setContentsMargins(12, 6, 6, 6)
            line.setSpacing(10)
            for text, kind in ((old, ""), ("→", "Muted"), (new, "")):
                part = label(text, kind)
                if not kind:
                    part.setStyleSheet("font-weight: 600;")
                line.addWidget(part)
            line.addStretch(1)
            remove = IconButton("close", f"Stop tagging {old} as {new}", 12, "TEXT_MUTED")
            remove.clicked.connect(lambda _c=False, name=old: self.removed.emit(name))
            line.addWidget(remove)
            self.rows.addWidget(row)
            self._rows.append(row)
        self.empty.setVisible(not self._rows)
