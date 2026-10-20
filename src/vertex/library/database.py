"""SQLite-backed library of per-clip edit metadata.

The clip files are never modified. Every user edit — title, tags, favourite,
trim points, per-track volumes — lives here, keyed by the clip's file name
(relative to the clips folder), and is applied when the clip is played,
trimmed or exported.

The layout is versioned with `PRAGMA user_version`: a change to SCHEMA bumps
SCHEMA_VERSION, and `Library._upgrade` brings older libraries up to it in
place.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from vertex import fmt
from vertex.core.naming import clean_tag, clean_tags, fixed_name, game_from_filename, game_key
from vertex.logs import CLIPS as log

DB_NAME = "library.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    filename    TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    game        TEXT NOT NULL DEFAULT '',     -- '' = untagged
    people      TEXT NOT NULL DEFAULT '[]',   -- JSON list, in typed order
    favorite    INTEGER NOT NULL DEFAULT 0,
    trim_start  REAL,                         -- NULL = clip start
    trim_end    REAL,                         -- NULL = clip end
    -- JSON: {track_name: {"volume": 0..1.5, "muted": bool}}
    volumes     TEXT NOT NULL DEFAULT '{}',
    duration    REAL,
    -- When the clip was recorded: from its name where that says, else the date
    -- its file had when first indexed. NULL = never indexed (not the same as 0).
    recorded    REAL,
    updated     REAL NOT NULL DEFAULT 0       -- last write
);
CREATE INDEX IF NOT EXISTS clips_game ON clips (game COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS clips_favorite ON clips (favorite);
"""
# The user_version of SCHEMA. Libraries in use are at 2 already; bump it with
# every change.
SCHEMA_VERSION = 2


def _decode_people(raw: str | None) -> list[str]:
    try:
        people = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return clean_tags(people) if isinstance(people, list) else []


def _decode_volumes(raw: str | None) -> dict:
    try:
        volumes = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return volumes if isinstance(volumes, dict) else {}


@dataclass
class TrackMix:
    volume: float = 1.0
    muted: bool = False


@dataclass
class ClipEdit:
    """Edit state for one clip. The defaults are an untouched clip."""

    filename: str
    title: str = ""
    description: str = ""
    game: str = ""
    people: list[str] = field(default_factory=list)
    favorite: bool = False
    trim_start: float | None = None
    trim_end: float | None = None
    volumes: dict = field(default_factory=dict)

    def mix_for(self, track_name: str) -> TrackMix | None:
        """The saved volume/mute of the track named `track_name`, if any."""
        saved = self.volumes.get(track_name)
        if saved is None:
            return None
        if not isinstance(saved, dict):
            return None
        try:
            return TrackMix(float(saved.get("volume", 1.0)), bool(saved.get("muted", False)))
        except (TypeError, ValueError):
            return None


