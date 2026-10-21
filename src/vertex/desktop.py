"""Start-menu entry, icons and login autostart.

What is written, and where, is up to `vertex.platform`: a freedesktop menu
entry and icons under the XDG folders on Linux, Start menu and Startup
shortcuts on Windows. Either way it is recorded by name, so
`vertex uninstall-desktop` removes exactly what `vertex install-desktop`
wrote and nothing else.

Vertex adds its start-menu entry by itself the first time it runs, and only
then: a marker remembers it was done, so an entry the user removed stays
removed. The marker also holds the logo ink the icon was drawn in, so the
icon is redrawn only when the desktop turns from dark to light or back.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from vertex import paths, platform


def added_marker() -> Path:
    """Present once the entry has been added, by Vertex or by the user. Holds
    the ink its icon was last drawn in."""
    return paths.default_state_dir() / "start-menu-entry-added"


def icon_ink() -> str:
    """The logo ink the start-menu icon was last drawn in ("" if unknown)."""
    try:
        return added_marker().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def desktop_ink() -> str:
    """The logo ink that suits the desktop, asked of Qt the way the window
    asks it. Qt runs in a child process: without a usable display it aborts,
    and then the default ink is used."""
    probe = "from vertex.ui import icons; print(icons.desktop_ink_outside_app())"
    try:
        done = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                              text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return paths.DEFAULT_LOGO_VARIANT
    return paths.logo_variant(done.stdout.strip())


def launch_command() -> list[str]:
    """How to start this Vertex, from a menu entry or at sign-in."""
    return platform.launch_command()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def install(variant: str = paths.DEFAULT_LOGO_VARIANT, autostart: bool | None = None,
            argv: list[str] | None = None) -> list[Path]:
    """Write the entry and icons (and autostart, if asked). Returns the files."""
    variant = paths.logo_variant(variant)
    written = platform.install_entry(argv or launch_command(), variant, autostart)
    _write(added_marker(), variant)
    platform.refresh_menus()
    return written


def ensure(variant: str = paths.DEFAULT_LOGO_VARIANT) -> list[Path]:
    """Add the entry if it never has been: on the first run, so Vertex is in
    the start menu without asking. After that, redraw its icon if it is in
    another ink. Returns what was written, usually nothing."""
    if not added_marker().exists():
        return install(variant)
    if icon_ink() != paths.logo_variant(variant):
        return update_icons(variant)
    return []


def update_icons(variant: str) -> list[Path]:
    """Redraw the start-menu icon in another logo ink, if there is an entry."""
    if not platform.has_entry():
        return []
    variant = paths.logo_variant(variant)
    written = platform.draw_icon(variant)
    _write(added_marker(), variant)
    platform.refresh_menus()
    return written


def set_autostart(enabled: bool, argv: list[str] | None = None) -> None:
    platform.set_autostart(enabled, argv)


def autostart_enabled() -> bool:
    return platform.autostart_enabled()


def uninstall() -> list[Path]:
    """Remove the entry, autostart and icons `install` writes. Returns what
    was removed. The marker stays, so Vertex doesn't add the entry back."""
    removed = platform.remove_entry()
    platform.refresh_menus()
    return removed
