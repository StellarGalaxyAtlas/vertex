"""Putting Vertex back to the start: its settings and its library.

Never the clips. Each file goes to the desktop Trash or, where there is none,
is renamed to a dated backup beside it: either way it can be brought back.
"""

from __future__ import annotations

import copy
import dataclasses
import os
import time

from vertex import paths
from vertex.core import storage
from vertex.library.database import DB_NAME

# SQLite keeps a journal beside the database while it is open or was cut off.
LIBRARY_FILES = (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm", f"{DB_NAME}-journal")


def discard(path: str | os.PathLike) -> str:
    """Move a file out of the way, recoverably. Returns where it went ("" if it
    wasn't there). Raises OSError if it could be neither trashed nor renamed."""
    path = os.fspath(path)
    if not os.path.exists(path):
        return ""
    if storage.trash_available():
        try:
            storage.send2trash(path)
            return "the Trash"
        except OSError:
            pass         # no Trash on this volume: keep a backup instead
    backup = f"{path}.{time.strftime('%Y-%m-%d-%H%M%S')}.bak"
    os.replace(path, backup)
    return backup


def discard_settings() -> str:
    return discard(paths.config_path())


def discard_library(data_dir: str) -> str:
    """The library database and its journal. Close it first."""
    places = [discard(os.path.join(data_dir, name)) for name in LIBRARY_FILES]
    return places[0]


def reset_in_place(target, fresh) -> None:
    """Make dataclass `target` equal `fresh`, keeping the objects it is made of:
    the rest of the app holds on to them (the recorder to its settings, say)."""
    for item in dataclasses.fields(target):
        value, new = getattr(target, item.name), getattr(fresh, item.name)
        if dataclasses.is_dataclass(value) and type(value) is type(new):
            reset_in_place(value, new)
        else:
            setattr(target, item.name, copy.deepcopy(new))
