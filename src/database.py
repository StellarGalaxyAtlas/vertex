"""SQLite-backed library of per-clip edit metadata.

The clip files themselves are never modified. All user edits — trim points,
per-track volumes, favorite, title, description, tags — live here and are
applied at export time. Clips are keyed by filename (relative to the clip
folder).
"""

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field

import core

DB_NAME = "library.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    filename    TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tag         TEXT NOT NULL DEFAULT '',   -- legacy, folded into `game`
    game        TEXT NOT NULL DEFAULT '',   -- '' = untagged
    people      TEXT NOT NULL DEFAULT '[]', -- JSON list of names, in typed order
    favorite    INTEGER NOT NULL DEFAULT 0,
    trim_start  REAL,               -- NULL = clip start
    trim_end    REAL,               -- NULL = clip end
    -- JSON: {device_name: {"volume": 0..1.5, "muted": bool}}. Older rows stored
    -- a bare number per track; readers still accept that form.
    volumes     TEXT NOT NULL DEFAULT '{}',
    updated     REAL NOT NULL DEFAULT 0
);
"""

# Columns added after the first release, with the DDL to bring an older DB up to
# date. Applied in order; ones already present are skipped.
LATER_COLUMNS = (
    ("duration", "REAL"),
    ("game", "TEXT NOT NULL DEFAULT ''"),
    ("people", "TEXT NOT NULL DEFAULT '[]'"),
    # When the clip was recorded: from its file name where that says, else the
    # date its file had when the app first saw it. NULL = never indexed, which
    # is not the same as 0.
    ("recorded", "REAL"),
)


def _decode_people(raw):
    """Read a `people` cell. Anything unreadable is treated as untagged."""
    try:
        people = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return core.clean_tags(people) if isinstance(people, list) else []


@dataclass
class ClipEdit:
    """Edit state for one clip. Defaults represent an untouched clip."""

    filename: str
    title: str = ""
    description: str = ""
    game: str = ""
    people: list = field(default_factory=list)
    favorite: bool = False
    trim_start: float | None = None
    trim_end: float | None = None
    volumes: dict = field(default_factory=dict)


class Library:
    def __init__(self, data_dir):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, DB_NAME)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Add columns introduced after a user's DB was first created."""
        for name, decl in LATER_COLUMNS:
            try:
                self.conn.execute(f"ALTER TABLE clips ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass  # column already present
        # `tag` was a single unused free-text field; whatever is in it is the
        # closest thing an older DB has to a game, so it seeds that column.
        self.conn.execute(
            "UPDATE clips SET game = tag WHERE game = '' AND tag != ''"
        )

    def get_edit(self, filename):
        """Return the stored ClipEdit, or defaults if the clip has no row yet."""
        row = self.conn.execute(
            "SELECT * FROM clips WHERE filename = ?", (filename,)
        ).fetchone()
        if row is None:
            return ClipEdit(filename=filename)
        return ClipEdit(
            filename=row["filename"],
            title=row["title"],
            description=row["description"],
            game=row["game"],
            people=_decode_people(row["people"]),
            favorite=bool(row["favorite"]),
            trim_start=row["trim_start"],
            trim_end=row["trim_end"],
            volumes=json.loads(row["volumes"]),
        )

    def save_edit(self, edit):
        """Insert or update a clip's full edit state."""
        self.conn.execute(
            """
            INSERT INTO clips
                (filename, title, description, game, people, favorite,
                 trim_start, trim_end, volumes, updated)
            VALUES (:filename, :title, :description, :game, :people, :favorite,
                    :trim_start, :trim_end, :volumes, :updated)
            ON CONFLICT(filename) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                game=excluded.game,
                people=excluded.people,
                favorite=excluded.favorite,
                trim_start=excluded.trim_start,
                trim_end=excluded.trim_end,
                volumes=excluded.volumes,
                updated=excluded.updated
            """,
            {
                "filename": edit.filename,
                "title": edit.title,
                "description": edit.description,
                "game": core.clean_tag(edit.game),
                "people": json.dumps(core.clean_tags(edit.people)),
                "favorite": int(edit.favorite),
                "trim_start": edit.trim_start,
                "trim_end": edit.trim_end,
                "volumes": json.dumps(edit.volumes),
                "updated": time.time(),
            },
        )
        self.conn.commit()

    def get_duration(self, filename):
        """Cached clip duration in seconds, or None if not probed yet."""
        row = self.conn.execute(
            "SELECT duration FROM clips WHERE filename = ?", (filename,)
        ).fetchone()
        return row["duration"] if row and row["duration"] is not None else None

    def probed(self):
        """Every filename whose duration is already known.

        The set, rather than a get_duration per clip: the grid checks the whole
        library at once to work out which clips still need probing.
        """
        rows = self.conn.execute(
            "SELECT filename FROM clips WHERE duration IS NOT NULL"
        ).fetchall()
        return {row["filename"] for row in rows}

    def set_duration(self, filename, seconds):
        self.conn.execute(
            """
            INSERT INTO clips (filename, duration, updated) VALUES (?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET duration = excluded.duration
            """,
            (filename, seconds, time.time()),
        )
        self.conn.commit()

    def set_title(self, filename, title):
        """Store a display title, preserving any other edit state.

        Purely metadata: the clip file itself is never renamed. An empty title
        means "show the filename".
        """
        edit = self.get_edit(filename)
        edit.title = title
        self.save_edit(edit)

    def titles(self):
        """{filename: title} for every clip that has a custom title set."""
        rows = self.conn.execute(
            "SELECT filename, title FROM clips WHERE title != ''"
        ).fetchall()
        return {row["filename"]: row["title"] for row in rows}

    # --- Tags ---------------------------------------------------------------

    def autotag_games(self, filenames):
        """Tag any untagged clip with the game its file name records.

        Only ever fills a blank, so a game typed on a clip is never written
        over. The flip side is that a game cleared off a clip whose name still
        carries one comes back on the next scan — the file name is the only
        thing to go on, and there is nowhere to record "leave this one alone".

        A spelling already used in the library wins over the one derived from
        the name, so "THE-FINALS__…" joins the existing "The Finals" tag rather
        than starting a second one beside it.

        Returns {filename: game} for the clips it tagged.
        """
        known = {core.game_key(game): game for game in self.known_games()}
        tagged_already = {
            row["filename"] for row in
            self.conn.execute("SELECT filename FROM clips WHERE game != ''")
        }

        tagged = {}
        for filename in filenames:
            if filename in tagged_already:
                continue
            game = core.game_from_filename(filename)
            if not game:
                continue
            game = known.setdefault(core.game_key(game), game)
            self.conn.execute(
                """
                INSERT INTO clips (filename, game, updated) VALUES (?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    game = excluded.game, updated = excluded.updated
                """,
                (filename, game, time.time()),
            )
            tagged[filename] = game

        if tagged:
            self.conn.commit()
        return tagged

    def store_recorded(self, dates):
        """Save when clips were recorded, from {filename: unix timestamp}.

        Only fills a blank, like autotag_games: once a date is on a clip it
        stays, so a correction made later isn't undone by the next scan — and
        neither is it undone by the file's own dates changing underneath, which
        is what makes this the date the app sorts by. Timestamps of 0 are
        skipped: they mean the caller had no date to offer at all.
        """
        known = {
            row["filename"] for row in
            self.conn.execute("SELECT filename FROM clips WHERE recorded IS NOT NULL")
        }
        stored = {
            filename: when for filename, when in dates.items()
            if when and filename not in known
        }
        for filename, when in stored.items():
            self.conn.execute(
                """
                INSERT INTO clips (filename, recorded, updated) VALUES (?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET recorded = excluded.recorded
                """,
                (filename, when, time.time()),
            )
        if stored:
            self.conn.commit()
        return stored

    def apply_import(self, assignments, dates=None):
        """Write an import's tags and dates: {filename: game}, {filename: when}.

        Games are written as given rather than only filling blanks, because the
        user has just seen and confirmed every one of them in the import
        dialog. A blank game means "skip this clip", so it is left untagged.

        Dates go in for every clip in `dates`, including ones this import did
        not retag — knowing when a clip was recorded is worth having either way.
        """
        written = 0
        for filename, game in assignments.items():
            game = core.clean_tag(game)
            if not game:
                continue
            self.conn.execute(
                """
                INSERT INTO clips (filename, game, recorded, updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    game = excluded.game, updated = excluded.updated
                """,
                (filename, game, (dates or {}).get(filename), time.time()),
            )
            written += 1
        self.conn.commit()
        self.store_recorded(dates or {})
        return written

    def recorded_dates(self):
        """{filename: unix timestamp} for every clip with a recording date."""
        return {
            row["filename"]: row["recorded"] for row in
            self.conn.execute(
                "SELECT filename, recorded FROM clips WHERE recorded IS NOT NULL"
            )
        }

    def set_tags(self, filename, game, people):
        """Store a clip's game and the people in it, preserving other edits.

        Returns the tags as they were actually stored, which is what the caller
        should display: both are cleaned on the way in.
        """
        edit = self.get_edit(filename)
        edit.game = core.clean_tag(game)
        edit.people = core.clean_tags(people)
        self.save_edit(edit)
        return edit.game, edit.people

    def tags(self):
        """{filename: (game, people)} for every clip carrying a tag.

        Clips missing from the result are untagged.
        """
        rows = self.conn.execute(
            "SELECT filename, game, people FROM clips"
            " WHERE game != '' OR people NOT IN ('', '[]')"
        ).fetchall()
        return {
            row["filename"]: (row["game"], _decode_people(row["people"]))
            for row in rows
        }

    def known_games(self):
        """Every game tagged so far, most-used first, for the suggestion list.

        Nothing is seeded: the list is exactly what has been typed on some clip,
        so it starts empty and grows as the library gets tagged.
        """
        rows = self.conn.execute(
            "SELECT game, COUNT(*) AS uses FROM clips WHERE game != ''"
            " GROUP BY game COLLATE NOCASE"
            " ORDER BY uses DESC, game COLLATE NOCASE"
        ).fetchall()
        return [row["game"] for row in rows]

    def known_people(self):
        """Every person tagged on any clip so far, most-tagged first.

        Names live in a JSON list rather than their own table, so the counting
        happens here instead of in SQL. The library is a few hundred rows at
        most, which this is comfortably fast enough for.
        """
        counts = {}
        for row in self.conn.execute(
            "SELECT people FROM clips WHERE people NOT IN ('', '[]')"
        ):
            for name in _decode_people(row["people"]):
                # Keyed case-insensitively so 'anna' and 'Anna' are one person;
                # the first spelling seen is the one suggested back.
                display, uses = counts.get(name.casefold(), (name, 0))
                counts[name.casefold()] = (display, uses + 1)
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1][1], kv[0]))
        return [display for _key, (display, _uses) in ranked]

    def clear_trim(self, filename):
        """Forget the trim points and cached duration, keeping title, favorite
        and volumes.

        Used when a clip's file is replaced by a trimmed version of itself: the
        markers and the duration describe the file that is now gone, while the
        title and per-track volumes still apply.
        """
        self.conn.execute(
            "UPDATE clips SET trim_start = NULL, trim_end = NULL,"
            " duration = NULL, updated = ? WHERE filename = ?",
            (time.time(), filename),
        )
        self.conn.commit()

    def set_favorite(self, filename, favorite):
        """Convenience toggle that preserves any other edit state."""
        edit = self.get_edit(filename)
        edit.favorite = favorite
        self.save_edit(edit)

    def favorites(self):
        """The filenames marked favourite, as a set.

        Read in one go rather than a get_edit per clip: the rail shows the count
        beside "Favorites" and has to filter on it, and both want the whole set.
        """
        rows = self.conn.execute(
            "SELECT filename FROM clips WHERE favorite = 1").fetchall()
        return {row["filename"] for row in rows}

    def delete_clip(self, filename):
        """Forget a clip's edit state — used when its file is deleted."""
        self.conn.execute("DELETE FROM clips WHERE filename = ?", (filename,))
        self.conn.commit()

    def close(self):
        self.conn.close()
