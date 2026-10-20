"""Settings › Shortcuts: global hotkeys for Vertex's actions, set by pressing
them, and the `vertex` commands for other software and scripts."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from vertex import hotkeys, logs, platform
from vertex.control import SAVE_LENGTHS
from vertex.hotkeys import Hotkey
from vertex.ui import theme
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
    ("Vertex", [
        ("vertex show", "Show Vertex", ""),
    ]),
)

LENGTH_LABELS = {10: "10 seconds", 30: "30 seconds", 60: "1 minute", 300: "5 minutes",
                 600: "10 minutes", 1800: "30 minutes"}

_MODIFIER_KEYS = {Qt.Key.Key_Control: "Ctrl", Qt.Key.Key_Alt: "Alt", Qt.Key.Key_AltGr: "Alt",
                  Qt.Key.Key_Shift: "Shift", Qt.Key.Key_Meta: "Win", Qt.Key.Key_Super_L: "Win",
                  Qt.Key.Key_Super_R: "Win"}
_MODIFIER_FLAGS = ((Qt.KeyboardModifier.ControlModifier, "Ctrl"),
                   (Qt.KeyboardModifier.AltModifier, "Alt"),
                   (Qt.KeyboardModifier.ShiftModifier, "Shift"),
                   (Qt.KeyboardModifier.MetaModifier, "Win"))
_NAMED_KEYS = {
    Qt.Key.Key_Space: "Space", Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter",
    Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backspace: "Backspace", Qt.Key.Key_Insert: "Insert",
    Qt.Key.Key_Delete: "Delete", Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End",
    Qt.Key.Key_PageUp: "Page Up", Qt.Key.Key_PageDown: "Page Down", Qt.Key.Key_Left: "Left",
    Qt.Key.Key_Up: "Up", Qt.Key.Key_Right: "Right", Qt.Key.Key_Down: "Down",
    Qt.Key.Key_Pause: "Pause", Qt.Key.Key_ScrollLock: "Scroll Lock",
    Qt.Key.Key_Print: "Print Screen", Qt.Key.Key_MediaTogglePlayPause: "Play/Pause",
    Qt.Key.Key_MediaPlay: "Play/Pause", Qt.Key.Key_MediaNext: "Next Track",
    Qt.Key.Key_MediaPrevious: "Previous Track", Qt.Key.Key_MediaStop: "Stop",
    Qt.Key.Key_VolumeMute: "Mute", Qt.Key.Key_VolumeDown: "Volume Down",
    Qt.Key.Key_VolumeUp: "Volume Up",
}
_KEYPAD = {Qt.Key.Key_Asterisk: "Num *", Qt.Key.Key_Plus: "Num +", Qt.Key.Key_Minus: "Num -",
           Qt.Key.Key_Period: "Num .", Qt.Key.Key_Slash: "Num /"}


def key_name(event) -> str:
    """The name in hotkeys.KEYS of the key an event is for; "" for one a
    hotkey can't use. On Windows the key's own code says, whatever the
    keyboard layout and whatever Shift does to it."""
    native = platform.key_name(event.nativeVirtualKey())
    if native:
        return native
    key = Qt.Key(event.key())
    keypad = bool(event.modifiers() & Qt.KeyboardModifier.KeypadModifier)
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return chr(key)
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return f"Num {chr(key)}" if keypad else chr(key)
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return f"F{key - Qt.Key.Key_F1 + 1}"
    if keypad and key in _KEYPAD:
        return _KEYPAD[key]
    return _NAMED_KEYS.get(key, "")


class KeyCaps(QWidget):
    """Keys drawn as keycaps with a + between them: Ctrl + Alt + F9."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(5)
        self.parts: tuple[str, ...] = ()

    def show_keys(self, parts, open_end: bool = False, empty: str = "") -> None:
        """`open_end` leaves a + after the last key, for one still to come."""
        self.parts = tuple(parts)
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not parts:
            self.row.addWidget(label(empty, "Dim"))
        for index, part in enumerate(parts):
            if index:
                self.row.addWidget(label("+", "Dim"))
            cap = QLabel(part)
            cap.setObjectName("KeyCap")
            theme.style(cap, lambda: f"QLabel#KeyCap {{ background: {theme.CONTROL_BG}; "
                                     f"color: {theme.TEXT}; border: 1px solid {theme.SEAM}; "
                                     f"border-bottom-width: 3px; border-radius: 6px; "
                                     f"padding: 0 7px; }}")
            self.row.addWidget(cap)
        if parts and open_end:
            self.row.addWidget(label("+", "Dim"))
        self.row.addStretch(1)


