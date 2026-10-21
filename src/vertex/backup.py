"""Backups: the settings and the library in one zip file, and putting one back.

Never the clips, the thumbnails or the logs: the clips are the user's own
files, and the rest is made again. A restore first moves the settings and the
library in use out of the way, recoverably (`reset.discard`).

Vertex also backs up once a day by itself while `daily_backup` is on,
keeping the last few in a folder of the library's.

A restore puts back what the user picks (`choices`, by setting_groups'
items, and the library). By default, all but folders that aren't on this
computer, and a recorder's and Sonar's settings made for another recorder
(GPU Screen Recorder, OBS).
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass, field

from vertex import APP_NAME, __version__, fmt, paths, platform, reset, setting_groups
from vertex.config import Config
from vertex.library.database import DB_NAME, SCHEMA_VERSION
from vertex.setting_groups import LIBRARY

FORMAT = 1                       # bumped when what a backup holds changes
MANIFEST = "vertex-backup.json"
SETTINGS = "config.json"
LIBRARY_FILE = DB_NAME
SUFFIX = ".zip"
PARTS = ("settings", "library")
AUTOMATIC_DIR = "Backups"        # in the library folder
AUTOMATIC_KEPT = 5
DAY = 24 * 3600



class BackupError(Exception):
    """A backup that can't be made, read or put back; the message says why."""


@dataclass
class Contents:
    """What a backup holds, as its manifest says."""

    created: float
    version: str                 # the Vertex that made it
    recorder: str                # platform.RECORDER where it was made
    parts: tuple[str, ...]       # of PARTS
    clips: int = 0               # clips the library knows


@dataclass
class Restored:
    config: Config               # the settings now in use
    picks: tuple[str, ...]       # what was put back: setting_groups keys, LIBRARY
    clips: int = 0
    left_out: list[str] = field(default_factory=list)   # not picked by default, and why
    moved_to: str = ""           # where the replaced files went, "" if nowhere

    @property
    def settings(self) -> bool:
        return any(key != LIBRARY for key in self.picks)


def default_name(when: float | None = None) -> str:
    return f"{APP_NAME} backup {time.strftime('%Y-%m-%d', time.localtime(when))}{SUFFIX}"


def automatic_dir(config: Config) -> str:
    return os.path.join(config.resolved_data_dir(), AUTOMATIC_DIR)


def automatic(config: Config) -> list[tuple[str, Contents]]:
    """The automatic backups that can be read, newest first."""
    folder = automatic_dir(config)
    try:
        names = [name for name in os.listdir(folder) if name.endswith(SUFFIX)]
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(folder, name)
        try:
            found.append((path, read(path)))
        except BackupError:
            continue
    return sorted(found, key=lambda pair: -pair[1].created)


def back_up_daily(config: Config, now: float | None = None) -> str:
    """Make the day's automatic backup unless one is less than a day old,
    then keep only the newest few. Returns the new backup's path, or ""."""
    now = time.time() if now is None else now
    database = os.path.join(config.resolved_data_dir(), DB_NAME)
    if not config.daily_backup or not os.path.isfile(database):
        return ""
    made = automatic(config)
    if made and now - made[0][1].created < DAY:
        return ""
    stamp = time.strftime("%Y-%m-%d %H%M%S", time.localtime(now))
    path = os.path.join(automatic_dir(config), f"{APP_NAME} backup {stamp}{SUFFIX}")
    export(path, config, now=now)
    for old, _contents in automatic(config)[AUTOMATIC_KEPT:]:
        _remove(old)
    return path


def missing_clips(config: Config, data_dir: str | None = None) -> tuple[int, int]:
    """(clips the library knows that aren't in the clips folder, clips it
    knows). A clip deleted outside Vertex is still known, so a few missing
    is normal; most of them missing means the clips are somewhere else."""
    database = os.path.join(data_dir or config.resolved_data_dir(), DB_NAME)
    folder = config.resolved_clip_dir()
    if not os.path.isfile(database):
        return 0, 0
    try:
        conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            names = [row[0] for row in conn.execute("SELECT filename FROM clips")]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0, 0
    missing = sum(1 for name in names if not os.path.isfile(os.path.join(folder, name)))
    return missing, len(names)


