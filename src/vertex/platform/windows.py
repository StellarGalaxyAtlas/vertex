"""Vertex on Windows: AppData folders, the Start menu and taskbar, Explorer,
global hotkeys, and what Windows itself says (known folders, the game in
front, the taskbar's theme, monitors, audio devices, the graphics card).

Nothing here imports anything Windows-only at the top: every call into the
Windows API goes through ctypes or winreg when it is made, and does nothing
(or returns its fallback) on any other system, so Linux runs and tests this
module too. The names `vertex.platform` hands out are listed there.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from vertex import APP_ID, APP_NAME, paths

# Whether this really is Windows: the Windows API is only called then, even
# when tests choose this module elsewhere.
ON_WINDOWS = sys.platform == "win32"

# Keyword arguments for every helper program Vertex starts (ffmpeg, ffprobe,
# the recorder): on Windows a GUI app's child otherwise opens a console
# window of its own, which flashes up over the game for every thumbnail.
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if ON_WINDOWS else {}

# --- What Vertex has here ------------------------------------------------------

RECORDER = "obs"                    # see recorder.backend
RECORDER_COMMAND = ""               # OBS is found where it is installed
SONAR = False                       # vertex.audio needs PipeWire
STREAM_DECK_PLUGIN = ""
UNIX_SOCKETS = False                # `vertex <command>` reaches Vertex over a local port
CONTROL_FILE = "control.json"       # ... named in this file, with its token
HOTKEYS = True                      # see HotkeyListener
GAME_FROM = "the full-screen app"   # see fullscreen_app
SHORT_HOME = False                  # no ~ for the home folder in paths shown
LIBMPV_NAMES = ("mpv-2.dll", "libmpv-2.dll", "mpv-1.dll")
FILE_OPENER: tuple[str, str] | None = None      # Explorer is always there

# Where to get each, for the release that doesn't bundle them.
INSTALL_HINTS = {
    "ffmpeg": "winget install Gyan.FFmpeg",
    "libmpv": "put libmpv-2.dll (from mpv's Windows builds) next to Vertex or on PATH",
    "obs": "winget install OBSProject.OBSStudio",
}


def install_hint(what: str) -> str:
    return INSTALL_HINTS.get(what, "")


# Known folder ids (KNOWNFOLDERID) for the folders Vertex asks Windows about.
FOLDER_IDS = {
    "VIDEOS": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}


def known_folder(role: str) -> str:
    """Where Windows keeps a user folder (VIDEOS), wherever the user moved it
    and whatever it is called in their language; "" when it can't be told."""
    if not ON_WINDOWS or role not in FOLDER_IDS:
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
    if not ON_WINDOWS:
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
             if ON_WINDOWS else 0)
    subprocess.Popen(argv, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def allow_foreground() -> None:
    """Let the running Vertex bring its window to the front when asked by
    this process: Windows only lets the app the user is using do that, so
    `vertex show` (a shortcut, a script) hands that right over first."""
    if not ON_WINDOWS:
        return
    import ctypes

    ASFW_ANY = -1
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    except (OSError, AttributeError):
        pass


GUI_SCRIPT = "VertexApp"       # pyproject's gui-script
APP_USER_MODEL_ID = f"{APP_NAME}.{APP_NAME}"     # what the taskbar files Vertex under


def set_app_id() -> None:
    """Group Vertex's windows and notifications under its own name and icon
    on the taskbar, not under python.exe's."""
    if not ON_WINDOWS:
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
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
    if not ON_WINDOWS:
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


# Windows of the desktop and the taskbar: the foreground with no app in front.
_SHELL_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"})


def running_game() -> str:
    """Not told here: the full-screen app says (fullscreen_app)."""
    return ""


def fullscreen_app() -> tuple[str, str] | None:
    """(title, program path) of the window in front when it fills its
    screen, the way a game does, borderless or not; ("", "") when no window
    does. None where that can't be told: not Windows, or Vertex's own
    window is in front, so whatever was played is behind it."""
    if not ON_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    MONITOR_DEFAULTTONEAREST = 2
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    try:
        user32 = ctypes.WinDLL("user32")
        kernel32 = ctypes.WinDLL("kernel32")
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                    ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, len(name))
        if name.value in _SHELL_CLASSES:
            return "", ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return None
        rect, screen = wintypes.RECT(), MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)) or not user32.GetMonitorInfoW(
                user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(screen)):
            return None
        whole = screen.rcMonitor
        if (rect.left > whole.left or rect.top > whole.top
                or rect.right < whole.right or rect.bottom < whole.bottom):
            return "", ""
        title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        program = ""
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if process:
            try:
                path, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                    program = path.value
            finally:
                kernel32.CloseHandle(process)
        return title.value, program
    except (OSError, AttributeError):
        return None


PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def light_desktop() -> bool | None:
    """Whether the taskbar and Start menu are light. Windows sets them apart
    from apps: by default the taskbar is dark while apps are light, and Qt
    only reports the apps' setting. None where this isn't Windows, or
    Windows doesn't say."""
    if not ON_WINDOWS:
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


# --- Folders --------------------------------------------------------------------
#
#     settings    %APPDATA%\Vertex\config.json
#     library     %LOCALAPPDATA%\Vertex\Library
#     logs        %LOCALAPPDATA%\Vertex\State\logs
#     thumbnails  %LOCALAPPDATA%\Vertex\Cache


def local_dir() -> Path:
    """The folder under %LOCALAPPDATA% everything but the settings goes in."""
    return Path(appdata(local=True)) / APP_NAME


def config_dir() -> Path:
    return Path(appdata()) / APP_NAME


def data_dir() -> Path:
    return local_dir() / "Library"


def state_dir() -> Path:
    return local_dir() / "State"


def cache_dir() -> Path:
    return local_dir() / "Cache"


def runtime_dir() -> Path:
    return local_dir()


def user_dir(role: str, fallback: str) -> str:
    """The known folder Windows keeps for a role (VIDEOS), else `fallback`."""
    return paths.normalize(known_folder(role) or fallback)


def _in_appdata(path: str) -> bool:
    folder = os.path.normcase(os.path.abspath(path))
    for root in (appdata(), appdata(local=True)):
        root = os.path.normcase(os.path.abspath(root))
        if folder == root or folder.startswith(root.rstrip(os.sep) + os.sep):
            return True
    return False


def real(path: str) -> str:
    """Where `path` really is on disk, for handing to another program.

    A Python packaged as a Windows app (the Microsoft Store's) writes new
    folders and files under AppData into a private copy that only it sees:
    ffmpeg, OBS and Explorer look for them in vain. realpath() names the
    copy. Outside AppData, `path` is returned as it is."""
    if not path or not _in_appdata(path):
        return path
    return os.path.realpath(path)


def prepare_dir(path: str) -> None:
    """Under AppData, Windows' own mkdir makes a missing folder, so it is
    made where every program sees it (see `real`); a folder that already
    exists there is used where it is, not copied into the private one."""
    if os.path.isdir(path) or not _in_appdata(path):
        return
    try:
        # One string: cmd parses its own line, and the quotes keep a
        # path's spaces and & together.
        subprocess.run(f'cmd /d /c mkdir "{path}"', capture_output=True, timeout=10,
                       check=False, **NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass


# --- The Start menu, signing in and the taskbar -----------------------------------


def _programs() -> Path:
    return Path(appdata()) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def start_menu_shortcut() -> Path:
    return _programs() / f"{APP_NAME}.lnk"


def startup_shortcut() -> Path:
    """Starts Vertex when the user signs in. A shortcut, not a Run value in
    the registry: Windows lists a shortcut by its own name, a Run value by
    the program it starts (pythonw.exe)."""
    return _programs() / "Startup" / f"{APP_NAME}.lnk"


def icon_file() -> Path:
    return local_dir() / f"{APP_ID}.ico"


def _shortcut_icon() -> Path:
    """The icon where Explorer can read it (see real)."""
    return Path(real(str(icon_file())))


def launch_command() -> list[str]:
    """How to start this Vertex: the installed Vertex.exe, the VertexApp.exe
    launcher pip writes beside this interpreter, or the console-less
    pythonw.exe: a shortcut to python.exe would open a console window beside
    Vertex's. Windows lists the startup entry by that program's name."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    launcher = Path(sys.executable).with_name(f"{GUI_SCRIPT}.exe")
    if launcher.exists():
        return [str(launcher)]
    quiet = Path(sys.executable).with_name("pythonw.exe")
    return [str(quiet if quiet.exists() else Path(sys.executable)), "-m", "vertex"]


def put_on_taskbar(hwnd: int) -> bool:
    """A window under Vertex's name and icon on the taskbar, also when
    pinned (see set_window_app_id). The icon is named as a resource, a file
    and its index: a bare path is ignored and the pin gets python.exe's."""
    return set_window_app_id(hwnd, APP_USER_MODEL_ID, subprocess.list2cmdline(launch_command()),
                             f"{_shortcut_icon()},0", APP_NAME)


def draw_icon(variant: str) -> list[Path]:
    """The mark as an .ico for the shortcut, drawn by Qt."""
    try:
        from PySide6.QtGui import QImage
    except ImportError:
        return []
    image = QImage(str(paths.mark_path(variant)))
    target = icon_file()
    paths.make_dir(target.parent)
    if image.isNull() or not image.save(str(target), "ICO"):
        return []
    return [Path(real(str(target)))]       # where Explorer can read it


def _powershell_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _write_shortcut(path: Path, argv: list[str], icon: Path) -> None:
    """A .lnk through Windows' own shell object; PowerShell is on every
    Windows Vertex runs on."""
    path.parent.mkdir(parents=True, exist_ok=True)
    script = "; ".join((
        f"$link = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"{_powershell_quote(str(path))})",
        f"$link.TargetPath = {_powershell_quote(argv[0])}",
        f"$link.Arguments = {_powershell_quote(subprocess.list2cmdline(argv[1:]))}",
        f"$link.IconLocation = {_powershell_quote(str(icon))}",
        f"$link.Description = {_powershell_quote('Record, trim and share game clips')}",
        "$link.Save()"))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   capture_output=True, timeout=60, check=True, **NO_WINDOW)