class KeyRecorder(QFrame):
    """A hotkey's field. Click it and it listens: the keys held show as they
    are pressed, the first key that isn't a modifier ends it, Esc or a click
    elsewhere leaves the old keys."""

    chosen = Signal(object)         # a Hotkey
    recording = Signal(bool)
    refused = Signal(str)           # why the keys pressed can't be a hotkey

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hotkey: Hotkey | None = None
        self.listening = False
        self.warn = False
        self._held: list[str] = []
        self.setObjectName("KeyRecorder")
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(240)
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        self.caps = KeyCaps()
        layout.addWidget(self.caps)
        theme.style(self, self._style)
        self._show()

    def set_hotkey(self, hotkey: Hotkey | None, warn: bool = False) -> None:
        self.hotkey, self.warn = hotkey, warn
        self._show()

    def _style(self) -> str:
        if self.listening:
            edge = f"2px solid {theme.ACCENT}"
        elif self.warn:
            edge = f"1px solid {theme.WARN}"
        else:
            edge = f"1px {'solid' if self.hotkey else 'dashed'} {theme.LINE}"
        return (f"QFrame#KeyRecorder {{ background: {theme.FIELD_BG}; border: {edge}; "
                f"border-radius: 8px; }}")

    def _show(self) -> None:
        if self.listening:
            self.caps.show_keys(self._held, open_end=True, empty="Press keys…")
        else:
            self.caps.show_keys(self.hotkey.parts if self.hotkey else (), empty="Click to set")
        self.setStyleSheet(self._style())

    # --- Listening ---------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if not self.listening:
            self.listen()
        event.accept()

    def listen(self) -> None:
        self.listening = True
        self._held = []
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.grabKeyboard()
        self.recording.emit(True)
        self._show()

    def stop(self) -> None:
        if not self.listening:
            return
        self.listening = False
        self.releaseKeyboard()
        self.recording.emit(False)
        self._show()

    def event(self, event) -> bool:
        # Tab would otherwise move the focus rather than be a key to record.
        if self.listening and event.type() == QEvent.Type.KeyPress:
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if not self.listening:
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key.Key_Escape and not event.modifiers():
            self.stop()
            return
        if key in _MODIFIER_KEYS:
            self._hold(_MODIFIER_KEYS[key])
            return
        if event.isAutoRepeat():
            return
        modifiers = [name for flag, name in _MODIFIER_FLAGS if event.modifiers() & flag]
        name = key_name(event)
        if not name:
            self.refused.emit("Vertex can't use that key in a hotkey. Try a letter, a digit "
                              "or an F-key.")
            return
        hotkey = Hotkey.of(modifiers, name)
        if hotkey.problem():
            self.refused.emit(hotkey.problem())
            return
        self.hotkey = hotkey
        self.stop()
        self.chosen.emit(hotkey)

    def keyReleaseEvent(self, event) -> None:
        if not self.listening:
            return super().keyReleaseEvent(event)
        if event.key() in _MODIFIER_KEYS and _MODIFIER_KEYS[event.key()] in self._held:
            self._held.remove(_MODIFIER_KEYS[event.key()])
            self._show()

    def _hold(self, modifier: str) -> None:
        if modifier not in self._held:
            self._held = [m for m in hotkeys.MODIFIERS if m in {*self._held, modifier}]
            self._show()

    def focusOutEvent(self, event) -> None:
        self.stop()
        super().focusOutEvent(event)


