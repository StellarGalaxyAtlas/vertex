"""Clips on disk: what a scan finds, and how the library orders and filters it.

Nothing here writes to the clips folder. Scanning only lists and stats files;
the user's recordings are never modified by indexing them.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from vertex import fmt
from vertex.core.naming import recorded_at

VIDEO_EXTENSIONS = (".mp4", ".mkv")


def is_clip(name: str) -> bool:
    """A finished recording — not a hidden staging file or a partial copy."""
    return not name.startswith(".") and name.lower().endswith(VIDEO_EXTENSIONS)


@dataclass
class Clip:
    """One clip file: its name in the clips folder, size and dates."""

    name: str
    size_bytes: int
    mtime: float = 0.0
    path: str = ""
    created: float = 0.0   # birth time where the platform exposes one, else mtime
    # When it was recorded: seeded from the name, then replaced by the
    # library's stored date once the clip has been indexed.
    recorded: float = 0.0

    def __post_init__(self):
        if not self.created:
            self.created = self.mtime

    @property
    def date(self) -> float:
        """When it was recorded, or failing that, its file's date.

        Copying a clip between folders or trimming it in place rewrites every
        date the filesystem keeps — but not the one in its name, nor the one the
        library stored the first time it saw the clip.
        """
        return self.recorded or self.created

    @property
    def size_human(self) -> str:
        return fmt.size(self.size_bytes)

    @property
    def age_human(self) -> str:
        return fmt.relative_time(self.date)


@dataclass
class ClipScan:
    clips: list[Clip] = field(default_factory=list)
    total_bytes: int = 0


def creation_time(stat_result: os.stat_result) -> float:
    """Best creation date a file offers; st_birthtime isn't exposed on Linux."""
    birth = getattr(stat_result, "st_birthtime", 0) or 0
    return birth or stat_result.st_mtime


def scan_clips(clip_dir: str) -> ClipScan:
    """List the recordings directly inside `clip_dir`, newest first.

    Subfolders are not descended into: exports and other apps' thumbnails live
    beside the recordings, and none of those are recordings.
    """
    scan = ClipScan()
    with os.scandir(clip_dir) as entries:
        for entry in entries:
            if not is_clip(entry.name):
                continue
            try:
                if not entry.is_file():
                    continue
                info = entry.stat()
            except OSError:
                continue   # vanished between listing and stat
            scan.clips.append(Clip(
                name=entry.name, size_bytes=info.st_size, mtime=info.st_mtime,
                path=entry.path, created=creation_time(info),
                recorded=recorded_at(entry.name),
            ))
            scan.total_bytes += info.st_size
    scan.clips = sort_clips(scan.clips)
    return scan


def sort_clips(clips: list[Clip], key: str = "date", descending: bool = True,
               games: dict[str, str] | None = None) -> list[Clip]:
    """`clips` ordered by recording date ("date") or game ("game").

    File name is the tie-break throughout, so a burst of recordings saved in
    the same second keeps a steady order instead of shuffling every rescan.
    `games` is {filename: game}; untagged clips sort to the end either way —
    they are the ones still to label, not the ones to bury in the middle.
    """
    ordered = sorted(clips, key=lambda clip: clip.name.casefold())
    if key == "date":
        ordered.sort(key=lambda clip: clip.date, reverse=descending)
    elif key == "game":
        lookup = games or {}
        # Two stable passes, so flipping the direction reverses the games
        # without dragging the unlabelled pile to the top.
        ordered.sort(key=lambda clip: (lookup.get(clip.name) or "").casefold(),
                     reverse=descending)
        ordered.sort(key=lambda clip: not lookup.get(clip.name))
    elif descending:
        ordered.reverse()
    return ordered


def filter_clips(clips: list[Clip], query: str,
                 tags: dict[str, tuple[str, list[str]]] | None = None,
                 titles: dict[str, str] | None = None) -> list[Clip]:
    """The clips matching `query` across game, people, title and file name.

    Every whitespace-separated word has to match somewhere, case-insensitively,
    so "finals anna" finds the Finals clips Anna is in, in either order.
    """
    words = query.casefold().split()
    if not words:
        return list(clips)
    tags = tags or {}
    titles = titles or {}
    matched = []
    for clip in clips:
        game, people = tags.get(clip.name, ("", []))
        haystack = " ".join([clip.name, titles.get(clip.name, ""), game, *people]).casefold()
        if all(word in haystack for word in words):
            matched.append(clip)
    return matched


def trimmed_copy_path(clip_path: str) -> str:
    """A free '<stem> (trimmed).mp4' name beside `clip_path`."""
    folder = os.path.dirname(os.path.abspath(clip_path))
    stem, ext = os.path.splitext(os.path.basename(clip_path))
    candidate = os.path.join(folder, f"{stem} (trimmed){ext}")
    count = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{stem} (trimmed {count}){ext}")
        count += 1
    return candidate


def staging_path(target: str, tag: str) -> str:
    """A hidden sibling of `target` to write into before moving it into place.

    Hidden, so a scan of the folder mid-write never lists it as a clip, and on
    the same filesystem, so the final move is an atomic rename.
    """
    folder = os.path.dirname(os.path.abspath(target))
    stem, ext = os.path.splitext(os.path.basename(target))
    return os.path.join(folder, f".{stem}.{tag}{ext}")


def disk_total(path: str) -> int:
    return shutil.disk_usage(path).total