def export(target: str, config: Config, data_dir: str | None = None,
           now: float | None = None) -> Contents:
    """Write a backup of `config` and the library in `data_dir` (the config's
    own by default) to `target`, which is replaced if it exists."""
    data_dir = data_dir or config.resolved_data_dir()
    database = os.path.join(data_dir, DB_NAME)
    target = os.path.abspath(target)
    folder = os.path.dirname(target)
    paths.make_dir(folder)
    parts = ("settings",)
    clips = 0
    with tempfile.TemporaryDirectory(prefix="vertex-backup-") as scratch:
        snapshot = os.path.join(scratch, LIBRARY_FILE)
        if os.path.isfile(database):
            clips = _snapshot(database, snapshot)
            parts = PARTS
        created = time.time() if now is None else now
        contents = Contents(created, __version__, platform.RECORDER, parts, clips)
        staging = os.path.join(folder, f".{os.path.basename(target)}.part")
        try:
            with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(MANIFEST, json.dumps(_manifest(contents), indent=2))
                archive.writestr(SETTINGS, json.dumps(config.to_dict(), indent=4))
                if "library" in parts:
                    archive.write(snapshot, LIBRARY_FILE)
            os.replace(staging, target)
        except BaseException:
            _remove(staging)
            raise
    return contents


def read(path: str) -> Contents:
    """What the backup at `path` holds. Raises BackupError if it isn't one
    this Vertex can put back."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if MANIFEST not in names:
                raise BackupError(f"{os.path.basename(path)} isn't a {APP_NAME} backup.")
            data = json.loads(archive.read(MANIFEST))
    except (OSError, zipfile.BadZipFile, ValueError, KeyError) as exc:
        raise BackupError(f"Couldn't read {os.path.basename(path)}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("format"), int):
        raise BackupError(f"{os.path.basename(path)} isn't a {APP_NAME} backup.")
    if data["format"] > FORMAT:
        raise BackupError(f"This backup was made by a newer {APP_NAME} "
                          f"({data.get('version', '?')}). Update {APP_NAME} first.")
    parts = tuple(part for part in PARTS if part in data.get("parts", ()) and
                  (SETTINGS if part == "settings" else LIBRARY_FILE) in names)
    if not parts:
        raise BackupError(f"{os.path.basename(path)} holds nothing to restore.")
    return Contents(float(data.get("created", 0) or 0), str(data.get("version", "")),
                    str(data.get("recorder", "")), parts, int(data.get("clips", 0) or 0))


@dataclass
class Choice:
    """One thing a restore can put back, as the backup has it."""

    key: str                     # a setting_groups item's, or LIBRARY
    shown: str                   # the backup's value
    now: str = ""                # what is in use, when that differs
    default: bool = True         # picked unless the user says otherwise
    note: str = ""               # why it isn't picked by default


def load_settings(path: str) -> Config | None:
    """The backup's settings, None if it holds none."""
    try:
        with zipfile.ZipFile(path) as archive:
            if SETTINGS not in archive.namelist():
                return None
            data = json.loads(archive.read(SETTINGS))
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise BackupError(f"Couldn't read the backup's settings: {exc}") from exc
    if not isinstance(data, dict):
        raise BackupError("The backup's settings can't be read.")
    return Config.from_dict(data)


