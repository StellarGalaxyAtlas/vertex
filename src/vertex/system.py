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


def in_console() -> bool:
    """Whether this process has a console window: started as `vertex` from a
    terminal, not from a shortcut (VertexApp.exe) or another program."""
    if not WINDOWS:
        return False
    import ctypes

    try:
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except (OSError, AttributeError):
        return False


def start_detached(argv: list[str]) -> None:
    """Start a program apart from this one's console: it keeps running when
    the terminal is closed. Raises OSError if it can't be started."""
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
             if WINDOWS else 0)
    subprocess.Popen(argv, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


# The taskbar's properties of a window (PKEY_AppUserModel_*): its id, and how
# the taskbar starts it again, with which icon and name, once it is pinned.
_APP_MODEL_KEYS = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_RELAUNCH_COMMAND, _RELAUNCH_ICON, _RELAUNCH_NAME, _APP_MODEL_ID = 2, 3, 4, 5
_IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"


def set_window_app_id(hwnd: int, app_id: str, command: str, icon: str, name: str) -> bool:
    """Put a window under Vertex's own name and icon on the taskbar. The
    process-wide id isn't enough where Python runs as a packaged app (the
    Microsoft Store's): Windows files its windows under Python's package,
    with Python's logo, unless the window itself says otherwise. Returns
    whether Windows took it."""
    if not WINDOWS:
        return False
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):      # just the VT_LPWSTR case
        _fields_ = [("vt", wintypes.USHORT), ("reserved", wintypes.WORD * 3),
                    ("value", ctypes.c_void_p), ("rest", ctypes.c_void_p)]

    def guid(text: str) -> GUID:
        return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)

    VT_LPWSTR = 31
    store = ctypes.c_void_p()
    try:
        shell32 = ctypes.windll.shell32
        shell32.SHGetPropertyStoreForWindow.argtypes = (
            wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
        shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
        if shell32.SHGetPropertyStoreForWindow(
                hwnd, ctypes.byref(guid(_IID_PROPERTY_STORE)), ctypes.byref(store)) != 0:
            return False
    except (OSError, AttributeError):
        return False
    table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                   ctypes.POINTER(PROPVARIANT))(table[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(table[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])
    ok = True
    try:
        # The id last: the taskbar reads the others when it changes.
        for pid, text in ((_RELAUNCH_COMMAND, command), (_RELAUNCH_ICON, icon),
                          (_RELAUNCH_NAME, name), (_APP_MODEL_ID, app_id)):
            buffer = ctypes.create_unicode_buffer(text)
            value = PROPVARIANT(vt=VT_LPWSTR, value=ctypes.addressof(buffer))
            key = PROPERTYKEY(fmtid=guid(_APP_MODEL_KEYS), pid=pid)
            ok = set_value(store, ctypes.byref(key), ctypes.byref(value)) == 0 and ok
        ok = commit(store) == 0 and ok
    finally:
        release(store)
    return ok


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
