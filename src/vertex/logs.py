"""What Vertex did, written down in plain-text files in the log folder.

One file per part of the app, so a problem with the recorder isn't buried
under clip saves:

    vertex.log      the app itself: starting, quitting, settings, commands
                    from shortcuts and scripts, errors
    recorder.log    the replay buffer and the recorder's own output
    clips.log       the library: clips saved, tagged, trimmed, exported, deleted

Every line starts with the time and how serious it is, so the files read in
any text editor, `less` or `tail -f`. A file that reaches MAX_BYTES starts
over, keeping the previous BACKUPS as `.1` and `.2`: no part of Vertex ever
holds more than about 6 MB of logs.

Modules log to the logger of their part (`logs.CLIPS.info(...)`). Nothing is
written anywhere until `setup` names a folder, which only the running app
does, and only while Keep logs is on in Settings: a `vertex save-clip` from a
hotkey leaves the files alone.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

from vertex import APP_NAME, __version__, paths

MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 2

FORMAT = "%(asctime)s  %(levelname)-7s  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# The parts of Vertex, by logger, and the file each writes to.
FILES = {
    "vertex.app": "vertex.log",
    "vertex.recorder": "recorder.log",
    "vertex.clips": "clips.log",
}

APP = logging.getLogger("vertex.app")
RECORDER = logging.getLogger("vertex.recorder")
CLIPS = logging.getLogger("vertex.clips")

_root = logging.getLogger("vertex")
_root.addHandler(logging.NullHandler())   # quiet until set up, as a library should be
_root.setLevel(logging.INFO)

_handlers: dict[str, RotatingFileHandler] = {}
_folder = ""
_enabled: bool | None = None     # what `apply` was last told; None before it was
_hooked = False


def apply(enabled: bool, path: str) -> str:
    """Logs on in `path`, or off; what the settings say. Returns the folder in
    use ("" while off)."""
    global _enabled
    was, _enabled = _enabled, enabled
    if not enabled:
        if _folder:
            APP.info("Logging turned off")
        shutdown()
        return ""
    used = setup(path)
    if was is False and used:
        APP.info("Logging turned on")
    return used


def folder() -> str:
    """The folder the logs are written to now, or "" before `setup`."""
    return _folder


def setup(path: str) -> str:
    """Write the logs to `path` from now on (creating it). Returns the folder
    in use: `path`, or "" if it can't be written to, in which case nothing is
    logged to files until a later call names one that can."""
    global _folder
    path = os.path.abspath(os.path.expanduser(path))
    if path == _folder:
        return _folder
    try:
        paths.make_dir(path)
        opened = {name: _handler(os.path.join(path, file)) for name, file in FILES.items()}
    except OSError as exc:
        APP.error("Couldn't write logs to %s: %s", path, exc)
        return _folder
    previous = _folder
    _close()
    for name, handler in opened.items():
        logging.getLogger(name).addHandler(handler)
    _handlers.update(opened)
    _folder = path
    _hook_exceptions()
    if previous:
        APP.info("Log folder moved here from %s", previous)
    return _folder


def started(pid: int | None = None) -> None:
    """Mark a new run at the top of every file, so runs are easy to tell apart."""
    for name in FILES:
        logging.getLogger(name).info("%s %s started (pid %d)", APP_NAME, __version__,
                                     pid or os.getpid())


def shutdown() -> None:
    """Flush and close the files (the app is quitting)."""
    global _folder
    _close()
    _folder = ""


def _handler(file: str) -> RotatingFileHandler:
    handler = RotatingFileHandler(file, maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
    return handler


def _close() -> None:
    for name, handler in _handlers.items():
        logging.getLogger(name).removeHandler(handler)
        handler.close()
    _handlers.clear()


def _hook_exceptions() -> None:
    """Crashes land in vertex.log too, and still print as they did before."""
    global _hooked
    if _hooked:
        return
    _hooked = True
    previous_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    def hook(kind, value, trace):
        if not issubclass(kind, KeyboardInterrupt):
            APP.error("Unexpected error", exc_info=(kind, value, trace))
        previous_hook(kind, value, trace)

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            name = args.thread.name if args.thread is not None else "a thread"
            APP.error("Unexpected error in %s", name,
                      exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        previous_thread_hook(args)

    sys.excepthook = hook
    threading.excepthook = thread_hook
