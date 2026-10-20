"""Thumbnails and hover-preview frames, cached on disk.

Blocking functions only — the UI decides which thread runs them. The cache key
includes the file's mtime and size, so a clip re-recorded under the same name
regenerates by itself.
"""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import subprocess

from vertex.media.ffmpeg import BASE
from vertex.media.probe import duration as probe_duration
from vertex.system import NO_WINDOW

SEEK_SECONDS = 1.0      # skip the black intro frame most recordings open on
THUMB_WIDTH = 960       # sharp on the library's largest cards
PREVIEW_FRAMES = 20
PREVIEW_WIDTH = 960


class ThumbnailCache:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self.thumb_dir = os.path.join(cache_dir, "thumbnails")
        self.preview_root = os.path.join(cache_dir, "previews")
        os.makedirs(self.thumb_dir, exist_ok=True)

    @staticmethod
    def digest(clip_path: str) -> str:
        try:
            stat = os.stat(clip_path)
            key = f"{os.path.abspath(clip_path)}:{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            key = os.path.abspath(clip_path)
        # The image sizes are part of the key: images of another size are made
        # again when next shown, and prune() drops the old ones.
        key += f":{THUMB_WIDTH}:{PREVIEW_WIDTH}"
        return hashlib.sha1(key.encode()).hexdigest()

    def thumb_path(self, clip_path: str) -> str:
        return os.path.join(self.thumb_dir, f"{self.digest(clip_path)}.jpg")

    def preview_dir(self, clip_path: str) -> str:
        return os.path.join(self.preview_root, self.digest(clip_path))

    # --- Thumbnails ----------------------------------------------------------

    def cached_thumbnail(self, clip_path: str) -> str | None:
        path = self.thumb_path(clip_path)
        return path if os.path.exists(path) else None

    def thumbnail(self, clip_path: str) -> str | None:
        """The clip's thumbnail, generating it if needed. Blocking."""
        target = self.thumb_path(clip_path)
        if os.path.exists(target):
            return target
        if not os.path.exists(clip_path):
            return None
        tmp = f"{target}.tmp.jpg"
        # A clip shorter than the seek has no frame there; fall back to the first.
        for seek in (SEEK_SECONDS, 0.0):
            argv = [*BASE, "-v", "error", "-y", "-ss", str(seek), "-i", clip_path,
                    "-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", tmp]
            try:
                subprocess.run(argv, check=True, timeout=30,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **NO_WINDOW)
                if os.path.getsize(tmp) > 0:
                    os.replace(tmp, target)      # never leave a partial JPEG
                    return target
            except (subprocess.SubprocessError, OSError):
                pass
        _remove(tmp)
        return None

    # --- Hover previews ----------------------------------------------------

    def cached_preview(self, clip_path: str) -> list[str]:
        return _frames(self.preview_dir(clip_path))

    def preview(self, clip_path: str, duration: float | None = None) -> list[str]:
        """PREVIEW_FRAMES evenly spaced frames spanning the clip. Blocking."""
        out_dir = self.preview_dir(clip_path)
        cached = _frames(out_dir)
        if cached or not os.path.exists(clip_path):
            return cached
        duration = duration or probe_duration(clip_path)
        if not duration:
            return []
        tmp = f"{out_dir}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        argv = [*BASE, "-v", "error", "-y", "-i", clip_path,
                "-vf", f"fps={PREVIEW_FRAMES / duration:.6f},scale={PREVIEW_WIDTH}:-2",
                "-frames:v", str(PREVIEW_FRAMES), os.path.join(tmp, "frame_%02d.jpg")]
        try:
            subprocess.run(argv, check=True, timeout=90,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **NO_WINDOW)
        except (subprocess.SubprocessError, OSError):
            shutil.rmtree(tmp, ignore_errors=True)
            return []
        if not _frames(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
            return []
        shutil.rmtree(out_dir, ignore_errors=True)
        os.replace(tmp, out_dir)
        return _frames(out_dir)

    # --- Housekeeping -------------------------------------------------------

    def discard(self, clip_path: str) -> None:
        """Drop a clip's cached images. Call before deleting or replacing the
        file: once it changes, its digest does too and these are unreachable."""
        _remove(self.thumb_path(clip_path))
        shutil.rmtree(self.preview_dir(clip_path), ignore_errors=True)

    def clear(self) -> None:
        """Delete every cached image. Only the cache's own folders: the cache
        folder itself may be anywhere, shared with anything."""
        for folder in (self.thumb_dir, self.preview_root):
            shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(self.thumb_dir, exist_ok=True)

    def prune(self, clip_paths) -> int:
        """Delete cached images for clips that no longer exist. Returns count."""
        keep = {self.digest(path) for path in clip_paths}
        removed = 0
        for entry in glob.glob(os.path.join(self.thumb_dir, "*.jpg")):
            if os.path.splitext(os.path.basename(entry))[0] not in keep:
                _remove(entry)
                removed += 1
        if os.path.isdir(self.preview_root):
            for name in os.listdir(self.preview_root):
                if name not in keep:
                    shutil.rmtree(os.path.join(self.preview_root, name), ignore_errors=True)
                    removed += 1
        return removed


def _frames(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(glob.glob(os.path.join(folder, "frame_*.jpg")))


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
