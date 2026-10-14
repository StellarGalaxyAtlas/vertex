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
        ("vertex save-clip", "Save a clip", "The whole replay buffer."),
        ("vertex save-clip --last 30", "Save the last 30 seconds",
         "Or 10, 60, 300, 600 or 1800."),
        ("vertex replay toggle", "Start or stop the replay buffer",
         "Also: vertex replay start, vertex replay stop."),
    ]),
    ("Sonar", [
        ("vertex volume game up", "Game volume up",
         "Or down, or a volume: vertex volume game 40. Also chat, media and mic."),
        ("vertex mute mic", "Mute your microphone",
         "Mutes Vertex Mic; again to unmute. Any channel works."),
        ("vertex device next", "Next output device",
         "Down the device manager's list, then round again; Auto goes to Manual. Also: "
         "vertex device previous."),
        ("vertex device next mic", "Next microphone",
         "Down the device manager's list of microphones, then round again; Auto goes to "
         "Manual."),
        ("vertex sonar up", "Turn Sonar on", ""),
        ("vertex sonar down", "Turn Sonar off", "Your previous default devices come back."),
    ]),
    ("Vertex", [
        ("vertex show", "Bring Vertex to the front", "From the tray, or from behind a game."),
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
            "Your desktop can run a command when you press a key, anywhere, in or out of "
            "a game. Add a custom shortcut in its keyboard settings and give it one of "
            "these commands. Vertex has to be running; in the tray is enough.")
        self.sections = [intro]
        for group, commands in COMMANDS:
            section = Section(group)
            for command, title, more in commands:
                section.add(setting_row(title, command_field(command), more))
            self.sections.append(section)
        terminal = Section(
            "In a terminal",
            "The same commands work in a terminal, where they say what happened.")
        for text in ("<code>vertex state</code> says what is running, with every volume and "
                     "device; <code>vertex watch</code> follows changes as they happen.",
                     "<code>vertex doctor</code> checks that everything Vertex needs is "
                     "installed.",
                     "<code>vertex --help</code> lists every command."):
            terminal.add(label(text, "Dim", wrap=True))
        self.sections.append(terminal)
