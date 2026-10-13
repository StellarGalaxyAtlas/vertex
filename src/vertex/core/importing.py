"""Bringing an existing recording library in.

Two separate steps, each worked out in full before anything is written so the
user can see it and change their mind:

* a CopyPlan copies recordings from another folder into the clips folder;
* an ImportPlan tags clips with the games their file names record.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field

from vertex import fmt
from vertex.core.clips import is_clip
from vertex.core.naming import game_from_filename, game_key, recorded_at

COPY_CHUNK = 4 * 1024 * 1024          # read/write size for a single clip
COPY_REPORT_EVERY = 8 * 1024 * 1024   # how much must land before reporting again


@dataclass
class CopyPlan:
    """Which recordings a copy would bring in, and what that would cost."""

    source: str = ""
    target: str = ""
    files: list[tuple[str, int]] = field(default_factory=list)   # (name, bytes)
    present: list[str] = field(default_factory=list)             # already there
    total_bytes: int = 0
    free_bytes: int = 0

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


def plan_copy(source: str, target: str) -> CopyPlan:
    """Work out which recordings would be copied from `source` into `target`.

    Only the folder itself is read: a Moments library keeps thumbnails and
    exports in folders of their own beside the recordings. A name already in
    the target is left alone — re-running an import must never clobber a clip
    that has been edited since.
    """
    existing = set(os.listdir(target)) if os.path.isdir(target) else set()
    plan = CopyPlan(source=source, target=target)
    for name in sorted(os.listdir(source)):
        if not is_clip(name):
            continue
        if name in existing:
            plan.present.append(name)
            continue
        try:
            size = os.path.getsize(os.path.join(source, name))
        except OSError:
            continue
        plan.files.append((name, size))
        plan.total_bytes += size
    if os.path.isdir(target):
        plan.free_bytes = shutil.disk_usage(target).free
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
    done_bytes = 0
    for index, (name, size) in enumerate(plan.files, start=1):
        if cancelled is not None and cancelled():
            break
        source = os.path.join(plan.source, name)
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
            failed.append((name, str(err)))
            done_bytes = settled
            try:
                os.remove(partial)
            except OSError:
                pass
        if on_progress is not None:
            on_progress(index, name, done_bytes)
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


def plan_import(folder: str, known_games=(), tagged=()) -> ImportPlan:
    """Work out what tagging `folder` would do, touching nothing.

    `known_games` are tags already in use, so a derived game landing on one
    keeps the spelling in use; `tagged` are clips that already carry a game.
    """
    known = {game_key(game): game for game in known_games}
    tagged = set(tagged)
    plan = ImportPlan(folder=folder)
    for name in sorted(os.listdir(folder)):
        if not is_clip(name):
            continue
        when = recorded_at(name)
        if when:
            plan.dates[name] = when
        if name in tagged:
            plan.already.append(name)
            continue
        game = game_from_filename(name)
        if not game:
            plan.strays.append(name)
            continue
        plan.games.setdefault(game, []).append(name)
    plan.stored_as = {game: known.get(game_key(game), game) for game in plan.games}
    return plan
