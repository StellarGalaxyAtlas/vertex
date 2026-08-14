"""Thumbnail generation and caching.

Frames are extracted with ffmpeg on a background thread pool so the GUI never
blocks, then cached as JPEGs under the cache dir. The cache key includes the
file's mtime and size, so a re-recorded clip with the same name regenerates.
"""

import glob
import hashlib
import os
import queue
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

# Seek this far in before grabbing a frame, to skip black intro frames.
SEEK_SECONDS = 1.0
THUMB_WIDTH = 480

# Hover preview: this many evenly-spaced frames spanning the whole clip.
PREVIEW_FRAMES = 20
PREVIEW_WIDTH = 480


# How often the main thread drains finished background jobs.
POLL_MS = 40


class ThumbnailService:
    def __init__(self, cache_dir, tk_root, max_workers=3):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        # Worker threads must not touch Tk. They drop (callback, result) here,
        # and a main-thread poller invokes the callbacks safely.
        self._results = queue.Queue()
        self._root = tk_root
        self._alive = True
        # Outstanding ffmpeg/ffprobe jobs, so a view can tell the user when the
        # processing a refresh kicked off has actually finished. Hover previews
        # are deliberately left out: those are the user's own doing, and the
        # count is meant to describe the work a reload set in motion.
        self._outstanding = 0
        self._count_lock = threading.Lock()
        self._root.after(POLL_MS, self._poll)

    @property
    def pending(self):
        """How many thumbnail/duration jobs are still queued or running."""
        with self._count_lock:
            return self._outstanding

    def _track(self, future):
        """Count `future` as outstanding until it settles, whatever it does."""
        with self._count_lock:
            self._outstanding += 1

        def settled(_fut):
            with self._count_lock:
                self._outstanding -= 1

        future.add_done_callback(settled)

    def _poll(self):
        if not self._alive:
            return
        while True:
            try:
                callback, result = self._results.get_nowait()
            except queue.Empty:
                break
            try:
                callback(result)
            except Exception:
                pass  # a dead widget or bad callback must not kill the poller
        if self._alive and self._root.winfo_exists():
            self._root.after(POLL_MS, self._poll)

    def _dispatch(self, callback, result):
        """Hand a result to the main thread. Safe to call from any thread."""
        self._results.put((callback, result))

    def _digest(self, clip_path):
        """Cache key from path + mtime + size, so a re-recording invalidates it."""
        try:
            stat = os.stat(clip_path)
            key = f"{os.path.abspath(clip_path)}:{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            key = os.path.abspath(clip_path)
        return hashlib.sha1(key.encode()).hexdigest()

    def path_for(self, clip_path):
        """Deterministic thumbnail cache path (independent of existence)."""
        return os.path.join(self.cache_dir, f"{self._digest(clip_path)}.jpg")

    def preview_dir_for(self, clip_path):
        """Directory holding this clip's cached hover-preview frames."""
        return os.path.join(self.cache_dir, "previews", self._digest(clip_path))

    def discard(self, clip_path):
        """Drop this clip's cached thumbnail and preview frames.

        Call this *before* deleting the clip: the cache key is derived from the
        file's mtime and size, so once the file is gone the digest changes and
        the old entries can no longer be found.
        """
        try:
            os.remove(self.path_for(clip_path))
        except OSError:
            pass  # never cached, or already gone
        shutil.rmtree(self.preview_dir_for(clip_path), ignore_errors=True)

    def request(self, clip_path, callback):
        """Resolve a thumbnail for clip_path, calling callback(path_or_None).

        The callback always runs on the Tk main thread (via the poller), so it is
        safe to touch widgets from it. Cached hits are dispatched the same way,
        so the caller can treat every path uniformly.
        """
        thumb = self.path_for(clip_path)
        if os.path.exists(thumb):
            self._dispatch(callback, thumb)
            return

        future = self._pool.submit(self._generate, clip_path, thumb)
        self._track(future)

        def done(fut):
            if fut.cancelled():  # pool cancels pending futures on shutdown
                return
            try:
                success = fut.result()
            except Exception:
                success = False
            self._dispatch(callback, thumb if success else None)

        future.add_done_callback(done)

    def _generate(self, clip_path, thumb_path):
        """Run ffmpeg to extract one scaled frame. Returns True on success."""
        if FFMPEG is None or not os.path.exists(clip_path):
            return False
        tmp = thumb_path + ".tmp.jpg"
        cmd = [
            FFMPEG, "-y", "-loglevel", "error",
            "-ss", str(SEEK_SECONDS), "-i", clip_path,
            "-frames:v", "1",
            "-vf", f"scale={THUMB_WIDTH}:-2",
            tmp,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.replace(tmp, thumb_path)  # atomic: never leave a partial jpg
            return True
        except (subprocess.SubprocessError, OSError):
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False

    # --- Hover preview frames ---------------------------------------------

    def request_preview(self, clip_path, callback):
        """Resolve preview frames for a clip, calling callback(list_of_paths).

        Frames are cached on disk, so a re-hover reuses them without regenerating.
        The callback runs on the Tk main thread; an empty list means unavailable.
        """
        out_dir = self.preview_dir_for(clip_path)
        cached = self._existing_frames(out_dir)
        if cached:
            self._dispatch(callback, cached)
            return

        future = self._pool.submit(self._generate_preview, clip_path, out_dir)

        def done(fut):
            if fut.cancelled():
                return
            try:
                frames = fut.result()
            except Exception:
                frames = []
            self._dispatch(callback, frames)

        future.add_done_callback(done)

    def request_duration(self, clip_path, callback):
        """Probe a clip's duration off-thread; callback(seconds_or_None) on main."""
        future = self._pool.submit(self._probe_duration, clip_path)
        self._track(future)

        def done(fut):
            if fut.cancelled():
                return
            try:
                seconds = fut.result()
            except Exception:
                seconds = None
            self._dispatch(callback, seconds)

        future.add_done_callback(done)

    @staticmethod
    def _existing_frames(out_dir):
        if not os.path.isdir(out_dir):
            return []
        return sorted(glob.glob(os.path.join(out_dir, "frame_*.jpg")))

    def _probe_duration(self, clip_path):
        if FFPROBE is None:
            return None
        cmd = [
            FFPROBE, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", clip_path,
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return float(out.stdout.strip())
        except (ValueError, subprocess.SubprocessError):
            return None

    def _generate_preview(self, clip_path, out_dir):
        """Extract PREVIEW_FRAMES evenly-spaced frames spanning the clip."""
        if FFMPEG is None or not os.path.exists(clip_path):
            return []
        duration = self._probe_duration(clip_path)
        if not duration or duration <= 0:
            return []

        # Build into a temp dir, then atomically swap in — never expose partial.
        tmp = out_dir + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        fps = PREVIEW_FRAMES / duration
        cmd = [
            FFMPEG, "-y", "-loglevel", "error", "-i", clip_path,
            "-vf", f"fps={fps:.6f},scale={PREVIEW_WIDTH}:-2",
            "-frames:v", str(PREVIEW_FRAMES),
            os.path.join(tmp, "frame_%02d.jpg"),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=90,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError, OSError):
            shutil.rmtree(tmp, ignore_errors=True)
            return []

        if not glob.glob(os.path.join(tmp, "frame_*.jpg")):
            shutil.rmtree(tmp, ignore_errors=True)
            return []
        os.makedirs(os.path.dirname(out_dir), exist_ok=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        os.replace(tmp, out_dir)
        return self._existing_frames(out_dir)

    def shutdown(self):
        self._alive = False  # stop the poller from rescheduling
        self._pool.shutdown(wait=False, cancel_futures=True)
