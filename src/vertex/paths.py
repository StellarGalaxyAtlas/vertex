"""Where Vertex keeps things: per-user folders and bundled assets.

Every default is derived from the account the app is running under, so
nothing machine-specific ever has to be written into the repository. On
Linux that means the XDG base directories (honouring the XDG_* variables);
on Windows, the AppData folders:

    settings    %APPDATA%\\Vertex\\config.json
    library     %LOCALAPPDATA%\\Vertex\\Library
    logs        %LOCALAPPDATA%\\Vertex\\State\\logs
    thumbnails  %LOCALAPPDATA%\\Vertex\\Cache
"""

from __future__ import annotations

import os
import subprocess
from importlib import resources
from pathlib import Path

from vertex import APP_ID, APP_NAME, system


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


def local_dir() -> Path:
    """Windows: the folder under %LOCALAPPDATA% everything but the settings
    goes in."""
    return Path(system.appdata(local=True)) / APP_NAME


def runtime_dir() -> Path:
    """Per-user runtime dir for the control socket; falls back to the cache dir."""
    if system.WINDOWS:
        return local_dir()
    value = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    base = Path(value) if value and os.path.isabs(value) else cache_home()
    return base / APP_ID


def config_dir() -> Path:
    if system.WINDOWS:
        return Path(system.appdata()) / APP_NAME
    return config_home() / APP_ID


def config_path() -> Path:
    return config_dir() / "config.json"


def default_data_dir() -> Path:
    return local_dir() / "Library" if system.WINDOWS else data_home() / APP_ID


def default_state_dir() -> Path:
    return local_dir() / "State" if system.WINDOWS else state_home() / APP_ID


def default_cache_dir() -> Path:
    return local_dir() / "Cache" if system.WINDOWS else cache_home() / APP_ID


def default_log_dir() -> Path:
    return default_state_dir() / "logs"


def control_socket() -> Path:
    """Where a running Vertex listens for `vertex <command>`: a Unix socket,
    or on Windows a file saying which local port it listens on (see `ipc`)."""
    return runtime_dir() / ("control.json" if system.WINDOWS else "control.sock")


def _in_appdata(path: str) -> bool:
    folder = os.path.normcase(os.path.abspath(path))
    for root in (system.appdata(), system.appdata(local=True)):
        root = os.path.normcase(os.path.abspath(root))
        if folder == root or folder.startswith(root.rstrip(os.sep) + os.sep):
            return True
    return False


def real(path: str) -> str:
    """Where `path` really is on disk, for handing to another program.

    A Python packaged as a Windows app (the Microsoft Store's) writes new
    folders and files under AppData into a private copy that only it sees:
    ffmpeg, OBS and Explorer look for them in vain. realpath() names the
    copy. Elsewhere, and outside AppData, `path` is returned as it is."""
    if not system.WINDOWS or not path or not _in_appdata(path):
        return path
    return os.path.realpath(path)


def make_dir(path: str | os.PathLike) -> str:
    """os.makedirs(path, exist_ok=True), and the folder's real place (see
    `real`). Under AppData on Windows, Windows' own mkdir makes it first: a
    folder that already exists in AppData is used where it is, not copied
    into the private one. Raises OSError like os.makedirs."""
    path = os.fspath(path)
    if system.WINDOWS and not os.path.isdir(path) and _in_appdata(path):
        try:
            # One string: cmd parses its own line, and the quotes keep a
            # path's spaces and & together.
            subprocess.run(f'cmd /d /c mkdir "{path}"', capture_output=True, timeout=10,
                           check=False, **system.NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
    os.makedirs(path, exist_ok=True)
    return real(path)


def normalize(path: str | os.PathLike | None) -> str:
    """Expand '~', collapse '..'/'.', drop a trailing slash. Blank stays ''."""
    text = os.fspath(path).strip() if path is not None else ""
    if not text:
        return ""
    return os.path.normpath(os.path.expanduser(text))


def tilde(path: str) -> str:
    """`path` with the home directory written as '~', for display. Windows
    has no such shorthand: paths show in full there."""
    if system.WINDOWS:
        return path
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def xdg_user_dir(role: str, fallback: str) -> str:
    """Absolute path of an XDG user folder by role, e.g. ('VIDEOS', '~/Videos').

    Asked for by role because the folders carry translated names on a
    non-English desktop ("Vidéos", "Видео"). Tries the xdg-user-dir helper,
    then the user-dirs.dirs file it reads, then the English fallback. On
    Windows, the known folder Windows itself keeps for the role.
    """
    home = os.path.expanduser("~")
    if system.WINDOWS:
        return normalize(system.known_folder(role) or fallback)
    try:
        out = subprocess.run(
            ["xdg-user-dir", role], capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if out and out != home:
            return normalize(out)
    except (OSError, subprocess.SubprocessError):
        pass  # helper not installed; read the file it would have read

    try:
        with open(config_home() / "user-dirs.dirs", encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key == f"XDG_{role}_DIR":
                    value = value.strip().strip('"').replace("$HOME", home)
                    if value:
                        return normalize(value)
    except OSError:
        pass
    return normalize(fallback)


# --- Bundled assets ---------------------------------------------------------
# The logo ships in two inks: "light" artwork for dark backgrounds — what the
# app's own chrome wants — and "dark" artwork for light ones. Which one the
# desktop icon uses is the user's choice, because the panel it sits on is not
# something the app can see.

LOGO_VARIANTS = ("light", "dark")
DEFAULT_LOGO_VARIANT = "light"


def logo_variant(name: str | None) -> str:
    """`name` if it is a variant we ship, else the default. Never raises."""
    return name if name in LOGO_VARIANTS else DEFAULT_LOGO_VARIANT


def asset(*parts: str) -> Path:
    """Filesystem path of a bundled asset."""
    return Path(str(resources.files("vertex").joinpath("assets", *parts)))


def mark_path(variant: str = DEFAULT_LOGO_VARIANT, svg: bool = False) -> Path:
    """The square mark: desktop icon, window icon, tray, first-run screen."""
    variant = logo_variant(variant)
    return asset("logo", variant, f"vertex-mark-{variant}.{'svg' if svg else 'png'}")


def wordmark_path(variant: str = DEFAULT_LOGO_VARIANT) -> Path:
    """The horizontal lockup: the mark with the name beside it."""
    variant = logo_variant(variant)
    return asset("logo", variant, f"vertex-horizontal-{variant}.png")