class HotkeyRow(QWidget):
    """One action: its name, its keys, a ✕ that clears them, and a line
    under them when something needs saying."""

    def __init__(self, action: hotkeys.Action, parent=None):
        super().__init__(parent)
        self.action = action
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QHBoxLayout()
        title.setSpacing(8)
        title.addWidget(label(action.title))
        self.length: QComboBox | None = None
        if action.id == "save_last":
            self.length = QComboBox()
            for seconds in SAVE_LENGTHS:
                self.length.addItem(LENGTH_LABELS.get(seconds, f"{seconds} seconds"), seconds)
            title.addWidget(self.length)
        title.addStretch(1)
        text.addLayout(title)
        if action.more:
            text.addWidget(label(action.more, "Dim", wrap=True))
        row.addLayout(text, 1)
        self.recorder = KeyRecorder()
        row.addWidget(self.recorder, 0, Qt.AlignmentFlag.AlignVCenter)
        self.clear = button("", "ghost", icon="close", tooltip="Clear this hotkey")
        self.clear.setFixedWidth(36)
        # Keeps its place while hidden, so the fields stay in line.
        policy = self.clear.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.clear.setSizePolicy(policy)
        row.addWidget(self.clear, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(row)
        self.note = label("", wrap=True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.note.setTextFormat(Qt.TextFormat.RichText)
        self.note.hide()
        self.said = ""       # what the note is about: hint, refused, moved, taken or held
        outer.addWidget(self.note)
        self.recorder.recording.connect(self._recording)

    def say(self, about: str = "", text: str = "", colour: str = "TEXT_DIM") -> None:
        self.said = about if text else ""
        self.note.setText(text)
        self.note.setVisible(bool(text))
        theme.style(self.note, lambda: f"color: {theme.colour(colour)};")

    def _recording(self, on: bool) -> None:
        if on:
            self.say("hint", "Hold Ctrl, Alt, Shift or Win and press a key · Esc cancels")
        elif self.said == "hint":
            self.say()


def _keys(hotkey: Hotkey) -> str:
    return " + ".join(hotkey.parts)


class HotkeysPage:
    """The hotkeys' section. A change is saved at once, and Windows then says
    whether another program already has the keys."""

    def __init__(self, context):
        self.context = context
        self.rows: dict[str, HotkeyRow] = {}
        self._undo: tuple[dict, str] | None = None   # the hotkeys before a move, and the row
        self._waiting: dict[str, Hotkey | None] = {}  # action just set → the keys it had
        self.section = Section("Hotkeys", "Hotkeys work everywhere, in games too, while "
                                          "Vertex is running.")
        for action in hotkeys.ACTIONS:
            row = HotkeyRow(action)
            row.recorder.chosen.connect(lambda hk, a=action.id: self._chosen(a, hk))
            row.recorder.refused.connect(lambda text, r=row: r.say("refused", text, "WARN"))
            row.recorder.recording.connect(context.hotkeys.pause)
            row.clear.clicked.connect(lambda _c=False, a=action.id: self._clear(a))
            row.note.linkActivated.connect(lambda _link: self._undo_move())
            if row.length is not None:
                row.length.activated.connect(lambda _i, r=row: self._length_chosen(r))
            self.rows[action.id] = row
            self.section.add(row)
        context.hotkeys.checked.connect(self._checked)
        self.load()

    def load(self) -> None:
        config = self.context.config
        bound = self._bound()
        failed = self.context.hotkeys.failed
        for action, row in self.rows.items():
            row.recorder.set_hotkey(bound.get(action), warn=action in failed)
            row.clear.setVisible(action in bound)
            if row.length is not None:
                row.length.setCurrentIndex(max(0, row.length.findData(
                    config.hotkey_last_seconds)))

    # --- Changes -------------------------------------------------------------------

    def _bound(self) -> dict[str, Hotkey]:
        return hotkeys.bindings(self.context.config.hotkeys)

    def _save(self, bound: dict[str, Hotkey]) -> None:
        before = self._bound()
        for action in self.rows:
            if before.get(action) != bound.get(action):
                logs.APP.info("Hotkey for %s: %s", hotkeys.BY_ID[action].title,
                              bound[action].text if action in bound else "none")
        self.context.config.hotkeys = {action: hk.text for action, hk in bound.items()}
        self.context.save_config()
        self.load()

    def _chosen(self, action: str, hotkey: Hotkey) -> None:
        bound = self._bound()
        for row in self.rows.values():
            if row.said in ("refused", "moved", "taken"):
                row.say()
        if bound.get(action) == hotkey:
            self.load()
            return
        self._waiting[action] = bound.get(action)
        taken = next((other for other, hk in bound.items() if hk == hotkey), None)
        self._undo = (dict(bound), action) if taken is not None else None
        if taken is not None:
            del bound[taken]
        bound[action] = hotkey
        self._save(bound)
        if taken is not None:
            self.rows[action].say(
                "moved", f"Taken from “{hotkeys.BY_ID[taken].title}”, which now has none. "
                         f"<a href='undo' style='color: {theme.SELECT};'>Undo</a>")

    def _clear(self, action: str) -> None:
        bound = self._bound()
        if action in bound:
            del bound[action]
            self._waiting.pop(action, None)
            self.rows[action].say()
            self._save(bound)

    def _undo_move(self) -> None:
        if self._undo is not None:
            bound, action = self._undo
            self._undo = None
            self._waiting.pop(action, None)
            self.rows[action].say()
            self._save(bound)

    def _length_chosen(self, row: HotkeyRow) -> None:
        seconds = row.length.currentData()
        if seconds != self.context.config.hotkey_last_seconds:
            logs.APP.info("Hotkey saves the last %s seconds", seconds)
            self.context.config.hotkey_last_seconds = seconds
            self.context.save_config()

    def _checked(self) -> None:
        """Keys just set that another program holds go back to what the action
        had; keys set before stay, and say they do nothing for now."""
        failed = self.context.hotkeys.failed
        waiting, self._waiting = self._waiting, {}
        bound = self._bound()
        refused = {action: bound[action] for action in waiting
                   if action in failed and action in bound}
        if refused:
            for action in refused:
                if waiting[action] is not None:
                    bound[action] = waiting[action]
                else:
                    del bound[action]
            self._save(bound)
            for action, taken in refused.items():
                kept = "Your old keys are kept." if waiting[action] else "Pick other keys."
                self.rows[action].say("taken", f"Another program already uses "
                                               f"{_keys(taken)}. {kept}", "WARN")
            return
        self.load()
        for action, row in self.rows.items():
            if action in failed and action in bound:
                row.say("held", f"Another program already uses {_keys(bound[action])}, so "
                                f"it does nothing for now. Pick other keys.", "WARN")
            elif row.said == "held":
                row.say()


# --- Commands, for other software ------------------------------------------------------

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


def _command_rows(add, group: str | None = None) -> None:
    for name, commands in COMMANDS:
        if group is None or name == group:
            for command, title, more in commands:
                add(setting_row(title, command_field(command), more))


def _terminal() -> Section:
    terminal = Section("In a terminal")
    for text in ("<code>vertex state</code> says what is running; "
                 "<code>vertex watch</code> follows changes as they happen.",
                 "<code>vertex doctor</code> checks that everything Vertex needs is "
                 "installed.",
                 "<code>vertex --help</code> lists every command."):
        terminal.add(label(text, "Dim", wrap=True))
    return terminal


class ShortcutsPage:
    def __init__(self, context):
        # The first entry is the page's top row.
        self.hotkeys: HotkeysPage | None = None
        if hotkeys.AVAILABLE:
            self.hotkeys = HotkeysPage(context)
            other = Section("From other software",
                            "For mouse or keyboard software, a Stream Deck or a script: the "
                            "same actions as commands.")
            commands = QWidget()
            commands_layout = QVBoxLayout(commands)
            commands_layout.setContentsMargins(0, 0, 0, 0)
            commands_layout.setSpacing(12)
            _command_rows(commands_layout.addWidget)
            commands.hide()
            toggle = button("Show the commands", icon="chevron-right")

            def flip():
                commands.setVisible(not commands.isVisible())
                toggle.setText("Hide the commands" if commands.isVisible() else
                               "Show the commands")
            toggle.clicked.connect(flip)
            top = QHBoxLayout()
            top.addWidget(toggle)
            top.addStretch(1)
            other.body.addLayout(top)
            other.add(commands)
            self.commands = commands
            # Side by side on a wide page: the hotkeys, and what else there is.
            side = QWidget()
            side_layout = QVBoxLayout(side)
            side_layout.setContentsMargins(0, 0, 0, 0)
            side_layout.setSpacing(16)
            side_layout.addWidget(other)
            side_layout.addWidget(_terminal())
            self.sections = [(self.hotkeys.section, side)]
            return
        intro = Section(
            "Keyboard shortcuts",
            "Add these commands as custom shortcuts in your desktop's keyboard settings. "
            "They work in games too, while Vertex is running.")
        self.sections = [intro]
        for group, _commands in COMMANDS:
            section = Section(group)
            _command_rows(section.add, group)
            self.sections.append(section)
        self.sections.append(_terminal())
