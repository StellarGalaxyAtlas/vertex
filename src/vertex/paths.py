"""Where Vertex keeps things: per-user folders and bundled assets.

Every default is derived from the account the app is running under, so
nothing machine-specific ever has to be written into the repository. Where
that is on each system is up to `vertex.platform`: the XDG base directories
on Linux, the AppData folders on Windows.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

from vertex import platform


def runtime_dir() -> Path:
    return platform.runtime_dir()


def config_dir() -> Path:
    return platform.config_dir()


def config_path() -> Path:
    return config_dir() / "config.json"


def default_data_dir() -> Path:
    return platform.data_dir()


def default_state_dir() -> Path:
    return platform.state_dir()


def default_cache_dir() -> Path:
    return platform.cache_dir()


def default_log_dir() -> Path:
    return default_state_dir() / "logs"


def control_socket() -> Path:
    """Where a running Vertex listens for `vertex <command>`: a Unix socket,
    or a file saying which local port it listens on (see `ipc`)."""
    return runtime_dir() / platform.CONTROL_FILE


def real(path: str) -> str:
    """Where `path` really is on disk, for handing to another program: a
    Python packaged as a Windows app keeps what it makes in AppData in a
    private copy other programs don't see (see platform.windows.real)."""
    return platform.real(path)


def make_dir(path: str | os.PathLike) -> str:
    """os.makedirs(path, exist_ok=True), and the folder's real place (see
    `real`). Raises OSError like os.makedirs."""
    path = os.fspath(path)
    platform.prepare_dir(path)
    os.makedirs(path, exist_ok=True)
    return real(path)


def normalize(path: str | os.PathLike | None) -> str:
    """Expand '~', collapse '..'/'.', drop a trailing slash. Blank stays ''."""
    text = os.fspath(path).strip() if path is not None else ""
    if not text:
        return ""
    return os.path.normpath(os.path.expanduser(text))


def tilde(path: str) -> str:
    """`path` with the home directory written as '~', for display, where
    the system has that shorthand."""
    if not platform.SHORT_HOME:
        return path
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def user_dir(role: str, fallback: str) -> str:
    """Absolute path of a user folder by role, e.g. ('VIDEOS', '~/Videos'),
    under whatever name the system gives it in the user's language."""
    return platform.user_dir(role, fallback)


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
