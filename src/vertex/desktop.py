"""Start-menu entry, icons and login autostart.

On Linux, per the freedesktop specs: everything written lives under the
user's XDG data/config dirs. On Windows: a shortcut in the user's Start menu,
its icon in Vertex's AppData folder, and a value under the user's Run key in
the registry for starting at login. Either way it is recorded by name, so
`vertex uninstall-desktop` removes exactly what `vertex install-desktop`
wrote and nothing else.

Vertex adds its start-menu entry by itself the first time it runs, and only
then: a marker remembers it was done, so an entry the user removed stays
removed. The marker also holds the logo ink the icon was drawn in, so the
icon is redrawn only when the desktop turns from dark to light or back.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from vertex import APP_ID, APP_NAME, paths, system

ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def applications_dir() -> Path:
    return paths.data_home() / "applications"


def icon_root() -> Path:
    return paths.data_home() / "icons" / "hicolor"


def desktop_file() -> Path:
    return applications_dir() / f"{APP_ID}.desktop"


def autostart_file() -> Path:
    return paths.config_home() / "autostart" / f"{APP_ID}.desktop"


def added_marker() -> Path:
    """Present once the entry has been added, by Vertex or by the user. Holds
    the ink its icon was last drawn in."""
    return paths.default_state_dir() / "start-menu-entry-added"


# --- Windows ------------------------------------------------------------------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def start_menu_shortcut() -> Path:
    return (Path(system.appdata()) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / f"{APP_NAME}.lnk")


def windows_icon() -> Path:
    return paths.local_dir() / f"{APP_ID}.ico"


def _windows_icon(variant: str) -> list[Path]:
    """The mark as an .ico for the shortcut, drawn by Qt."""
    try:
        from PySide6.QtGui import QImage
    except ImportError:
        return []
    image = QImage(str(paths.mark_path(variant)))
    target = windows_icon()
    paths.make_dir(target.parent)
    if image.isNull() or not image.save(str(target), "ICO"):
        return []
    return [Path(paths.real(str(target)))]       # where Explorer can read it


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
                   capture_output=True, timeout=60, check=True, **system.NO_WINDOW)


def _run_value(enabled: bool, argv: list[str] | None = None) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            line = subprocess.list2cmdline([*(argv or launch_command()), "--background"])
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, line)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def _run_value_set() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
    except OSError:
        return False
    return True


# --- Both ---------------------------------------------------------------------


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
    """How to start this Vertex: its own `vertex` script if that is on PATH
    and is ours, else this interpreter running the package. On Windows, the
    installed Vertex.exe, or the console-less pythonw.exe: a shortcut to
    python.exe would open a console window beside Vertex's."""
    if system.WINDOWS:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        quiet = Path(sys.executable).with_name("pythonw.exe")
        return [str(quiet if quiet.exists() else Path(sys.executable)), "-m", "vertex"]
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
    if system.WINDOWS:
        written = _windows_icon(paths.logo_variant(variant))
        _write_shortcut(start_menu_shortcut(), argv, windows_icon())
        written.append(start_menu_shortcut())
        if autostart is not None:
            set_autostart(autostart, argv)
        _write(added_marker(), paths.logo_variant(variant))
        return written
    written = install_icons(paths.logo_variant(variant))
    _write(desktop_file(), desktop_entry(argv), 0o755)
    written.append(desktop_file())
    if autostart is not None:
        set_autostart(autostart, argv)
        if autostart:
            written.append(autostart_file())
    _write(added_marker(), paths.logo_variant(variant))
    refresh_caches()
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
    if not (start_menu_shortcut() if system.WINDOWS else desktop_file()).exists():
        return []
    variant = paths.logo_variant(variant)
    written = _windows_icon(variant) if system.WINDOWS else install_icons(variant)
    _write(added_marker(), variant)
    refresh_caches()
    return written


def set_autostart(enabled: bool, argv: list[str] | None = None) -> None:
    if system.WINDOWS:
        _run_value(enabled, argv)
        return
    if enabled:
        _write(autostart_file(), desktop_entry(argv or launch_command(), hidden_start=True))
    else:
        try:
            autostart_file().unlink()
        except FileNotFoundError:
            pass


def autostart_enabled() -> bool:
    return _run_value_set() if system.WINDOWS else autostart_file().exists()


def uninstall() -> list[Path]:
    """Remove the entry, autostart and icons `install` writes. Returns what
    was removed. The marker stays, so Vertex doesn't add the entry back."""
    if system.WINDOWS:
        autostart = autostart_enabled()
        _run_value(False)
        removed = [Path(f"HKCU\\{RUN_KEY}\\{APP_NAME}")] if autostart else []
        for path in (start_menu_shortcut(), windows_icon()):
            try:
                path.unlink()
                removed.append(path)
            except FileNotFoundError:
                pass
        return removed
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
    if system.WINDOWS:
        return
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
