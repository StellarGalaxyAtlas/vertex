"""Vertex on Linux: the XDG folders, freedesktop menu entries and autostart,
the file manager over D-Bus, and a Unix socket for `vertex <command>`.

Everything written lives under the user's XDG data and config folders,
honouring the XDG_* variables. The names `vertex.platform` hands out are
listed there.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from vertex import APP_ID, APP_NAME, paths

NO_WINDOW: dict = {}

# --- What Vertex has here ------------------------------------------------------

RECORDER = "gsr"                    # see recorder.backend
RECORDER_COMMAND = "gpu-screen-recorder"
UNIX_SOCKETS = hasattr(socket, "AF_UNIX")
CONTROL_FILE = "control.sock"
HOTKEYS = False                     # see HotkeyListener
FULLSCREEN_GAME = False             # see fullscreen_app
SHORT_HOME = True                   # ~ for the home folder in paths shown
LIBMPV_NAMES = ("mpv",)
FILE_OPENER: tuple[str, str] | None = ("xdg-open", "install xdg-utils")


def _distro() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            text = handle.read().lower()
    except OSError:
        return ""
    for family, markers in (("arch", ("arch", "manjaro", "endeavouros", "cachyos")),
                            ("fedora", ("fedora", "nobara", "bazzite")),
                            ("debian", ("debian", "ubuntu", "mint", "pop"))):
        if any(f"id={m}" in text or f"id_like={m}" in text or f"id_like=\"{m}" in text
               for m in markers):
            return family
    return ""


PACKAGES = {
    "ffmpeg": {"arch": "ffmpeg", "fedora": "ffmpeg", "debian": "ffmpeg"},
    "libmpv": {"arch": "mpv", "fedora": "mpv-libs", "debian": "libmpv2"},
    "gsr": {"arch": "gpu-screen-recorder (AUR)", "fedora": "gpu-screen-recorder (COPR)",
            "debian": "gpu-screen-recorder (Flatpak: com.dec05eba.gpu_screen_recorder)"},
    "gsr-notify": {"arch": "gpu-screen-recorder-notification",
                   "fedora": "gpu-screen-recorder-notification (COPR)",
                   "debian": "gpu-screen-recorder-notification (from source)"},
}


def install_hint(what: str) -> str:
    """The package that brings `what`, for this distribution if it is known."""
    if what not in PACKAGES:
        return ""
    package = PACKAGES[what].get(_distro())
    if package is None:
        return "install " + " / ".join(sorted(set(PACKAGES[what].values())))
    return f"install {package}"


# --- Folders --------------------------------------------------------------------


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "").strip()
    # The spec says relative values are invalid and must be ignored.
    if value and os.path.isabs(value):
        return Path(value)
    return Path(os.path.expanduser(fallback))


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", "~/.config")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", "~/.local/share")


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", "~/.local/state")


def cache_home() -> Path:
    return _xdg("XDG_CACHE_HOME", "~/.cache")


def config_dir() -> Path:
    return config_home() / APP_ID


def data_dir() -> Path:
    return data_home() / APP_ID


def state_dir() -> Path:
    return state_home() / APP_ID


def cache_dir() -> Path:
    return cache_home() / APP_ID


def runtime_dir() -> Path:
    """Per-user runtime dir for the control socket; falls back to the cache dir."""
    value = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    base = Path(value) if value and os.path.isabs(value) else cache_home()
    return base / APP_ID


def user_dir(role: str, fallback: str) -> str:
    """An XDG user folder by role, e.g. ('VIDEOS', '~/Videos').

    Asked for by role because the folders carry translated names on a
    non-English desktop ("Vidéos", "Видео"). Tries the xdg-user-dir helper,
    then the user-dirs.dirs file it reads, then the English fallback."""
    home = os.path.expanduser("~")
    try:
        out = subprocess.run(
            ["xdg-user-dir", role], capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if out and out != home:
            return paths.normalize(out)
    except (OSError, subprocess.SubprocessError):
        pass  # helper not installed; read the file it would have read

    try:
        with open(config_home() / "user-dirs.dirs", encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key == f"XDG_{role}_DIR":
                    value = value.strip().strip('"').replace("$HOME", home)
                    if value:
                        return paths.normalize(value)
    except OSError:
        pass
    return paths.normalize(fallback)


def real(path: str) -> str:
    """A path is where it says on Linux."""
    return path


def prepare_dir(_path: str) -> None:
    """Nothing to do before os.makedirs here."""


# --- The menu entry, autostart and the window ----------------------------------------

ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def applications_dir() -> Path:
    return data_home() / "applications"


def icon_root() -> Path:
    return data_home() / "icons" / "hicolor"


def desktop_file() -> Path:
    return applications_dir() / f"{APP_ID}.desktop"


def autostart_file() -> Path:
    return config_home() / "autostart" / f"{APP_ID}.desktop"


def launch_command() -> list[str]:
    """How to start this Vertex: its own `vertex` script if that is on PATH
    and is ours, else this interpreter running the package."""
    script = shutil.which(APP_ID)
    if script:
        try:
            with open(script, encoding="utf-8", errors="replace") as handle:
                head = handle.read(4096)
        except OSError:
            head = ""
        if "vertex.cli" in head:       # the console script pip/pipx generate
            return [script]
    return [sys.executable, "-m", "vertex"]


def _exec_line(argv: list[str]) -> str:
    """argv quoted for a desktop entry's Exec key (spec §7: double quotes)."""
    def quote(arg: str) -> str:
        if not any(ch in arg for ch in ' \t\n"\'\\><~|&;$*?#()`'):
            return arg
        escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`") \
            .replace("$", "\\$")
        return f'"{escaped}"'
    return " ".join(quote(arg) for arg in argv)


def desktop_entry(argv: list[str], hidden_start: bool = False) -> str:
    base = _exec_line(argv)
    exec_line = f"{base} --background" if hidden_start else base
    return f"""[Desktop Entry]
Type=Application
Version=1.5
Name={APP_NAME}
Comment=Record, trim and share game clips; route game, chat and media audio
Exec={exec_line}
Icon={APP_ID}
Terminal=false
Categories=AudioVideo;Video;Recorder;Audio;Mixer;
Keywords=clips;recording;gameplay;moments;replay;
StartupNotify=true
StartupWMClass={APP_ID}
SingleMainWindow=true
Actions=save-clip;toggle-replay;
{"X-GNOME-Autostart-enabled=true" if hidden_start else ""}

[Desktop Action save-clip]
Name=Save Clip
Exec={base} save-clip

[Desktop Action toggle-replay]
Name=Start/Stop Replay Buffer
Exec={base} replay toggle
"""


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def draw_icon(variant: str) -> list[Path]:
    """The mark at every hicolor size, plus the SVG for scalable use."""
    written = []
    svg = paths.mark_path(variant, svg=True)
    if svg.exists():
        target = icon_root() / "scalable" / "apps" / f"{APP_ID}.svg"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(svg, target)
        written.append(target)
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage
    except ImportError:
        return written
    image = QImage(str(paths.mark_path(variant)))
    if image.isNull():
        return written
    for size in ICON_SIZES:
        target = icon_root() / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        scaled = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        if scaled.save(str(target)):
            written.append(target)
    return written


def install_entry(argv: list[str], variant: str, autostart: bool | None) -> list[Path]:
    """The menu entry and its icons (and autostart, if asked). Returns the
    files written."""
    written = draw_icon(variant)
    _write(desktop_file(), desktop_entry(argv), 0o755)
    written.append(desktop_file())
    if autostart is not None:
        set_autostart(autostart, argv)
        if autostart:
            written.append(autostart_file())
    return written


def has_entry() -> bool:
    return desktop_file().exists()


def set_autostart(enabled: bool, argv: list[str] | None = None) -> None:
    if enabled:
        _write(autostart_file(), desktop_entry(argv or launch_command(), hidden_start=True))
        return
    try:
        autostart_file().unlink()
    except FileNotFoundError:
        pass


def autostart_enabled() -> bool:
    return autostart_file().exists()


def remove_entry() -> list[Path]:
    """Remove what install_entry writes. Returns what was removed."""
    candidates = [desktop_file(), autostart_file(),
                  icon_root() / "scalable" / "apps" / f"{APP_ID}.svg"]
    candidates += [icon_root() / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
                   for size in ICON_SIZES]
    removed = []
    for path in candidates:
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            pass
    return removed


def refresh_menus() -> None:
    """Nudge menus into noticing the entry. Best-effort and silent; KDE needs
    kbuildsycoca, everything else reads the files directly."""
    for argv in (["update-desktop-database", str(applications_dir())],
                 ["gtk-update-icon-cache", "-f", "-t", str(icon_root())],
                 ["kbuildsycoca6", "--noincremental"],
                 ["kbuildsycoca5", "--noincremental"]):
        if shutil.which(argv[0]) is None:
            continue
        try:
            subprocess.run(argv, capture_output=True, timeout=60, check=False,
                           env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        except (OSError, subprocess.SubprocessError):
            pass


def set_app_id() -> None:
    """The desktop entry names Vertex's windows (Qt's desktop file name)."""


def put_on_taskbar(_window_id: int) -> bool:
    """Panels find Vertex's windows by the desktop entry."""
    return False


def activate_windows(pid: int) -> bool:
    """Bring the windows of process `pid` to the front where the desktop
    won't let Vertex do it itself: KDE Plasma under Wayland (see kwin)."""
    from vertex.platform import kwin

    return kwin.activate(pid)


def show_in_folder(path: str) -> bool:
    """The file manager's own "select this file" call. Returns whether it
    was asked; the caller opens the folder otherwise."""
    try:
        subprocess.Popen(
            ["dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
             "--type=method_call", "/org/freedesktop/FileManager1",
             "org.freedesktop.FileManager1.ShowItems",
             f"array:string:{Path(path).absolute().as_uri()}", "string:"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


# --- The rest Windows has ----------------------------------------------------------


def in_console() -> bool:
    """`vertex` runs in place, terminal or not."""
    return False


def start_detached(argv: list[str]) -> None:
    """Start a program apart from this one. Raises OSError if it can't."""
    subprocess.Popen(argv, close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def allow_foreground() -> None:
    """Nothing to hand over: see activate_windows."""


def fullscreen_app() -> tuple[str, str] | None:
    """Not told here (FULLSCREEN_GAME)."""
    return None


def light_desktop() -> bool | None:
    """The desktop's panels follow the app theme Qt reports."""
    return None


def key_name(_native_key: int) -> str:
    """No global hotkeys here (HOTKEYS), so no native key codes to name."""
    return ""


class HotkeyListener:
    """No global hotkeys here (HOTKEYS): holds nothing."""

    def __init__(self, on_press, on_result):
        self._thread = None

    def set(self, wanted: dict) -> None:
        pass

    def close(self) -> None:
        pass