def choices(contents: Contents, settings: Config | None, current: Config) -> dict[str, Choice]:
    """What the backup can put back, by key. Folders that aren't on this
    computer, and a recorder's (or Sonar's) settings made for another
    recorder, aren't picked by default."""
    found: dict[str, Choice] = {}
    if settings is not None:
        other_recorder = bool(contents.recorder) and contents.recorder != platform.RECORDER
        for group in setting_groups.groups():
            for item in group.items:
                choice = Choice(item.key, item.shown(settings))
                if setting_groups.differs(item, settings, current):
                    choice.now = item.shown(current)
                    if choice.now == choice.shown:
                        choice.now = "different"
                if item.folders and not _folders_here(item, settings, current):
                    choice.default, choice.note = False, "not on this computer"
                elif item.recorder and other_recorder:
                    choice.default, choice.note = False, "made for another recorder"
                found[item.key] = choice
    if "library" in contents.parts:
        found[LIBRARY] = Choice(LIBRARY, fmt.plural(contents.clips, "clip"))
    return found


def restore(path: str, current: Config, picks=None,
            config_file: str | None = None) -> Restored:
    """Put the settings and the library (the keys in `picks`, or what is
    picked by default) of the backup at `path` in place of those in use:
    `current`, saved at `config_file`. Close the library first. Raises
    BackupError, leaving everything as it was, if the backup can't be read."""
    contents = read(path)
    settings = load_settings(path) if "settings" in contents.parts else None
    offered = choices(contents, settings, current)
    if picks is None:
        picks = [key for key, choice in offered.items() if choice.default]
    picks = [key for key in offered if key in set(picks)]
    if not picks:
        raise BackupError("Nothing was picked to restore.")
    config = copy.deepcopy(current)
    items = setting_groups.items()
    for key in picks:
        if key != LIBRARY:
            for name in items[key].fields:
                setting_groups.put(config, name, copy.deepcopy(setting_groups.get(settings, name)))
    left_out = [key for key, choice in offered.items() if choice.note and key not in picks]
    data_dir = config.resolved_data_dir()
    staging, clips = "", 0
    if LIBRARY in picks:
        paths.make_dir(data_dir)
        staging = os.path.join(data_dir, f".{DB_NAME}.restoring")
        with zipfile.ZipFile(path) as archive, archive.open(LIBRARY_FILE) as source, \
                open(staging, "wb") as copied:
            shutil.copyfileobj(source, copied, 1 << 20)
        try:
            clips = _check_library(staging)
        except BackupError:
            _remove(staging)
            raise
    moved_to = ""
    try:
        if any(key != LIBRARY for key in picks):
            moved_to = reset.discard(config_file or paths.config_path())
            config.save(config_file)
        if LIBRARY in picks:
            moved_to = reset.discard_library(data_dir) or moved_to
            os.replace(staging, os.path.join(data_dir, DB_NAME))
    except OSError as exc:
        _remove(staging)
        raise BackupError(f"Couldn't restore the backup: {exc}") from exc
    return Restored(config, tuple(picks), clips, left_out, moved_to)


def _folders_here(item, settings: Config, current: Config) -> bool:
    """Whether the folders `item` names are this computer's: the ones in use,
    or ones that are here."""
    for name in item.fields:
        wanted = paths.normalize(setting_groups.get(settings, name))
        if wanted and wanted != paths.normalize(setting_groups.get(current, name)) and \
                not os.path.isdir(wanted):
            return False
    return True


def _snapshot(database: str, target: str) -> int:
    """Copy the library as it is now, even while Vertex has it open. Returns
    how many clips it knows."""
    try:
        source = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            copy = sqlite3.connect(target)
            try:
                source.backup(copy)
                return copy.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
            finally:
                copy.close()
        finally:
            source.close()
    except sqlite3.Error as exc:
        raise BackupError(f"Couldn't read the library: {exc}") from exc


def _check_library(path: str) -> int:
    """How many clips the library at `path` knows; BackupError if it isn't
    one this Vertex can open."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise BackupError(f"The backup's library was made by a newer {APP_NAME}. "
                                  f"Update {APP_NAME} first.")
            return conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BackupError(f"The backup's library can't be read: {exc}") from exc


def _manifest(contents: Contents) -> dict:
    return {"format": FORMAT, "app": APP_NAME, "version": contents.version,
            "created": contents.created, "recorder": contents.recorder,
            "parts": list(contents.parts), "clips": contents.clips}


def _remove(path: str) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass
