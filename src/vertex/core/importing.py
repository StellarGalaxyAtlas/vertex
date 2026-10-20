"""Bringing an existing recording library in.

Two separate steps, each worked out in full before anything is written so the
user can see it and change their mind:

* a CopyPlan copies recordings from another folder into the clips folder;
* an ImportPlan tags clips with the games their file names record.

Reading the names of the clips already in the library again, after an app
or a game name was added, is worked out the same way (plan_reread).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field

from vertex import fmt
from vertex.core.clips import is_clip
from vertex.core.naming import fixed_name, game_from_filename, game_key, recorded_at
from vertex.logs import CLIPS as log

COPY_CHUNK = 4 * 1024 * 1024          # read/write size for a single clip
COPY_REPORT_EVERY = 8 * 1024 * 1024   # how much must land before reporting again


@dataclass
class CopyFolder:
    """A folder under the source holding recordings: "" is the source itself."""

    path: str
    clips: int = 0
    bytes: int = 0


@dataclass
class CopyPlan:
    """Which recordings a copy would bring in, and what that would cost.

    Every recording under `source` is found, in subfolders too (Moments and
    Medal keep a folder per game); they all land side by side in `target`.
    `folders` lists where they were found, and `leave_out` drops folders
    from the copy (another app's exports, say)."""

    source: str = ""
    target: str = ""
    files: list[tuple[str, int]] = field(default_factory=list)   # (path under source, bytes)
    present: list[str] = field(default_factory=list)             # already there
    total_bytes: int = 0
    free_bytes: int = 0
    folders: list[CopyFolder] = field(default_factory=list)
    left_out: set[str] = field(default_factory=set)              # paths of folders
    _found: list[tuple[str, int]] = field(default_factory=list, repr=False)
    _existing: set[str] = field(default_factory=set, repr=False)

    @property
    def fits(self) -> bool:
        """Whether the target volume has room, with a little to spare."""
        return self.free_bytes >= self.total_bytes * 1.02

    @property
    def total_human(self) -> str:
        return fmt.size(self.total_bytes)

    @property
    def free_human(self) -> str:
        return fmt.size(self.free_bytes)

    @property
    def found(self) -> int:
        """Recordings found, in every folder."""
        return len(self._found)

    def leave_out(self, folders) -> None:
        """Copy everything but the recordings in `folders` (CopyFolder paths)."""
        self.left_out = set(folders)
        self.files, self.present, self.total_bytes = [], [], 0
        taken = set(self._existing)
        for path, size in self._found:
            if os.path.dirname(path) in self.left_out:
                continue
            # One clips folder: a name taken there, or by a clip in an
            # earlier folder, is left alone.
            name = os.path.basename(path)
            if name in taken:
                self.present.append(path)
                continue
            taken.add(name)
            self.files.append((path, size))
            self.total_bytes += size


def plan_copy(source: str, target: str) -> CopyPlan:
    """Work out which recordings would be copied from `source` and the
    folders under it into `target`.

    A name already in the target is left alone — re-running an import must
    never clobber a clip that has been edited since. Hidden folders, and the
    target itself if it lies under `source`, aren't read.
    """
    existing = set(os.listdir(target)) if os.path.isdir(target) else set()
    plan = CopyPlan(source=source, target=target, _existing=existing)
    skip = os.path.realpath(target)

    def visit(folder: str) -> None:
        here = CopyFolder(os.path.relpath(folder, source) if folder != source else "")
        subfolders = []
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda e: e.name.lower()):
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not entry.name.startswith(".") and \
                                os.path.realpath(entry.path) != skip:
                            subfolders.append(entry.path)
                        continue
                    if not is_clip(entry.name):
                        continue
                    size = entry.stat().st_size
                except OSError:
                    continue
                plan._found.append((os.path.join(here.path, entry.name), size))
                here.clips += 1
                here.bytes += size
        if here.clips:
            plan.folders.append(here)
        for path in subfolders:
            try:
                visit(path)
            except OSError as exc:
                log.warning("Couldn't read %s: %s", path, exc)

    visit(source)
    plan.leave_out(())
    # A clips folder chosen during setup doesn't exist yet; the space that
    # counts is on the drive it will be created on.
    existing_parent = os.path.abspath(target)
    while not os.path.isdir(existing_parent) and \
            os.path.dirname(existing_parent) != existing_parent:
        existing_parent = os.path.dirname(existing_parent)
    if os.path.isdir(existing_parent):
        plan.free_bytes = shutil.disk_usage(existing_parent).free
    return plan


def _copy_file(source: str, target: str, on_bytes: Callable[[int], None] | None) -> int:
    """Copy one file in chunks, reporting progress; then copy its metadata."""
    written = since_report = 0
    with open(source, "rb") as src, open(target, "wb") as dst:
        while chunk := src.read(COPY_CHUNK):
            dst.write(chunk)
            written += len(chunk)
            since_report += len(chunk)
            if on_bytes is not None and since_report >= COPY_REPORT_EVERY:
                since_report = 0
                on_bytes(written)
    shutil.copystat(source, target)
    return written


