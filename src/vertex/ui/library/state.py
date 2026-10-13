"""What the library view shows: every clip, its tags, and the current filter.

One object owns the scan of the clips folder and the library's view of each
clip, so the rail, the grid and the editor never disagree about a title or a
tag. Edits go through here; it writes them to the library and tells every view.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from vertex import fmt
from vertex.core import clips as clips_mod
from vertex.core import storage
from vertex.core.clips import Clip


@dataclass
class Facet:
    kind: str = "all"       # all | favorites | game | person | untagged
    value: str = ""

    def title(self) -> str:
        return {"all": "All clips", "favorites": "Favorites",
                "untagged": "Untagged"}.get(self.kind, self.value)


class LibraryState(QObject):
    reset = Signal()                 # the visible list changed shape
    clip_changed = Signal(str)       # one clip's metadata changed (file name)
    counts_changed = Signal()        # games/people/favourites counts
    storage_changed = Signal(object)  # StorageStats
    status = Signal(str, str)        # text, level

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.all_clips: list[Clip] = []
        self.visible: list[Clip] = []
        self.tags: dict[str, tuple[str, list[str]]] = {}
        self.titles: dict[str, str] = {}
        self.favorites: set[str] = set()
        self.durations: dict[str, float] = {}
        self.query = ""
        self.facet = Facet()
        self.sort_key = "date"
        self.descending = True
        self.error = ""

    @property
    def library(self):
        return self.context.library

    # --- Loading ------------------------------------------------------------

    def reload(self) -> None:
        """Rescan the clips folder and re-read the library."""
        folder = self.context.config.resolved_clip_dir()
        self.error = ""
        try:
            scan = clips_mod.scan_clips(folder) if folder else clips_mod.ClipScan()
        except OSError as exc:
            scan = clips_mod.ClipScan()
            self.error = f"Could not read {folder}: {exc}"
        self.all_clips = scan.clips
        tagged = self._index()
        self._load_metadata()
        self._refilter()
        self.counts_changed.emit()
        self.refresh_storage()
        if tagged:
            self.status.emit(f"Tagged {fmt.plural(tagged, 'clip')} from their file names", "info")

    def _index(self) -> int:
        """Settle each clip's game and recording date in the library, once."""
        if self.library is None or not self.all_clips:
            return 0
        try:
            tagged = self.library.autotag_games([clip.name for clip in self.all_clips])
            self.library.store_recorded(
                {clip.name: clip.recorded or clip.created for clip in self.all_clips})
            dates = self.library.recorded_dates()
        except sqlite3.Error:
            return 0
        for clip in self.all_clips:
            clip.recorded = dates.get(clip.name) or clip.recorded
        return len(tagged)

    def _load_metadata(self) -> None:
        if self.library is None:
            self.tags, self.titles, self.favorites, self.durations = {}, {}, set(), {}
            return
        try:
            self.tags = self.library.tags()
            self.titles = self.library.titles()
            self.favorites = self.library.favorites()
            self.durations = self.library.durations()
        except sqlite3.Error:
            self.tags, self.titles, self.favorites, self.durations = {}, {}, set(), {}

    def refresh_storage(self) -> None:
        folder = self.context.config.resolved_clip_dir()
        try:
            self.storage_changed.emit(storage.storage_stats(folder))
        except OSError:
            pass

    # --- Filtering ----------------------------------------------------------

    def _in_facet(self, clip: Clip) -> bool:
        kind, value = self.facet.kind, self.facet.value
        if kind == "favorites":
            return clip.name in self.favorites
        game, people = self.tags.get(clip.name, ("", []))
        if kind == "game":
            return game == value
        if kind == "person":
            return value.casefold() in (p.casefold() for p in people)
        if kind == "untagged":
            return not game
        return True

    def _refilter(self) -> None:
        clips = [clip for clip in self.all_clips if self._in_facet(clip)]
        clips = clips_mod.filter_clips(clips, self.query, self.tags, self.titles)
        games = {name: game for name, (game, _people) in self.tags.items()}
        self.visible = clips_mod.sort_clips(clips, self.sort_key, self.descending, games)
        self.reset.emit()

    def set_query(self, text: str) -> None:
        if text != self.query:
            self.query = text
            self._refilter()

    def set_facet(self, facet: Facet) -> None:
        self.facet = facet
        self._refilter()

    def set_sort(self, key: str, descending: bool) -> None:
        self.sort_key, self.descending = key, descending
        self._refilter()

    # --- Lookups ------------------------------------------------------------

    def title_of(self, clip: Clip) -> str:
        return self.titles.get(clip.name) or clip.name

    def tags_of(self, clip: Clip) -> tuple[str, list[str]]:
        return self.tags.get(clip.name, ("", []))

    def find(self, name: str) -> Clip | None:
        return next((clip for clip in self.all_clips if clip.name == name), None)

    def games(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        present = {clip.name for clip in self.all_clips}
        for name, (game, _people) in self.tags.items():
            if game and name in present:
                counts[game] = counts.get(game, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))

    def people(self) -> list[tuple[str, int]]:
        counts: dict[str, tuple[str, int]] = {}
        present = {clip.name for clip in self.all_clips}
        for name, (_game, people) in self.tags.items():
            if name not in present:
                continue
            for person in people:
                display, count = counts.get(person.casefold(), (person, 0))
                counts[person.casefold()] = (display, count + 1)
        return sorted(counts.values(), key=lambda kv: (-kv[1], kv[0].casefold()))

    def favorite_count(self) -> int:
        present = {clip.name for clip in self.all_clips}
        return len(self.favorites & present)

    def untagged_count(self) -> int:
        return sum(1 for clip in self.all_clips if not self.tags.get(clip.name, ("",))[0])

    # --- Edits --------------------------------------------------------------

    def set_title(self, clip: Clip, title: str) -> str:
        title = title.strip()
        stored = "" if title in ("", clip.name) else title
        if self.library is not None:
            self.library.set_title(clip.name, stored)
        if stored:
            self.titles[clip.name] = stored
        else:
            self.titles.pop(clip.name, None)
        self.clip_changed.emit(clip.name)
        return stored or clip.name

    def set_tags(self, clip: Clip, game: str, people: list[str]) -> tuple[str, list[str]]:
        if self.library is None:
            return game, people
        game, people = self.library.set_tags(clip.name, game, people)
        if game or people:
            self.tags[clip.name] = (game, people)
        else:
            self.tags.pop(clip.name, None)
        self.counts_changed.emit()
        if self.facet.kind in ("game", "person", "untagged") or self.sort_key == "game":
            self._refilter()
        else:
            self.clip_changed.emit(clip.name)
        return game, people

    def toggle_favorite(self, clip: Clip) -> bool:
        favorite = clip.name not in self.favorites
        if self.library is not None:
            self.library.set_favorite(clip.name, favorite)
        if favorite:
            self.favorites.add(clip.name)
        else:
            self.favorites.discard(clip.name)
        self.counts_changed.emit()
        if self.facet.kind == "favorites":
            self._refilter()
        else:
            self.clip_changed.emit(clip.name)
        return favorite

    def set_duration(self, clip_path: str, seconds: float) -> None:
        name = os.path.basename(clip_path)
        if seconds <= 0 or self.durations.get(name) == seconds:
            return
        self.durations[name] = seconds
        if self.library is not None:
            try:
                self.library.set_duration(name, seconds)
            except sqlite3.Error:
                pass
        self.clip_changed.emit(name)

    def delete(self, clip: Clip) -> str:
        """Delete a clip's file (to the Trash when possible) and its edits."""
        if self.context.thumbs is not None:
            self.context.thumbs.discard(clip.path)   # keyed on the file's mtime
        try:
            trashed = storage.delete_file(clip.path)
        except OSError as exc:
            self.status.emit(f"Could not delete {clip.name}: {exc}", "error")
            return ""
        if self.library is not None:
            self.library.forget(clip.name)
        self.all_clips = [c for c in self.all_clips if c.name != clip.name]
        self.tags.pop(clip.name, None)
        self.favorites.discard(clip.name)
        self._refilter()
        self.counts_changed.emit()
        self.refresh_storage()
        verb = "Moved to Trash" if trashed else "Deleted"
        self.status.emit(f"{verb}: {clip.name}", "ok")
        return verb

    def replace_with_trim(self, clip: Clip, trimmed_path: str) -> bool:
        """Swap a clip's file for its trimmed version, keeping name and edits."""
        if self.context.thumbs is not None:
            self.context.thumbs.discard(clip.path)
        try:
            trashed = storage.delete_file(clip.path)
        except OSError as exc:
            self.status.emit(f"Could not replace {clip.name}: {exc}", "error")
            return False
        try:
            os.replace(trimmed_path, clip.path)
        except OSError as exc:
            # The original is already gone; keep the trim under a visible name.
            salvage = clips_mod.trimmed_copy_path(clip.path)
            try:
                os.replace(trimmed_path, salvage)
            except OSError:
                salvage = trimmed_path
            self.reload()
            self.status.emit(f"Trim saved as {os.path.basename(salvage)} — could not take "
                             f"over the original name: {exc}", "error")
            return False
        if self.library is not None:
            self.library.clear_trim(clip.name)
        self.reload()
        where = "moved to Trash" if trashed else "deleted"
        self.status.emit(f"Trimmed {clip.name} · original {where}", "ok")
        return True
