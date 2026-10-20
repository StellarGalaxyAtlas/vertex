"""What sets Windows apart, in one place, so the rest of Vertex asks this
module rather than checking the platform itself.

Nothing here imports anything Windows-only at the top: every call into the
Windows API is made through ctypes when it is needed, and does nothing (or
returns its fallback) everywhere else, so Linux runs and tests the same code.
"""

from __future__ import annotations

import os
import subprocess
import sys

WINDOWS = sys.platform == "win32"

# Keyword arguments for every helper program Vertex starts (ffmpeg, ffprobe,
# the recorder): on Windows a GUI app's child otherwise opens a console
# window of its own, which flashes up over the game for every thumbnail.
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}

# Known folder ids (KNOWNFOLDERID) for the folders Vertex asks Windows about.
FOLDER_IDS = {
    "VIDEOS": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}


def known_folder(role: str) -> str:
    """Where Windows keeps a user folder (VIDEOS), wherever the user moved it
    and whatever it is called in their language; "" when it can't be told."""
    if not WINDOWS or role not in FOLDER_IDS:
        return ""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

    guid = GUID()
    ole32 = ctypes.windll.ole32
    if ole32.CLSIDFromString(FOLDER_IDS[role], ctypes.byref(guid)) != 0:
        return ""
    found = ctypes.c_wchar_p()
    try:
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(guid), 0, None, ctypes.byref(found)) != 0:
            return ""
        return found.value or ""
    finally:
        ole32.CoTaskMemFree(found)


def allow_foreground() -> None:
    """Let the running Vertex bring its window to the front when asked by
    this process: Windows only lets the app the user is using do that, so
    `vertex show` (a shortcut, a script) hands that right over first."""
    if not WINDOWS:
        return
    import ctypes

    ASFW_ANY = -1
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    except (OSError, AttributeError):
        pass


def set_app_id(app_id: str) -> None:
    """Group Vertex's windows and notifications under its own name and icon
    on the taskbar, not under python.exe's."""
    if not WINDOWS:
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (OSError, AttributeError):
        pass


PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def light_desktop() -> bool | None:
    """Whether the taskbar and Start menu are light. Windows sets them apart
    from apps: by default the taskbar is dark while apps are light, and Qt
    only reports the apps' setting. None where this isn't Windows, or
    Windows doesn't say."""
    if not WINDOWS:
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, "SystemUsesLightTheme")
    except (OSError, ImportError):
        return None
    return bool(value)


def appdata(local: bool = False) -> str:
    """%APPDATA% (settings that roam) or %LOCALAPPDATA% (data that doesn't)."""
    name = "LOCALAPPDATA" if local else "APPDATA"
    value = os.environ.get(name, "").strip()
    if value and os.path.isabs(value):
        return value
    home = os.path.expanduser("~")
    return os.path.join(home, "AppData", "Local" if local else "Roaming")
