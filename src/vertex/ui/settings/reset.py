"""Settings › Reset and delete: settings, the library and the cache back to how
a fresh install has them. Never the clips. What is lost is spelled out, and
the two that lose your own work only go ahead once a word is typed."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from vertex import platform
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


def _warning(text: str) -> QFrame:
    """A bold amber box that stops you before a step you probably don't need."""
    box = QFrame()
    box.setObjectName("ResetWarning")
    theme.style(box, lambda: f"#ResetWarning {{ border: 2px solid {theme.WARN}; "
                             f"border-radius: {theme.RADIUS_CONTROL}px; }}")
    layout = QHBoxLayout(box)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(12)
    sign = label("⚠")
    theme.style(sign, lambda: f"color: {theme.WARN}; font-size: 22px;")
    layout.addWidget(sign, 0, Qt.AlignmentFlag.AlignVCenter)
    words = label(text, wrap=True)
    theme.style(words, lambda: f"color: {theme.WARN}; font-weight: bold;")
    layout.addWidget(words, 1)
    return box


def _titled(title: str, blurb: str, control: QWidget) -> QWidget:
    """A title, a sentence and a full-width button, like a Section of its own,
    so two of them can share one card."""
    block = QWidget()
    layout = QVBoxLayout(block)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    layout.addWidget(label(title, "Subheading"))
    layout.addWidget(label(blurb, "Muted", wrap=True))
    layout.addWidget(control)
    return block


def _kept_where() -> str:
    return ("It's moved to the Trash." if storage.trash_available() else
            "A .bak backup is kept.")


class ResetPage(QObject):
    """The tab's sections; each button asks first, then emits what to reset."""

    reset_requested = Signal(str)        # "settings" | "library" | "cache"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_widget = parent
        basics = Section()
        basics.body.setSpacing(24)
        basics.add(_titled("Reset settings", "Restore defaults and run setup again",
                           button("Reset settings…", "danger", on_click=self._settings)))
        basics.add(_titled("Clear cache", "Delete thumbnails and previews",
                           button("Clear cache…", on_click=self._cache)))
        library = Section()
        library.add(_warning(
            "Only do this if something's wrong and clearing the cache didn't fix it."))
        library.add(_titled("Reset library",
                            "Clear titles, tags, favorites and edits. Video files are kept",
                            button("Reset library…", "danger", on_click=self._library)))
        self.sections = [basics, library]

    def _settings(self) -> None:
        if TypeToConfirm.ask(
                self.parent_widget, "Reset settings", "Reset every setting?",
                ["All settings, including the recorder's and Sonar's devices and volumes"
                 if platform.SONAR else "All settings, including the recorder's"],
                f"Clips and the library are kept. {_kept_where()}",
                "RESET", "Reset settings"):
            self.reset_requested.emit("settings")

    def _library(self) -> None:
        if TypeToConfirm.ask(
                self.parent_widget, "Reset library", "Reset the library?",
                ["Titles, tags and favorites", "Trims and track volumes"],
                f"Video files are kept. {_kept_where()}",
                "DELETE", "Reset library"):
            self.reset_requested.emit("library")

    def _cache(self) -> None:
        if ChoiceDialog.ask(self.parent_widget, "Clear cache", "Clear the cache?",
                            "They're rebuilt as you browse.",
                            [("Clear cache", "clear", "danger")]) == "clear":
            self.reset_requested.emit("cache")
