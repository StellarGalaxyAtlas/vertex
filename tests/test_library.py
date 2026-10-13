import json
import sqlite3

from vertex.library import database
from vertex.library.database import ClipEdit, Library

# The table exactly as Vertex 1.x created it, before any of its ad-hoc ALTERs.
V0_SCHEMA = """
CREATE TABLE clips (
    filename    TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tag         TEXT NOT NULL DEFAULT '',
    game        TEXT NOT NULL DEFAULT '',
    people      TEXT NOT NULL DEFAULT '[]',
    favorite    INTEGER NOT NULL DEFAULT 0,
    trim_start  REAL,
    trim_end    REAL,
    volumes     TEXT NOT NULL DEFAULT '{}',
    updated     REAL NOT NULL DEFAULT 0
);
"""


def test_upgrades_a_v1_library_in_place(tmp_path):
    path = tmp_path / database.DB_NAME
    conn = sqlite3.connect(path)
    conn.executescript(V0_SCHEMA)
    conn.execute(
        "INSERT INTO clips (filename, title, tag, favorite, trim_start, volumes)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("a.mp4", "My clip", "Apex", 1, 2.5,
         json.dumps({"Mic": {"volume": 0.4, "muted": False}, "Old": 0.7})))
    conn.commit()
    conn.close()

    library = Library(str(tmp_path))
    assert library.schema_version == database.SCHEMA_VERSION
    edit = library.get_edit("a.mp4")
    assert edit.title == "My clip"
    assert edit.game == "Apex"               # the legacy tag column seeds it
    assert edit.favorite and edit.trim_start == 2.5
    assert edit.mix_for("Mic").volume == 0.4
    assert edit.mix_for("Old").volume == 0.7  # bare numbers from early rows
    assert edit.mix_for("missing") is None
    library.close()

    # Re-opening is a no-op.
    again = Library(str(tmp_path))
    assert again.get_edit("a.mp4").title == "My clip"
    again.close()


def test_edit_round_trip():
    library = Library.in_memory()
    edit = ClipEdit("x.mp4", title="T", game="  The   Finals ", people=["Anna", "anna", "Ben"],
                    favorite=True, trim_start=1.0, trim_end=5.0,
                    volumes={"Vertex Mic": {"volume": 0.5, "muted": True}})
    library.save_edit(edit)
    loaded = library.get_edit("x.mp4")
    assert loaded.game == "The Finals"
    assert loaded.people == ["Anna", "Ben"]
    assert loaded.mix_for("Vertex Mic").muted
    assert library.get_edit("unknown.mp4") == ClipEdit("unknown.mp4")


def test_single_field_setters_preserve_the_rest():
    library = Library.in_memory()
    library.set_tags("a.mp4", "Apex", ["Anna"])
    library.set_title("a.mp4", "Title")
    library.set_favorite("a.mp4", True)
    library.set_trim("a.mp4", 1.0, 2.0)
    library.set_duration("a.mp4", 9.5)
    edit = library.get_edit("a.mp4")
    assert (edit.game, edit.people, edit.title, edit.favorite) == ("Apex", ["Anna"], "Title", True)
    assert library.durations() == {"a.mp4": 9.5}
    library.clear_trim("a.mp4")
    edit = library.get_edit("a.mp4")
    assert edit.trim_start is None and edit.title == "Title"
    assert library.get_duration("a.mp4") is None


def test_autotag_fills_blanks_with_known_spelling():
    library = Library.in_memory()
    library.set_tags("mine.mp4", "The Finals", [])
    library.set_tags("THE-FINALS__2024-06-16__19-45-24.mp4", "Typed", [])
    tagged = library.autotag_games([
        "THE-FINALS__2024-06-16__19-45-23.mp4",
        "THE-FINALS__2024-06-16__19-45-24.mp4",
        "Replay_2026-03-28_05-28-25.mp4",
    ])
    assert tagged == {"THE-FINALS__2024-06-16__19-45-23.mp4": "The Finals"}
    assert library.get_edit("THE-FINALS__2024-06-16__19-45-24.mp4").game == "Typed"


def test_tag_if_untagged():
    library = Library.in_memory()
    library.set_tags("a.mp4", "Deep Rock Galactic", [])
    assert library.tag_if_untagged("b.mp4", "deep rock galactic") == "Deep Rock Galactic"
    assert library.tag_if_untagged("a.mp4", "Other") == ""
    assert library.tag_if_untagged("c.mp4", "  ") == ""


def test_known_games_and_people_rank_by_use():
    library = Library.in_memory()
    library.set_tags("1", "Apex", ["Anna", "Ben"])
    library.set_tags("2", "Apex", ["anna"])
    library.set_tags("3", "Zelda", [])
    assert library.known_games() == ["Apex", "Zelda"]
    assert library.known_people() == ["Anna", "Ben"]
    assert set(library.tags()) == {"1", "2", "3"}


def test_dates_fill_blanks_only():
    library = Library.in_memory()
    assert library.store_recorded({"a": 10.0, "b": 0}) == {"a": 10.0}
    assert library.store_recorded({"a": 20.0}) == {}
    assert library.recorded_dates() == {"a": 10.0}


def test_apply_import_overwrites_confirmed_games():
    library = Library.in_memory()
    library.set_tags("a", "Old", [])
    assert library.apply_import({"a": "New", "b": " "}, {"a": 5.0, "c": 6.0}) == 1
    assert library.get_edit("a").game == "New"
    assert library.get_edit("b").game == ""
    assert library.recorded_dates() == {"a": 5.0, "c": 6.0}


def test_rename_copy_and_forget():
    library = Library.in_memory()
    library.save_edit(ClipEdit("a", title="T", game="G", favorite=True, trim_start=1.0))
    library.copy_edits("a", "a2", title_suffix=" (trimmed)")
    copy = library.get_edit("a2")
    assert (copy.title, copy.game, copy.favorite, copy.trim_start) == \
        ("T (trimmed)", "G", False, None)
    library.rename("a", "b")
    assert library.get_edit("b").title == "T"
    assert library.get_edit("a") == ClipEdit("a")
    library.forget("b")
    assert library.get_edit("b") == ClipEdit("b")
    assert library.favorites() == set()
