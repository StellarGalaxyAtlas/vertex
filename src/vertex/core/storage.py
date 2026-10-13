"""Disk usage of the clips folder, and deleting a clip recoverably."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from vertex import fmt
from vertex.core.clips import is_clip

try:
    from send2trash import send2trash
except ImportError:  # pragma: no cover - it is a declared dependency
    send2trash = None


@dataclass
class StorageStats:
    """Disk usage of the filesystem holding the clips, and the clips' share."""

    clips_bytes: int = 0
    disk_total: int = 0
    disk_used: int = 0
    disk_free: int = 0

    @property
    def other_used(self) -> int:
        """Bytes used by everything on the disk that isn't a clip."""
        return max(0, self.disk_used - self.clips_bytes)

    def fraction(self, value: int) -> float:
        return value / self.disk_total if self.disk_total else 0.0

    @property
    def clips_human(self) -> str:
        return fmt.size(self.clips_bytes)

    @property
    def free_human(self) -> str:
        return fmt.size(self.disk_free)

    @property
    def other_human(self) -> str:
        return fmt.size(self.other_used)

    @property
    def total_human(self) -> str:
        return fmt.size(self.disk_total)


def storage_stats(clip_dir: str) -> StorageStats:
    """Size of the clips in `clip_dir` and usage of the disk it is on.

    Measured on the clips' own filesystem: a clips folder on a second drive
    would otherwise be reported against a disk it has nothing to do with.
    """
    clips_bytes = 0
    target = "/"
    if clip_dir and os.path.isdir(clip_dir):
        target = clip_dir
        with os.scandir(clip_dir) as entries:
            for entry in entries:
                if is_clip(entry.name):
                    try:
                        clips_bytes += entry.stat().st_size
                    except OSError:
                        pass
    usage = shutil.disk_usage(target)
    return StorageStats(clips_bytes=clips_bytes, disk_total=usage.total,
                        disk_used=usage.used, disk_free=usage.free)


def trash_available() -> bool:
    return send2trash is not None


def delete_file(path: str) -> bool:
    """Delete a file, preferring the desktop Trash so it stays recoverable.

    Returns True if it went to the Trash, False if it had to be removed for
    good (a volume with no usable trash dir — some removable and network
    mounts). Raises OSError if it could not be removed at all.
    """
    if send2trash is not None:
        try:
            send2trash(path)
            return True
        except OSError:
            pass   # no trash here; fall through to a real delete
    os.remove(path)
    return False
