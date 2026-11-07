"""The game Steam is running, on Linux.

Steam starts every game, native or through Proton, under its `reaper`
process: `reaper SteamLaunch AppId=1245620 -- …`. The number names the
game, and the game's manifest in the Steam library it is installed in,
`steamapps/appmanifest_1245620.acf`, holds its store name. This works on
any desktop, Wayland or X11, and for the Flatpak Steam too: its processes
show in /proc like any other.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Where Steam keeps itself: the native package, its usual link, the Flatpak.
STEAM_HOMES = (".local/share/Steam", ".steam/steam", ".steam/root",
               ".var/app/com.valvesoftware.Steam/.local/share/Steam")

_APP_ID = re.compile(r"AppId=(\d+)")
_PATH = re.compile(r'"path"\s+"((?:[^"\\]|\\.)*)"')
_NAME = re.compile(r'"name"\s+"((?:[^"\\]|\\.)*)"')


def running_app_ids(proc: str = "/proc") -> set[str]:
    """The AppIds of the games Steam's reaper runs now."""
    ids = set()
    try:
        pids = [entry for entry in os.listdir(proc) if entry.isdigit()]
    except OSError:
        return ids
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "cmdline"), "rb") as handle:
                args = handle.read().decode("utf-8", "replace").split("\0")
        except OSError:
            continue        # gone, or not ours
        if len(args) < 3 or os.path.basename(args[0]) != "reaper" or "SteamLaunch" not in args:
            continue
        # Only reaper's own arguments, before the game's command line.
        own = args[1:args.index("--")] if "--" in args else args[1:]
        for arg in own:
            found = _APP_ID.fullmatch(arg)
            if found and found.group(1) != "0":
                ids.add(found.group(1))
    return ids


def _unquote(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def libraries(home: str | os.PathLike | None = None) -> list[Path]:
    """Every Steam library folder (each holds a steamapps folder)."""
    home = Path(home or Path.home())
    found: list[Path] = []
    for steam in STEAM_HOMES:
        root = home / steam
        candidates = [root]
        try:
            text = (root / "steamapps" / "libraryfolders.vdf").read_text(
                encoding="utf-8", errors="replace")
            candidates += [Path(_unquote(path)) for path in _PATH.findall(text)]
        except OSError:
            pass
        for folder in candidates:
            try:
                real = folder.resolve()
            except OSError:
                continue
            if real not in found and (real / "steamapps").is_dir():
                found.append(real)
    return found


def app_name(app_id: str, folders: list[Path]) -> str:
    """The store name of the game with this AppId; "" when no library has it."""
    for folder in folders:
        try:
            text = (folder / "steamapps" / f"appmanifest_{app_id}.acf").read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = _NAME.search(text)
        if found:
            return _unquote(found.group(1)).strip()
    return ""


def running_games(proc: str = "/proc", home: str | os.PathLike | None = None) -> set[str]:
    """The names of the games Steam runs now. A shortcut to a game from
    elsewhere has no manifest, and no name here."""
    ids = running_app_ids(proc)
    if not ids:
        return set()
    folders = libraries(home)
    return {name for name in (app_name(app_id, folders) for app_id in ids) if name}
