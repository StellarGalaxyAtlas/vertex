"""The full-screen window in front, asked of the X server, on Linux.

Games mostly run as X11 windows, also on a Wayland desktop (through
XWayland): Proton and Wine games do, and most native ones. The window
manager names the active window on the root window (_NET_ACTIVE_WINDOW),
and the window says whether it is full screen (_NET_WM_STATE), its title
and its program (WM_CLASS). A window of the Wayland desktop itself is no X
window: XWayland then names none active.

This talks to the server with libxcb, through ctypes: no package to
install, and errors come back with the reply instead of ending the process
as Xlib's do.
"""

from __future__ import annotations

import ctypes
import ctypes.util

ATOM, CARDINAL, WINDOW, STRING = 4, 6, 33, 31
ANY = 0


class _ScreenIterator(ctypes.Structure):
    _fields_ = [("data", ctypes.POINTER(ctypes.c_uint32)),     # root is a screen's first field
                ("rem", ctypes.c_int), ("index", ctypes.c_int)]


class _AtomReply(ctypes.Structure):
    _fields_ = [("response_type", ctypes.c_uint8), ("pad0", ctypes.c_uint8),
                ("sequence", ctypes.c_uint16), ("length", ctypes.c_uint32),
                ("atom", ctypes.c_uint32)]


class _Cookie(ctypes.Structure):
    _fields_ = [("sequence", ctypes.c_uint)]


_lib = None


def _xcb():
    """libxcb with the calls used here declared; None where it isn't."""
    global _lib
    if _lib is None:
        name = ctypes.util.find_library("xcb") or "libxcb.so.1"
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            _lib = False
            return None
        lib.xcb_connect.restype = ctypes.c_void_p
        lib.xcb_connect.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        lib.xcb_connection_has_error.argtypes = [ctypes.c_void_p]
        lib.xcb_disconnect.argtypes = [ctypes.c_void_p]
        lib.xcb_get_setup.restype = ctypes.c_void_p
        lib.xcb_get_setup.argtypes = [ctypes.c_void_p]
        lib.xcb_setup_roots_iterator.restype = _ScreenIterator
        lib.xcb_setup_roots_iterator.argtypes = [ctypes.c_void_p]
        lib.xcb_screen_next.argtypes = [ctypes.POINTER(_ScreenIterator)]
        lib.xcb_intern_atom.restype = _Cookie
        lib.xcb_intern_atom.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint16,
                                        ctypes.c_char_p]
        lib.xcb_intern_atom_reply.restype = ctypes.POINTER(_AtomReply)
        lib.xcb_intern_atom_reply.argtypes = [ctypes.c_void_p, _Cookie, ctypes.c_void_p]
        lib.xcb_get_property.restype = _Cookie
        lib.xcb_get_property.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint32,
                                         ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                         ctypes.c_uint32]
        lib.xcb_get_property_reply.restype = ctypes.c_void_p
        lib.xcb_get_property_reply.argtypes = [ctypes.c_void_p, _Cookie, ctypes.c_void_p]
        lib.xcb_get_property_value.restype = ctypes.c_void_p
        lib.xcb_get_property_value.argtypes = [ctypes.c_void_p]
        lib.xcb_get_property_value_length.argtypes = [ctypes.c_void_p]
        _lib = lib
    return _lib or None


_libc = None


def _free(pointer) -> None:
    """Free a reply, as xcb wants."""
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(None)
        _libc.free.argtypes = [ctypes.c_void_p]
    _libc.free(pointer)


class _Connection:
    def __init__(self, lib, display: bytes | None):
        self.lib = lib
        screen = ctypes.c_int(0)
        self.c = lib.xcb_connect(display, ctypes.byref(screen))
        self.root = 0
        if not self.c or lib.xcb_connection_has_error(self.c):
            return
        roots = lib.xcb_setup_roots_iterator(lib.xcb_get_setup(self.c))
        for _ in range(screen.value):
            lib.xcb_screen_next(ctypes.byref(roots))
        if roots.data:
            self.root = roots.data[0]

    def close(self) -> None:
        if self.c:
            self.lib.xcb_disconnect(self.c)

    def atom(self, name: str) -> int:
        raw = name.encode()
        reply = self.lib.xcb_intern_atom_reply(
            self.c, self.lib.xcb_intern_atom(self.c, 0, len(raw), raw), None)
        if not reply:
            return 0
        try:
            return reply.contents.atom
        finally:
            _free(reply)

    def get(self, window: int, prop: int, kind: int = ANY) -> bytes | None:
        """A property's value, as bytes; None if the window lacks it or is gone."""
        reply = self.lib.xcb_get_property_reply(
            self.c, self.lib.xcb_get_property(self.c, 0, window, prop, kind, 0, 4096), None)
        if not reply:
            return None
        try:
            length = self.lib.xcb_get_property_value_length(reply)
            if length <= 0:
                return None
            return ctypes.string_at(self.lib.xcb_get_property_value(reply), length)
        finally:
            _free(reply)

    def numbers(self, window: int, prop: int, kind: int) -> list[int]:
        value = self.get(window, prop, kind) or b""
        return list(memoryview(value[:len(value) // 4 * 4]).cast("I"))


def fullscreen_window(display: str | None = None) -> tuple[str, str, int] | None:
    """(title, program, process id) of the active X window when it is full
    screen; ("", "", 0) when it isn't, or no X window is active. The program
    is its WM_CLASS: "firefox", "mpv", or a Wine game's "eldenring.exe".
    None where no X server can be asked."""
    lib = _xcb()
    if lib is None:
        return None
    connection = _Connection(lib, display.encode() if display else None)
    try:
        if not connection.root:
            return None
        active = connection.numbers(connection.root, connection.atom("_NET_ACTIVE_WINDOW"),
                                    WINDOW)
        if not active or not active[0]:
            return "", "", 0
        window = active[0]
        states = connection.numbers(window, connection.atom("_NET_WM_STATE"), ATOM)
        if connection.atom("_NET_WM_STATE_FULLSCREEN") not in states:
            return "", "", 0
        title = connection.get(window, connection.atom("_NET_WM_NAME")) or \
            connection.get(window, connection.atom("WM_NAME")) or b""
        names = (connection.get(window, connection.atom("WM_CLASS"), STRING) or b"").split(b"\0")
        program = (names[1] if len(names) > 1 and names[1] else names[0]).decode(
            "utf-8", "replace")
        pid = connection.numbers(window, connection.atom("_NET_WM_PID"), CARDINAL)
        return title.decode("utf-8", "replace"), program, pid[0] if pid else 0
    finally:
        connection.close()
