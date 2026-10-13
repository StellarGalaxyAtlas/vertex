"""Tag a clip: one game, any number of people, both suggested from the library."""

from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import (
    QCompleter,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from vertex.core.naming import clean_tag, clean_tags, game_key
from vertex.ui import theme
from vertex.ui.widgets import FlowLayout, IconButton, button, label


def _completer(words: list[str], parent) -> QCompleter:
    completer = QCompleter(QStringListModel(words), parent)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.popup().setStyleSheet(
        f"background: {theme.CARD_BG}; border: 1px solid {theme.SEAM}; padding: 4px;")
    return completer


class Chip(QFrame):
    def __init__(self, text: str, on_remove, parent=None):
        super().__init__(parent)
        self.text = text
        self.setStyleSheet(f"background: {theme.CARD_BG}; border-radius: 8px;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 3, 3)
        layout.setSpacing(2)
        layout.addWidget(QLabel(text))
        remove = IconButton("close", f"Remove {text}", 12, theme.TEXT_MUTED)
        remove.clicked.connect(lambda: on_remove(self))
        layout.addWidget(remove)


class TagDialog(QDialog):
    def __init__(self, parent, clip_title: str, game: str = "", people=(),
                 games=(), people_pool=()):
        super().__init__(parent)
        self.setWindowTitle("Tag clip")
        self.setMinimumWidth(480)
        self.result_tags: tuple[str, list[str]] | None = None
        self._known_games = list(games)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(label("Tag clip", "Subheading"))
        layout.addWidget(label(clip_title, "Muted"))
        layout.addSpacing(6)

        layout.addWidget(label("GAME", "Group"))
        self.game = QLineEdit(game)
        self.game.setPlaceholderText("What was being played")
        self.game.setCompleter(_completer(self._known_games, self))
        layout.addWidget(self.game)
        self.game_hint = label("", "Dim")
        layout.addWidget(self.game_hint)
        self.game.textChanged.connect(self._hint_spelling)

        layout.addSpacing(6)
        layout.addWidget(label("PEOPLE", "Group"))
        self.chips_host = QWidget()
        self.chips = FlowLayout(self.chips_host)
        layout.addWidget(self.chips_host)
        self.person = QLineEdit()
        self.person.setPlaceholderText("Add a person and press Enter")
        self.person.setCompleter(_completer(list(people_pool), self))
        self.person.returnPressed.connect(self._add_typed)
        layout.addWidget(self.person)
        for name in people:
            self._add_chip(name)

        layout.addSpacing(10)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", on_click=self.reject))
        save = button("Save", "primary", on_click=self._save)
        save.setAutoDefault(False)
        row.addWidget(save)
        layout.addLayout(row)
        self.game.setFocus()

    def _hint_spelling(self, text: str) -> None:
        """Point out when a typed game is an existing tag spelled differently."""
        key = game_key(text)
        match = next((g for g in self._known_games if game_key(g) == key and g != text), "")
        self.game_hint.setText(f"Saved as “{match}”, the spelling already in use." if
                               key and match else "")

    def _people(self) -> list[str]:
        return [self.chips.itemAt(i).widget().text for i in range(self.chips.count())]

    def _add_chip(self, name: str) -> None:
        name = clean_tag(name)
        if not name or name.casefold() in (p.casefold() for p in self._people()):
            return
        self.chips.addWidget(Chip(name, self._remove_chip))
        self.chips_host.updateGeometry()

    def _remove_chip(self, chip: Chip) -> None:
        self.chips.removeWidget(chip)
        chip.deleteLater()
        self.chips_host.updateGeometry()

    def _add_typed(self) -> None:
        self._add_chip(self.person.text())
        self.person.clear()

    def keyPressEvent(self, event):
        # Enter in the people field adds a chip rather than closing the dialog.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.person.hasFocus():
            return
        super().keyPressEvent(event)

    def _save(self) -> None:
        if self.person.text().strip():
            self._add_typed()
        game = clean_tag(self.game.text())
        key = game_key(game)
        game = next((g for g in self._known_games if key and game_key(g) == key), game)
        self.result_tags = (game, clean_tags(self._people()))
        self.accept()

    @classmethod
    def ask(cls, parent, clip_title, game, people, games, people_pool):
        dialog = cls(parent, clip_title, game, people, games, people_pool)
        dialog.exec()
        return dialog.result_tags