def install_entry(argv: list[str], variant: str, autostart: bool | None) -> list[Path]:
    """The Start menu shortcut and its icon (and the sign-in shortcut, if
    asked). Returns the files written."""
    written = draw_icon(variant)
    _write_shortcut(start_menu_shortcut(), argv, _shortcut_icon())
    written.append(start_menu_shortcut())
    if autostart is not None:
        set_autostart(autostart, argv)
    return written


def has_entry() -> bool:
    return start_menu_shortcut().exists()


def set_autostart(enabled: bool, argv: list[str] | None = None) -> None:
    if enabled:
        _write_shortcut(startup_shortcut(), [*(argv or launch_command()), "--background"],
                        _shortcut_icon())
        return
    try:
        startup_shortcut().unlink()
    except FileNotFoundError:
        pass


def autostart_enabled() -> bool:
    return startup_shortcut().exists()


def remove_entry() -> list[Path]:
    """Remove what install_entry writes. Returns what was removed."""
    removed = []
    for path in (start_menu_shortcut(), startup_shortcut(), icon_file()):
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            pass
    return removed


def refresh_menus() -> None:
    """The Start menu notices shortcuts by itself."""


def activate_windows(_pid: int) -> bool:
    """Windows brings Vertex to the front itself, once allow_foreground has
    let it."""
    return False


def show_in_folder(path: str) -> bool:
    """Explorer, with the file selected. Returns whether it was asked."""
    try:
        # As one line: Explorer reads /select, and the quoted path itself.
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    except OSError:
        return False
    return True


# --- Global hotkeys ---------------------------------------------------------------

_MOD_BITS = {"Alt": 0x1, "Ctrl": 0x2, "Shift": 0x4, "Win": 0x8}
_MOD_NOREPEAT = 0x4000      # held down, a hotkey fires once
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_WM_APP_SET = 0x8000 + 1


def key_name(virtual_key: int) -> str:
    """The name in hotkeys.KEYS of a key from its Windows virtual-key code
    (what a key event's nativeVirtualKey is here); "" for one a hotkey can't
    use."""
    from vertex import hotkeys

    for name, code in hotkeys.KEYS.items():
        if code == virtual_key:
            return name
    return ""


class HotkeyListener:
    """Holds the hotkeys with Windows (RegisterHotKey, on a thread of its
    own) and calls `on_press(action)` when one is pressed, and
    `on_result(failed)` with the actions whose keys another program already
    holds after each `set`. Both are called from the listener's thread."""

    def __init__(self, on_press, on_result):
        import threading

        self._on_press = on_press
        self._on_result = on_result
        self._wanted: dict = {}
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread_id = 0
        self._thread: threading.Thread | None = None

    def set(self, wanted: dict) -> None:
        """Hold exactly these hotkeys (action → hotkeys.Hotkey) from now on;
        {} lets every one go."""
        import threading

        if not ON_WINDOWS:
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

        from vertex import hotkeys, logs

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
                    if user32.RegisterHotKey(None, number, bits, hotkeys.KEYS[hotkey.key]):
                        held[number] = action
                    else:
                        failed.add(action)
                        logs.APP.warning("Another program holds %s", hotkey.text)
                self._on_result(failed)
        for number in held:
            user32.UnregisterHotKey(None, number)


