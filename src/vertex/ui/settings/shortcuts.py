"""Settings › Shortcuts: the `vertex` commands worth binding to a key, ready
to copy, and how to use them from a terminal."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from vertex.ui.widgets import Section, button, label, setting_row

# (group, [(command, what it does, more)]). Every command must parse with the
# `vertex` command's own parser; a test checks.
COMMANDS = (
    ("Clips", [
        ("vertex save-clip", "Save a clip", ""),
        ("vertex save-clip --last 30", "Save the last 30 seconds",
         "Or 10, 60, 300, 600 or 1800"),
        ("vertex replay toggle", "Start or stop the replay buffer",
         "Also: vertex replay start, vertex replay stop."),
    ]),
    ("Sonar", [
        ("vertex volume game up", "Game volume up",
         "Also down, or a level like 40. Works for chat, media and mic"),
        ("vertex mute mic", "Mute microphone", "Press again to unmute"),
        ("vertex device next", "Next output device",
         "In list order, until a device is plugged in. Also: vertex device previous."),
        ("vertex device next mic", "Next microphone",
         "In list order, until a mic is plugged in."),
        ("vertex sonar up", "Turn Sonar on", ""),
        ("vertex sonar down", "Turn Sonar off", "Restores your default devices"),
    ]),
    ("Vertex", [
        ("vertex show", "Show Vertex", ""),
    ]),
)


def command_field(command: str) -> QWidget:
    """A command in a read-only field, with a button that copies it."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    field = QLineEdit(command)
    field.setReadOnly(True)
    field.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    field.setMinimumWidth(260)
    row.addWidget(field, 1)
    copy = button("Copy")

    def copied():
        QGuiApplication.clipboard().setText(command)
        copy.setText("Copied")
        QTimer.singleShot(1500, lambda: copy.setText("Copy"))
    copy.clicked.connect(copied)
    row.addWidget(copy)
    return box


class ShortcutsPage:
    def __init__(self):
        intro = Section(
            "Keyboard shortcuts",
            "Add these commands as custom shortcuts in your desktop's keyboard settings. "
            "They work in games too, while Vertex is running.")
        self.sections = [intro]
        for group, commands in COMMANDS:
            section = Section(group)
            for command, title, more in commands:
                section.add(setting_row(title, command_field(command), more))
            self.sections.append(section)
        terminal = Section("In a terminal")
        for text in ("<code>vertex state</code> says what is running, with every volume and "
                     "device; <code>vertex watch</code> follows changes as they happen.",
                     "<code>vertex doctor</code> checks that everything Vertex needs is "
                     "installed.",
                     "<code>vertex --help</code> lists every command."):
            terminal.add(label(text, "Dim", wrap=True))
        self.sections.append(terminal)
