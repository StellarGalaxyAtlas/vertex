"""Bringing Vertex's windows to the front on KDE Plasma under Wayland.

Wayland compositors don't let an app raise itself unless it was just used:
`vertex show` (a Stream Deck key, a shortcut) comes from elsewhere, so
KWin only flashes the taskbar entry. KWin's scripting interface on the
session bus can do it instead: a two-line script, loaded, run and
unloaded, activates the windows of Vertex's process.

Elsewhere (no KWin on the bus) this does nothing and says so.
"""

from __future__ import annotations

import subprocess

from vertex import paths

PLUGIN = "vertex-activate"
TIMEOUT = 2.0

# Plasma 6 has workspace.windowList/activeWindow, Plasma 5 clientList/activeClient.
SCRIPT = """\
const pid = {pid};
const windows = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (const window of windows) {{
    if (window.pid === pid && window.normalWindow) {{
        window.minimized = false;
        if (workspace.windowList) workspace.activeWindow = window;
        else workspace.activeClient = window;
    }}
}}
"""


def _call(path: str, method: str, *args: str) -> str | None:
    """A method call on KWin; its reply, or None if it failed."""
    try:
        done = subprocess.run(["dbus-send", "--session", "--print-reply", "--dest=org.kde.KWin",
                               path, method, *args],
                              capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def script_id(reply: str) -> str:
    """The script's number in loadScript's reply ("   int32 3")."""
    for word in reply.split():
        if word.lstrip("-").isdigit():
            return word
    return ""


def activate(pid: int) -> bool:
    """Ask KWin to bring the windows of process `pid` to the front."""
    script = paths.runtime_dir() / f"{PLUGIN}.js"
    try:
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(SCRIPT.format(pid=int(pid)))
    except OSError:
        return False
    scripting = "org.kde.kwin.Scripting"
    _call("/Scripting", f"{scripting}.unloadScript", f"string:{PLUGIN}")   # a stale one
    reply = _call("/Scripting", f"{scripting}.loadScript", f"string:{script}",
                  f"string:{PLUGIN}")
    number = script_id(reply or "")
    try:
        if not number:
            return False
        # Plasma 6 names the script's object /Scripting/ScriptN, Plasma 5 /N.
        return any(_call(path, "org.kde.kwin.Script.run") is not None
                   for path in (f"/Scripting/Script{number}", f"/{number}"))
    finally:
        _call("/Scripting", f"{scripting}.unloadScript", f"string:{PLUGIN}")
        try:
            script.unlink()
        except OSError:
            pass