# --- What OBS needs to know from Windows --------------------------------------------
# (see recorder.obs)


def registry_defaults(key: str) -> list[str]:
    """The default value of a key under HKEY_LOCAL_MACHINE, as 64-bit and
    32-bit programs see it, each once."""
    if not ON_WINDOWS:
        return []
    import winreg

    found = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0,
                                winreg.KEY_READ | view) as opened:
                value, _kind = winreg.QueryValueEx(opened, "")
        except OSError:
            continue
        if value and value not in found:
            found.append(value)
    return found


def file_version(path: str) -> tuple[int, ...]:
    """A Windows program's version from its version resource; () if unknown."""
    if not ON_WINDOWS:
        return ()
    import ctypes
    from ctypes import wintypes

    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ()
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, data):
        return ()
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return ()
    # VS_FIXEDFILEINFO: signature, struct version, then the file version.
    fields = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 4)).contents
    high, low = fields[2], fields[3]
    return (high >> 16, high & 0xFFFF, low >> 16)


def program_running(image: str) -> bool:
    """Whether a program (by its file name: obs64.exe) runs for this user."""
    if not ON_WINDOWS:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV",
                              "/NH"], capture_output=True, text=True, timeout=10,
                             **NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return image.lower() in out.lower()


def close_program(pid: int) -> bool:
    """Ask a program to quit, as closing its window does (it may still ask
    or refuse): never forced."""
    if not ON_WINDOWS:
        return False
    try:
        result = subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True,
                                text=True, timeout=10, **NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


_MMDEVICES = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
# Property keys of an endpoint: what it is ("Speakers") and what it is part
# of ("Realtek Audio"). Windows shows them as "Speakers (Realtek Audio)".
_DEVICE_DESCRIPTION = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
_INTERFACE_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"


def audio_endpoints(flow: str) -> list[tuple[str, str]]:
    """(guid, name) of each audio device plugged in and enabled, by flow:
    "Render" for outputs, "Capture" for inputs; sorted by name."""
    if not ON_WINDOWS:
        return []
    import winreg

    devices = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{_MMDEVICES}\{flow}", 0,
                              winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return []
    with root:
        index = 0
        while True:
            try:
                guid = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(root, guid) as key:
                    state, _kind = winreg.QueryValueEx(key, "DeviceState")
                with winreg.OpenKey(root, rf"{guid}\Properties") as props:
                    what, _kind = winreg.QueryValueEx(props, _DEVICE_DESCRIPTION)
                    try:
                        part, _kind = winreg.QueryValueEx(props, _INTERFACE_NAME)
                    except OSError:
                        part = ""
            except OSError:
                continue
            if state != 1:          # DEVICE_STATE_ACTIVE: plugged in and enabled
                continue
            devices.append((guid, f"{what} ({part})" if part else what))
    return sorted(devices, key=lambda device: device[1].lower())


@dataclass(frozen=True)
class MonitorRect:
    name: str             # Windows' name for it, as Qt has it: \\.\DISPLAY1
    x: int
    y: int
    width: int
    height: int


def monitor_label(name: str) -> str:
    """A monitor's name to show: \\\\.\\DISPLAY1 reads as Display 1."""
    match = re.fullmatch(r"\\\\\.\\DISPLAY(\d+)", name)
    return f"Display {match[1]}" if match else name


def monitor_rects() -> list[MonitorRect]:
    """The monitors, in physical pixels once Qt has made Vertex DPI-aware."""
    if not ON_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    found: list[MonitorRect] = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                       ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(monitor, _dc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.rcMonitor
            found.append(MonitorRect(info.szDevice, rect.left, rect.top,
                                     rect.right - rect.left, rect.bottom - rect.top))
        return True

    user32.EnumDisplayMonitors(None, None, callback_type(callback), 0)
    return found


def display_adapters() -> list[str]:
    """The graphics adapters' names, the main display's first."""
    if not ON_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

    PRIMARY = 0x4
    names, index = [], 0
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not ctypes.windll.user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            break
        index += 1
        if device.StateFlags & PRIMARY:
            names.insert(0, device.DeviceString)
        else:
            names.append(device.DeviceString)
    return names
