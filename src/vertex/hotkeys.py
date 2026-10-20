"""Global hotkeys: keys that run a Vertex action from anywhere, games too.

A hotkey is kept in the settings as text, modifiers first in a fixed order:

    Ctrl+Alt+F9        Win+Shift+Num 5        F13

The system holds them for Vertex (`listener`): Windows does, through
RegisterHotKey (see platform.windows); elsewhere there are none, and
`AVAILABLE` says so.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vertex import platform

AVAILABLE = platform.HOTKEYS

MODIFIERS = ("Win", "Ctrl", "Alt", "Shift")     # in the order Windows writes them

# The keys a hotkey can end on, by name, with their Windows virtual-key code.
KEYS: dict[str, int] = {
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    **{str(digit): 0x30 + digit for digit in range(10)},
    **{f"F{n}": 0x6F + n for n in range(1, 25)},
    **{f"Num {digit}": 0x60 + digit for digit in range(10)},
    "Num *": 0x6A, "Num +": 0x6B, "Num -": 0x6D, "Num .": 0x6E, "Num /": 0x6F,
    "Space": 0x20, "Enter": 0x0D, "Tab": 0x09, "Backspace": 0x08,
    "Insert": 0x2D, "Delete": 0x2E, "Home": 0x24, "End": 0x23,
    "Page Up": 0x21, "Page Down": 0x22,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
    "Pause": 0x13, "Scroll Lock": 0x91, "Print Screen": 0x2C,
    "Play/Pause": 0xB3, "Next Track": 0xB0, "Previous Track": 0xB1, "Stop": 0xB2,
    "Mute": 0xAD, "Volume Down": 0xAE, "Volume Up": 0xAF,
}

# Keys that type nothing and move nothing, so they can be a hotkey alone
# (F13-F24 are what macro keys send).
_ALONE = {*(f"F{n}" for n in range(1, 25)), "Pause", "Scroll Lock", "Print Screen",
          "Play/Pause", "Next Track", "Previous Track", "Stop", "Mute", "Volume Down",
          "Volume Up"}


@dataclass(frozen=True)
class Hotkey:
    modifiers: tuple[str, ...]      # some of MODIFIERS, in their order
    key: str                        # a name in KEYS

    @classmethod
    def of(cls, modifiers, key: str) -> Hotkey:
        held = set(modifiers)
        return cls(tuple(m for m in MODIFIERS if m in held), key)

    @property
    def text(self) -> str:
        return "+".join((*self.modifiers, self.key))

    @property
    def parts(self) -> tuple[str, ...]:
        return (*self.modifiers, self.key)

    def problem(self) -> str:
        """Why these keys can't be a hotkey, or "" if they can."""
        if self.key in _ALONE or set(self.modifiers) & {"Ctrl", "Alt", "Win"}:
            return ""
        keys = " + ".join(self.parts)
        return f"{keys} alone would stop it typing anywhere else. Add Ctrl, Alt or Win."


def parse(text: str) -> Hotkey | None:
    """The hotkey written as `text`, or None if it isn't one."""
    if not isinstance(text, str):
        return None
    modifiers, key = [], text
    while "+" in key and key.split("+", 1)[0] in MODIFIERS:
        modifier, key = key.split("+", 1)
        if modifier in modifiers:
            return None
        modifiers.append(modifier)
    if key not in KEYS:
        return None
    hotkey = Hotkey.of(modifiers, key)
    return hotkey if not hotkey.problem() else None


# --- The actions -------------------------------------------------------------------

@dataclass(frozen=True)
class Action:
    id: str
    title: str
    more: str = ""


ACTIONS = (
    Action("save_clip", "Save a clip", "As much as the replay buffer keeps"),
    Action("save_last", "Save the last", "A shorter clip from the same buffer"),
    Action("replay", "Start or stop the replay buffer"),
    Action("show", "Show Vertex"),
)
BY_ID = {action.id: action for action in ACTIONS}


def bindings(stored: dict) -> dict[str, Hotkey]:
    """The hotkeys in the settings, by action; what can't be read is left out."""
    found = {}
    for action, text in (stored or {}).items():
        hotkey = parse(text) if action in BY_ID else None
        if hotkey is not None and hotkey not in found.values():
            found[action] = hotkey
    return found


def listener(on_press: Callable[[str], None], on_result: Callable[[set[str]], None]):
    """Something that holds the hotkeys with the system: `set(bindings)`
    holds exactly those from then on, `close()` lets them go.
    `on_press(action)` is called when one is pressed, and `on_result(failed)`
    with the actions whose keys another program already holds after each
    `set`, both from a thread of the listener's. Holds nothing where hotkeys
    aren't AVAILABLE."""
    return platform.HotkeyListener(on_press, on_result)