class Library:
    """One connection, used from one thread (the UI's)."""

    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, DB_NAME)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        # The user's game names (config.game_names), followed by every tag
        # Vertex writes itself.
        self.game_names: dict[str, str] = {}
        self._upgrade()

    @classmethod
    def in_memory(cls) -> Library:
        """A throwaway library, for tests and for running without a data dir."""
        library = cls.__new__(cls)
        library.path = ":memory:"
        library.conn = sqlite3.connect(":memory:")
        library.conn.row_factory = sqlite3.Row
        library.game_names = {}
        library._upgrade()
        return library

    def _upgrade(self) -> None:
        if self.schema_version < SCHEMA_VERSION:
            with self.conn:
                self.conn.executescript(SCHEMA)
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @property
    def schema_version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        self.conn.close()

    # --- Whole edits -------------------------------------------------------

    def get_edit(self, filename: str) -> ClipEdit:
        row = self.conn.execute("SELECT * FROM clips WHERE filename = ?", (filename,)).fetchone()
        if row is None:
            return ClipEdit(filename=filename)
        return ClipEdit(
            filename=row["filename"], title=row["title"], description=row["description"],
            game=row["game"], people=_decode_people(row["people"]),
            favorite=bool(row["favorite"]), trim_start=row["trim_start"],
            trim_end=row["trim_end"], volumes=_decode_volumes(row["volumes"]),
        )

    def save_edit(self, edit: ClipEdit) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO clips (filename, title, description, game, people, favorite,
                                   trim_start, trim_end, volumes, updated)
                VALUES (:filename, :title, :description, :game, :people, :favorite,
                        :trim_start, :trim_end, :volumes, :updated)
                ON CONFLICT(filename) DO UPDATE SET
                    title = excluded.title, description = excluded.description,
                    game = excluded.game, people = excluded.people,
                    favorite = excluded.favorite, trim_start = excluded.trim_start,
                    trim_end = excluded.trim_end, volumes = excluded.volumes,
                    updated = excluded.updated
                """,
                {
                    "filename": edit.filename, "title": edit.title,
                    "description": edit.description, "game": clean_tag(edit.game),
                    "people": json.dumps(clean_tags(edit.people)),
                    "favorite": int(edit.favorite), "trim_start": edit.trim_start,
                    "trim_end": edit.trim_end, "volumes": json.dumps(edit.volumes),
                    "updated": time.time(),
                },
            )

    def _upsert(self, filename: str, **columns) -> None:
        """Set some columns of a clip's row, creating the row if needed."""
        columns["updated"] = time.time()
        names = ", ".join(columns)
        marks = ", ".join(f":{name}" for name in columns)
        updates = ", ".join(f"{name} = excluded.{name}" for name in columns)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO clips (filename, {names}) VALUES (:filename, {marks})"
                f" ON CONFLICT(filename) DO UPDATE SET {updates}",
                {"filename": filename, **columns},
            )

    # --- Single fields -----------------------------------------------------

    def set_title(self, filename: str, title: str) -> None:
        """A display title; the file keeps its name. '' means show the name."""
        self._upsert(filename, title=title)

    def titles(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT filename, title FROM clips WHERE title != ''")
        return {row["filename"]: row["title"] for row in rows}

    def set_favorite(self, filename: str, favorite: bool) -> None:
        self._upsert(filename, favorite=int(favorite))

    def favorites(self) -> set[str]:
        rows = self.conn.execute("SELECT filename FROM clips WHERE favorite = 1")
        return {row["filename"] for row in rows}

    def set_trim(self, filename: str, start: float | None, end: float | None) -> None:
        self._upsert(filename, trim_start=start, trim_end=end)

    def set_volumes(self, filename: str, volumes: dict) -> None:
        self._upsert(filename, volumes=json.dumps(volumes))

    def get_duration(self, filename: str) -> float | None:
        row = self.conn.execute(
            "SELECT duration FROM clips WHERE filename = ?", (filename,)).fetchone()
        return row["duration"] if row and row["duration"] is not None else None

    def durations(self) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT filename, duration FROM clips WHERE duration IS NOT NULL")
        return {row["filename"]: row["duration"] for row in rows}

    def set_duration(self, filename: str, seconds: float) -> None:
        self._upsert(filename, duration=seconds)

    def clear_trim(self, filename: str) -> None:
        """Forget trim points and duration, keeping everything else.

        For a clip whose file was just replaced by a trimmed version of itself:
        the markers and duration describe the file that is gone, while the
        title, tags and per-track volumes still apply.
        """
        with self.conn:
            self.conn.execute(
                "UPDATE clips SET trim_start = NULL, trim_end = NULL, duration = NULL,"
                " updated = ? WHERE filename = ?", (time.time(), filename))

    def forget(self, filename: str) -> None:
        """Drop a clip's row — its file has been deleted."""
        with self.conn:
            self.conn.execute("DELETE FROM clips WHERE filename = ?", (filename,))

    def rename(self, old: str, new: str) -> None:
        """Carry a clip's edits over to a new file name. No-op if `new` has a row."""
        with self.conn:
            exists = self.conn.execute(
                "SELECT 1 FROM clips WHERE filename = ?", (new,)).fetchone()
            if not exists:
                self.conn.execute(
                    "UPDATE clips SET filename = ?, updated = ? WHERE filename = ?",
                    (new, time.time(), old))

    def copy_edits(self, source: str, target: str, title_suffix: str = "") -> None:
        """Seed `target`'s row from `source`'s tags, title and mix (not its trim)."""
        edit = self.get_edit(source)
        edit.filename = target
        edit.trim_start = edit.trim_end = None
        edit.favorite = False
        if edit.title and title_suffix:
            edit.title = f"{edit.title}{title_suffix}"
        self.save_edit(edit)

    # --- Tags ---------------------------------------------------------------

    def set_tags(self, filename: str, game: str, people: Iterable[str]) -> tuple[str, list[str]]:
        """Store a clip's game and people. Returns them as actually stored."""
        game, people = clean_tag(game), clean_tags(people)
        self._upsert(filename, game=game, people=json.dumps(people))
        return game, people

    def tags(self) -> dict[str, tuple[str, list[str]]]:
        """{filename: (game, people)} for every clip carrying a tag."""
        rows = self.conn.execute(
            "SELECT filename, game, people FROM clips"
            " WHERE game != '' OR people NOT IN ('', '[]')")
        return {row["filename"]: (row["game"], _decode_people(row["people"])) for row in rows}

    def known_games(self) -> list[str]:
        """Every game tagged so far, most-used first, for suggestions."""
        rows = self.conn.execute(
            "SELECT game, COUNT(*) AS uses FROM clips WHERE game != ''"
            " GROUP BY game COLLATE NOCASE ORDER BY uses DESC, game COLLATE NOCASE")
        return [row["game"] for row in rows]

    def known_people(self) -> list[str]:
        """Every person tagged on any clip, most-tagged first."""
        counts: dict[str, tuple[str, int]] = {}
        for row in self.conn.execute("SELECT people FROM clips WHERE people NOT IN ('', '[]')"):
            for name in _decode_people(row["people"]):
                display, uses = counts.get(name.casefold(), (name, 0))
                counts[name.casefold()] = (display, uses + 1)
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1][1], kv[0]))
        return [display for _key, (display, _uses) in ranked]

    def canonical_game(self, game: str) -> str:
        """`game` as the user's game names have it, in the spelling the
        library already uses for it, if any."""
        game = fixed_name(clean_tag(game), self.game_names)
        known = {game_key(name): name for name in self.known_games()}
        return known.get(game_key(game), game)

    def tag_if_untagged(self, filename: str, game: str) -> str:
        """Give a clip a game only if it has none. Returns the tag written, or ''."""
        game = self.canonical_game(game)
        if not game:
            return ""
        row = self.conn.execute(
            "SELECT game FROM clips WHERE filename = ?", (filename,)).fetchone()
        if row is not None and row["game"]:
            return ""
        self._upsert(filename, game=game)
        return game

    def rename_game(self, old: str, new: str) -> int:
        """Retag every clip of the game `old` (in any spelling `game_key`
        counts as the same) as `new`, which may be a game already in use.
        Returns how many clips changed."""
        new = clean_tag(new)
        spellings = [game for game in self.known_games() if game_key(game) == game_key(old)]
        if not new or not spellings or spellings == [new]:
            return 0
        with self.conn:
            changed = self.conn.executemany(
                "UPDATE clips SET game = ?, updated = ? WHERE game = ? COLLATE NOCASE",
                [(new, time.time(), game) for game in spellings if game != new]).rowcount
        return changed

    def autotag_games(self, filenames: Iterable[str]) -> dict[str, str]:
        """Tag every untagged clip with the game its file name records.

        Only ever fills a blank, so a game typed on a clip is never written
        over. A spelling already in the library wins over the derived one, so
        "THE-FINALS__…" joins an existing "The Finals" tag.
        """
        known = {game_key(game): game for game in self.known_games()}
        tagged_already = {
            row["filename"] for row in self.conn.execute(
                "SELECT filename FROM clips WHERE game != ''")}
        tagged: dict[str, str] = {}
        for filename in filenames:
            if filename in tagged_already:
                continue
            game = fixed_name(game_from_filename(filename), self.game_names)
            if not game:
                continue
            tagged[filename] = known.setdefault(game_key(game), game)
        if tagged:
            now = time.time()
            with self.conn:
                self.conn.executemany(
                    "INSERT INTO clips (filename, game, updated) VALUES (?, ?, ?)"
                    " ON CONFLICT(filename) DO UPDATE SET game = excluded.game,"
                    " updated = excluded.updated",
                    [(name, game, now) for name, game in tagged.items()])
        return tagged

    # --- Dates ---------------------------------------------------------------

    def store_recorded(self, dates: dict[str, float]) -> dict[str, float]:
        """Save when clips were recorded, filling blanks only. 0 means unknown."""
        known = {
            row["filename"] for row in self.conn.execute(
                "SELECT filename FROM clips WHERE recorded IS NOT NULL")}
        stored = {name: when for name, when in dates.items() if when and name not in known}
        if stored:
            now = time.time()
            with self.conn:
                self.conn.executemany(
                    "INSERT INTO clips (filename, recorded, updated) VALUES (?, ?, ?)"
                    " ON CONFLICT(filename) DO UPDATE SET recorded = excluded.recorded",
                    [(name, when, now) for name, when in stored.items()])
        return stored

    def recorded_dates(self) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT filename, recorded FROM clips WHERE recorded IS NOT NULL")
        return {row["filename"]: row["recorded"] for row in rows}

    def apply_import(self, assignments: dict[str, str],
                     dates: dict[str, float] | None = None) -> int:
        """Write an import's games as given (the user just confirmed each one).

        A blank game means "skip this clip". Dates go in for every clip in
        `dates`, retagged or not — knowing when it was recorded is worth having.
        """
        rows = [(name, clean_tag(game), time.time())
                for name, game in assignments.items() if clean_tag(game)]
        log.info("Tagging %s from an import", fmt.plural(len(rows), "clip"))
        with self.conn:
            self.conn.executemany(
                "INSERT INTO clips (filename, game, updated) VALUES (?, ?, ?)"
                " ON CONFLICT(filename) DO UPDATE SET game = excluded.game,"
                " updated = excluded.updated", rows)
        self.store_recorded(dates or {})
        return len(rows)
