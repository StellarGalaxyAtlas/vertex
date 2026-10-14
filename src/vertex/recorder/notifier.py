"""GPU Screen Recorder's notifier, `gsr-notify`: the ShadowPlay-style toast
GSR's own overlay shows, drawn above fullscreen games (an override-redirect
window on X11, a layer-shell overlay on Wayland compositors that have one).

Vertex runs it for its pop-ups when it is installed and the setting is on,
the same way GSR's overlay does: one process per notice, the previous one
told to go first so toasts don't stack. It comes with the
gpu-screen-recorder-notification package.
"""

from __future__ import annotations

import shutil
import signal
import subprocess

COMMAND = "gsr-notify"

# The icons it draws itself, by name; any other value is read as an image file.
ICONS = ("record", "replay", "stream", "screenshot")

# Seconds on screen: GSR's overlay uses 3 for everything.
TIMEOUTS = {"info": 3.0, "ok": 3.0, "warn": 5.0, "error": 5.0}


def find() -> str | None:
    """The notifier's path, or None when it isn't installed."""
    return shutil.which(COMMAND)


def _hex(colour: str) -> str:
    """'#a1b2c3' as it takes colours: six hex digits, no '#'."""
    return colour.lstrip("#")[:6].upper()


def argv(command: str, text: str, level: str, background: str, icon_colour: str,
         icon: str = "") -> list[str]:
    args = [command, "--text", text, "--timeout", f"{TIMEOUTS.get(level, 3.0):.1f}",
            "--icon-color", _hex(icon_colour), "--bg-color", _hex(background)]
    if icon:
        args += ["--icon", icon]
    return args


class Notifier:
    """Shows one toast at a time."""

    def __init__(self, command: str | None = None):
        self.command = command if command is not None else find()
        self._shown: subprocess.Popen | None = None

    @property
    def available(self) -> bool:
        return bool(self.command)

    def show(self, text: str, level: str, background: str, icon_colour: str,
             icon: str = "") -> bool:
        """Start the toast; False when it couldn't be (shown some other way)."""
        if not self.command:
            return False
        self.dismiss()
        try:
            self._shown = subprocess.Popen(
                argv(self.command, text, level, background, icon_colour, icon),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            return False
        return True

    def dismiss(self) -> None:
        """Take the toast showing, if any, off the screen. Doesn't wait for it:
        subprocess reaps a dropped process the next time one starts."""
        shown, self._shown = self._shown, None
        if shown is not None and shown.poll() is None:
            try:
                shown.send_signal(signal.SIGINT)
            except OSError:
                pass
