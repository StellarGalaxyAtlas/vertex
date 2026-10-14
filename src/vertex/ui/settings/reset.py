"""Settings › Reset and delete: settings, the library and the cache back to how
a fresh install has them. Never the clips. What is lost is spelled out, and
the two that lose your own work only go ahead once a word is typed."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QVBoxLayout

from vertex.core import storage
from vertex.ui import theme
from vertex.ui.widgets import ChoiceDialog, Section, TextDialog, button, label


class TypeToConfirm(TextDialog):
    """A red warning that lists what goes and what stays, and only lets the
    action through once `word` has been typed."""

    def __init__(self, parent, title: str, message: str, goes: list[str], stays: str,
                 word: str, action: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(500)
        self.word = word
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        heading = label(message, "Subheading", wrap=True)
        theme.style(heading, lambda: f"color: {theme.DANGER};")
        layout.addWidget(heading)
        layout.addWidget(label("This can't be undone:", "Muted"))
        for line in goes:
            layout.addWidget(label(f"•  {line}", wrap=True))
        layout.addWidget(label(stays, "Muted", wrap=True))
        layout.addSpacing(6)
        layout.addWidget(label(f"Type {word} to confirm.", "Muted"))
        self.field = QLineEdit()
        self.field.setPlaceholderText(word)
        self.field.textChanged.connect(self._typed)
        layout.addWidget(self.field)
        layout.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel", on_click=self.reject)
        cancel.setDefault(True)
        row.addWidget(cancel)
        self.confirm = button(action, "danger", on_click=self.accept)
        self.confirm.setAutoDefault(False)
        self.confirm.setEnabled(False)
        row.addWidget(self.confirm)
        layout.addLayout(row)
        self.field.setFocus(Qt.FocusReason.OtherFocusReason)

    def _typed(self, text: str) -> None:
        self.confirm.setEnabled(text.strip() == self.word)

    @classmethod
    def ask(cls, parent, *args) -> bool:
        return cls(parent, *args).exec() == QDialog.DialogCode.Accepted


def _kept_where() -> str:
    return ("It's moved to the Trash." if storage.trash_available() else
            "A .bak backup is kept.")


class ResetPage(QObject):
    """The tab's sections; each button asks first, then emits what to reset."""

    reset_requested = Signal(str)        # "settings" | "library" | "cache"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_widget = parent
        settings = Section("Reset settings",
                           "Restore defaults and run setup again")
        settings.add(button("Reset settings…", "danger", on_click=self._settings))
        library = Section("Reset the library",
                          "Clear titles, tags, favorites and edits. Video files are kept")
        library.add(button("Reset the library…", "danger", on_click=self._library))
        cache = Section("Clear the cache",
                        "Delete thumbnails and previews")
        cache.add(button("Clear the cache…", on_click=self._cache))
        self.sections = [settings, library, cache]

    def _settings(self) -> None:
        if TypeToConfirm.ask(
                self.parent_widget, "Reset settings", "Reset every setting?",
                ["All settings, including Sonar's devices and volumes"],
                f"Clips and the library are kept. {_kept_where()}",
                "RESET", "Reset settings"):
            self.reset_requested.emit("settings")

    def _library(self) -> None:
        if TypeToConfirm.ask(
                self.parent_widget, "Reset the library", "Reset the library?",
                ["Titles, tags and favorites", "Trims and track volumes"],
                f"Video files are kept. {_kept_where()}",
                "DELETE", "Reset the library"):
            self.reset_requested.emit("library")

    def _cache(self) -> None:
        if ChoiceDialog.ask(self.parent_widget, "Clear the cache", "Clear the cache?",
                            "They're rebuilt as you browse.",
                            [("Clear the cache", "clear", "danger")]) == "clear":
            self.reset_requested.emit("cache")
