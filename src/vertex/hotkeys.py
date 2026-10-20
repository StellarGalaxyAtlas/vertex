"""Global hotkeys: keys that run a Vertex action from anywhere, games too.

A hotkey is kept in the settings as text, modifiers first in a fixed order:

    Ctrl+Alt+F9        Win+Shift+Num 5        F13

Windows hands the keys to Vertex through RegisterHotKey, on a thread of its
own (`Listener`); elsewhere there are none, and `AVAILABLE` says so.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from vertex import logs, system

AVAILABLE = system.WINDOWS

MODIFIERS = ("Win", "Ctrl", "Alt", "Shift")     # in the order Windows writes them
_MOD_BITS = {"Alt": 0x1, "Ctrl": 0x2, "Shift": 0x4, "Win": 0x8}
_MOD_NOREPEAT = 0x4000      # held down, a hotkey fires once

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
_BY_CODE = {code: name for name, code in KEYS.items()}

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


def key_name(virtual_key: int) -> str:
    """The name of a key from its Windows virtual-key code; "" for one a
    hotkey can't use."""
    return _BY_CODE.get(virtual_key, "")


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


# --- Windows --------------------------------------------------------------------

_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_WM_APP_SET = 0x8000 + 1


class Listener:
    """Holds the hotkeys with Windows and calls `on_press(action)` when one
    is pressed, and `on_result(failed)` with the actions whose keys another
    program already holds after each `set`. Both are called from the
    listener's own thread. Does nothing where hotkeys aren't AVAILABLE."""

    def __init__(self, on_press: Callable[[str], None],
                 on_result: Callable[[set[str]], None]):
        self._on_press = on_press
        self._on_result = on_result
        self._wanted: dict[str, Hotkey] = {}
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread_id = 0
        self._thread: threading.Thread | None = None

    def set(self, wanted: dict[str, Hotkey]) -> None:
        """Hold exactly these hotkeys from now on; {} lets every one go."""
        if not system.WINDOWS:
            return
        with self._lock:
            self._wanted = dict(wanted)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
            self._thread.start()
            self._ready.wait(5)
        self._post(_WM_APP_SET)

    def close(self) -> None:
        if self._thread is not None:
            self._post(_WM_QUIT)
            self._thread.join(2)
            self._thread = None

    def _post(self, message: int) -> None:
        import ctypes

        ctypes.windll.user32.PostThreadMessageW(self._thread_id, message, 0, 0)

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT,
                                          wintypes.UINT)
        user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM,
                                              wintypes.LPARAM)
        message = wintypes.MSG()
        # A thread has a message queue once it asks for a message.
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._ready.set()
        held: dict[int, str] = {}
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == _WM_HOTKEY and message.wParam in held:
                try:
                    self._on_press(held[message.wParam])
                except Exception:       # a hotkey must never end the thread
                    logs.APP.exception("Hotkey %s failed", held[message.wParam])
            elif message.message == _WM_APP_SET:
                for number in held:
                    user32.UnregisterHotKey(None, number)
                held = {}
                with self._lock:
                    wanted = dict(self._wanted)
                failed = set()
                for number, (action, hotkey) in enumerate(wanted.items(), 1):
                    bits = sum(_MOD_BITS[m] for m in hotkey.modifiers) | _MOD_NOREPEAT
                    if user32.RegisterHotKey(None, number, bits, KEYS[hotkey.key]):
                        held[number] = action
                    else:
                        failed.add(action)
                        logs.APP.warning("Another program holds %s", hotkey.text)
                self._on_result(failed)
        for number in held:
            user32.UnregisterHotKey(None, number)
