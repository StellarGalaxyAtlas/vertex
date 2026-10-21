"""The bar that takes the filters' place while clips are picked in the
library: how many, and what can be done to all of them at once."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout

from vertex.ui import icons, theme
from vertex.ui.widgets import IconButton, button, label

# Each action: its key, its words, its icon, its button kind.
ACTIONS = (
    ("favorite", "Favorite", "star-outline", ""),
    ("game", "Set game", "game", ""),
    ("people", "Add people", "people", ""),
    ("export", "Quick export", "export", ""),
    ("folder", "Show in folder", "folder", ""),
    ("delete", "Delete", "trash", "danger"),
)


class SelectionBar(QFrame):
    """`acted` names the action picked; `cleared` lets every clip go. On a
    narrow window the buttons keep only their icons."""

    acted = Signal(str)
    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SelectionBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        theme.style(self, lambda: f"#SelectionBar {{ background: {theme.ACCENT_SOFT}; "
                                  f"border-radius: {theme.RADIUS_CONTROL + 2}px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 4, 6, 4)
        row.setSpacing(8)
        self.count = label("")
        self.count.setStyleSheet("font-weight: 600; background: transparent;")
        row.addWidget(self.count)
        row.addStretch(1)
        self.words = {key: text for key, text, _icon, _kind in ACTIONS}
        self.buttons = {}
        for key, text, icon, kind in ACTIONS:
            action = button(text, kind, icon, on_click=lambda _c=False, k=key: self.acted.emit(k),
                            tooltip=text)
            action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(action)
            self.buttons[key] = action
        row.addSpacing(4)
        clear = IconButton("close", "Clear the selection (Esc)", 16)
        clear.clicked.connect(self.cleared.emit)
        row.addWidget(clear)

    def set_count(self, count: int, all_favorites: bool) -> None:
        self.count.setText(f"{count} selected")
        words = "Unfavorite" if all_favorites else "Favorite"
        self.words["favorite"] = words
        favorite = self.buttons["favorite"]
        favorite.setToolTip(words)
        star = "star" if all_favorites else "star-outline"
        theme.themed(favorite, lambda: favorite.setIcon(icons.icon(star)), "icon")
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        """Words on the buttons while they fit, only icons after."""
        for key, action in self.buttons.items():
            action.setText(self.words[key])
        if self.layout().sizeHint().width() > self.width():
            for action in self.buttons.values():
                action.setText("")