def copy_clips(plan: CopyPlan,
               on_progress: Callable[[int, str, int], None] | None = None,
               cancelled: Callable[[], bool] | None = None,
               ) -> tuple[list[str], list[tuple[str, str]]]:
    """Carry out a CopyPlan. Returns (copied names, [(name, error)]).

    Each clip is written under a temporary name and moved into place only once
    whole, so an interrupted copy never leaves a half-written file looking like
    a recording. `on_progress(index, name, done_bytes)` reports as it goes;
    `cancelled()` is checked before each file.
    """
    copied: list[str] = []
    failed: list[tuple[str, str]] = []
    log.info("Importing %s from %s into %s", fmt.plural(len(plan.files), "clip"), plan.source,
             plan.target)
    try:
        os.makedirs(plan.target, exist_ok=True)
    except OSError as err:
        log.error("Couldn't create %s: %s", plan.target, err)
        return copied, [(os.path.basename(path), str(err)) for path, _size in plan.files]
    done_bytes = 0
    for index, (path, size) in enumerate(plan.files, start=1):
        if cancelled is not None and cancelled():
            break
        name = os.path.basename(path)
        source = os.path.join(plan.source, path)
        target = os.path.join(plan.target, name)
        partial = os.path.join(plan.target, f".{name}.part")
        settled = done_bytes
        try:
            _copy_file(source, partial, None if on_progress is None else (
                lambda written, i=index, n=name, s=settled: on_progress(i, n, s + written)))
            os.replace(partial, target)
            copied.append(name)
            done_bytes = settled + size
        except OSError as err:
            log.error("Couldn't import %s: %s", source, err)
            failed.append((name, str(err)))
            done_bytes = settled
            try:
                os.remove(partial)
            except OSError:
                pass
        if on_progress is not None:
            on_progress(index, name, done_bytes)
    log.info("Imported %s%s", fmt.plural(len(copied), "clip"),
             f", {len(failed)} failed" if failed else "")
    return copied, failed


@dataclass
class ImportPlan:
    """What tagging a folder would do, worked out before anything is written."""

    folder: str = ""
    games: dict[str, list[str]] = field(default_factory=dict)  # derived game → files
    stored_as: dict[str, str] = field(default_factory=dict)    # derived game → tag to write
    strays: list[str] = field(default_factory=list)            # names carrying no game
    already: list[str] = field(default_factory=list)           # clips already tagged
    dates: dict[str, float] = field(default_factory=dict)      # file → recorded timestamp

    @property
    def clip_count(self) -> int:
        return self.taggable + len(self.strays) + len(self.already)

    @property
    def taggable(self) -> int:
        return sum(len(names) for names in self.games.values())

    def assignments(self, overrides: dict[str, str] | None = None) -> dict[str, str]:
        """{filename: game} to write, with the user's edits applied per game."""
        stored = {**self.stored_as, **(overrides or {})}
        return {name: stored.get(game, game)
                for game, names in self.games.items() for name in names}


def plan_import(folder: str, known_games=(), tagged=(), patterns=None,
                names=None) -> ImportPlan:
    """Work out what tagging `folder` would do, touching nothing.

    `known_games` are tags already in use, so a derived game landing on one
    keeps the spelling in use; `tagged` are clips that already carry a game;
    `patterns` read the names (by default the ones taught); `names` are the
    user's game names, applied first.
    """
    known = {game_key(game): game for game in known_games}
    tagged = set(tagged)
    plan = ImportPlan(folder=folder)
    for name in sorted(os.listdir(folder)):
        if not is_clip(name):
            continue
        when = recorded_at(name, patterns)
        if when:
            plan.dates[name] = when
        if name in tagged:
            plan.already.append(name)
            continue
        game = game_from_filename(name, patterns)
        if not game:
            plan.strays.append(name)
            continue
        plan.games.setdefault(game, []).append(name)
    fixed = {game: fixed_name(game, names or {}) for game in plan.games}
    plan.stored_as = {game: known.get(game_key(fixed[game]), fixed[game]) for game in plan.games}
    return plan


@dataclass
class Reread:
    """What reading one clip's name again changes: its game, its date or
    both. An empty `game` or a zero `when` leaves that as it is."""

    filename: str
    game_was: str
    game: str = ""
    when_was: float = 0.0
    when: float = 0.0


@dataclass
class RereadGroup:
    """The changes from one game to another ("" for "Dates only")."""

    game_was: str
    game: str
    changes: list[Reread] = field(default_factory=list)

    @property
    def dates(self) -> int:
        return sum(1 for change in self.changes if change.when)


def plan_reread(names, tags: dict[str, str], dates: dict[str, float], patterns=None,
                game_names=None) -> list[RereadGroup]:
    """What reading the clips called `names` again would change, grouped by
    game, the most clips first; dates only, last. `tags` and `dates` are what
    the library has; a game already in use keeps its spelling, and a game
    that only changes spelling isn't a change."""
    known = {game_key(game): game for game in tags.values() if game}
    groups: dict[tuple[str, str], RereadGroup] = {}
    for name in sorted(names):
        game_was = tags.get(name, "")
        game = fixed_name(game_from_filename(name, patterns), game_names or {})
        game = known.get(game_key(game), game)
        if not game or game_key(game) == game_key(game_was):
            game = ""
        when, when_was = recorded_at(name, patterns), dates.get(name, 0.0)
        if not when or abs(when - when_was) < 1:
            when = 0.0
        if not game and not when:
            continue
        key = (game_was, game) if game else ("", "")
        group = groups.setdefault(key, RereadGroup(*key))
        group.changes.append(Reread(name, game_was, game, when_was, when))
    return sorted(groups.values(), key=lambda g: (not g.game, -len(g.changes),
                                                  g.game.casefold()))
