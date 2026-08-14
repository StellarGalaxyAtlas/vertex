"""Keep Xlib protocol errors from killing the whole application.

libmpv installs its own X error handler while a video output is alive, and
resets it on teardown — which restores Xlib's *default* handler, the one that
prints "X Error of failed request: ..." and then calls exit(). That reset also
throws away the handler Tk installed for itself at interpreter startup.

The next ordinary Tk request against a window that is going away then takes the
process down with it. Tk does an XQueryTree stack-order walk over a toplevel as
it is destroyed; with mpv's reset in place that BadWindow is fatal, so closing
the player killed the main window too.

Call `capture()` once after the Tk root exists to remember Tk's own handler,
then `rearm()` after every mpv teardown. Races against a destroyed window are
swallowed; anything else is handed to Tk's handler as usual.
"""

import ctypes
import ctypes.util

# X protocol error codes that mean "the object went away underneath you".
BAD_WINDOW = 3
BAD_MATCH = 8
BAD_DRAWABLE = 9
_BENIGN = frozenset((BAD_WINDOW, BAD_MATCH, BAD_DRAWABLE))


class _XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("resourceid", ctypes.c_ulong),
        ("serial", ctypes.c_ulong),
        ("error_code", ctypes.c_ubyte),
        ("request_code", ctypes.c_ubyte),
        ("minor_code", ctypes.c_ubyte),
    ]


_HANDLER = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_XErrorEvent)
)

_x11 = None
_tk_handler = None   # Tk's own handler, so non-benign errors keep its behaviour
_installed = None    # our handler; kept alive here or ctypes would free it

swallowed = 0        # count of ignored errors, for debugging


def _load():
    global _x11
    if _x11 is None:
        name = ctypes.util.find_library("X11")
        if not name:
            return None
        try:
            _x11 = ctypes.CDLL(name)
        except OSError:
            return None
        _x11.XSetErrorHandler.restype = ctypes.c_void_p
        _x11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    return _x11


def capture():
    """Remember the handler Tk installed. Call once, after the Tk root exists."""
    global _tk_handler
    x11 = _load()
    if x11 is None:
        return False
    # XSetErrorHandler returns the previous handler, so set-then-restore reads it.
    _tk_handler = x11.XSetErrorHandler(None)
    x11.XSetErrorHandler(_tk_handler)
    return True


def _on_error(display, event):
    global swallowed
    code = event.contents.error_code
    if code in _BENIGN:
        swallowed += 1
        return 0
    if _tk_handler:
        return _HANDLER(_tk_handler)(display, event)
    return 0


def rearm():
    """Reinstall the guard. Call after every mpv teardown."""
    global _installed
    x11 = _load()
    if x11 is None:
        return False
    _installed = _HANDLER(_on_error)
    x11.XSetErrorHandler(ctypes.cast(_installed, ctypes.c_void_p))
    return True
