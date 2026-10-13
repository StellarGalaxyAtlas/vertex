"""Start-menu entry, icons and login autostart, per the freedesktop specs.

Everything written lives under the user's XDG data/config dirs and is
recorded by name, so `vertex uninstall-desktop` removes exactly what
`vertex install-desktop` wrote and nothing else.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from vertex import APP_ID, APP_NAME, paths

ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def applications_dir() -> Path:
    return paths.data_home() / "applications"


def icon_root() -> Path:
    return paths.data_home() / "icons" / "hicolor"


def desktop_file() -> Path:
    return applications_dir() / f"{APP_ID}.desktop"


def autostart_file() -> Path:
    return paths.config_home() / "autostart" / f"{APP_ID}.desktop"


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
GenericName=Game Clip Recorder
Comment=Record, trim and share game clips; route game, chat and media audio
Exec={exec_line}
Icon={APP_ID}
Terminal=false
Categories=AudioVideo;Video;Recorder;Audio;Mixer;
Keywords=clips;recording;gameplay;moments;replay;sonar;mixer;pipewire;
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


def install_icons(variant: str) -> list[Path]:
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


def install(variant: str = paths.DEFAULT_LOGO_VARIANT, autostart: bool | None = None,
            argv: list[str] | None = None) -> list[Path]:
    """Write the entry and icons (and autostart, if asked). Returns the files."""
    argv = argv or launch_command()
    written = install_icons(paths.logo_variant(variant))
    _write(desktop_file(), desktop_entry(argv), 0o755)
    written.append(desktop_file())
    if autostart is not None:
        set_autostart(autostart, argv)
        if autostart:
            written.append(autostart_file())
    refresh_caches()
    return written


def set_autostart(enabled: bool, argv: list[str] | None = None) -> None:
    if enabled:
        _write(autostart_file(), desktop_entry(argv or launch_command(), hidden_start=True))
    else:
        try:
            autostart_file().unlink()
        except FileNotFoundError:
            pass


def autostart_enabled() -> bool:
    return autostart_file().exists()


def uninstall() -> list[Path]:
    """Remove everything `install` writes. Returns what was removed."""
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
    refresh_caches()
    return removed


def refresh_caches() -> None:
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
