
from vertex.library import database
from vertex.library.database import ClipEdit, Library


def test_a_new_library_has_the_current_layout(tmp_path):
    library = Library(str(tmp_path))
    assert library.schema_version == database.SCHEMA_VERSION
    columns = {row[1] for row in library.conn.execute("PRAGMA table_info(clips)")}
    assert {"game", "people", "duration", "recorded"} <= columns
    library.save_edit(ClipEdit("a.mp4", title="My clip",
                               volumes={"Mic": {"volume": 0.4, "muted": False}, "Bad": 0.7}))
    library.close()

    # Re-opening keeps everything.
    again = Library(str(tmp_path))
    edit = again.get_edit("a.mp4")
    assert edit.title == "My clip"
    assert edit.mix_for("Mic").volume == 0.4
    assert edit.mix_for("Bad") is None and edit.mix_for("missing") is None
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
