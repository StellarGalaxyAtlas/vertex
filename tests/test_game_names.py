"""Game names the user fixed, and the game read from a fullscreen window."""

from vertex.config import Config
from vertex.core import importing, naming
from vertex.core.name_patterns import PRESETS
from vertex.library.database import Library


def test_a_fixed_name_matches_any_spelling_of_it():
    names = {"Heroes of the Storm(Retail)": "Heroes of the Storm"}
    assert naming.fixed_name("Heroes of the Storm (Retail)", names) == "Heroes of the Storm"
    assert naming.fixed_name("HEROES OF THE STORM(RETAIL)", names) == "Heroes of the Storm"
    assert naming.fixed_name("Overwatch", names) == "Overwatch"
    assert naming.fixed_name("", names) == ""


def test_adding_a_name_never_leads_round_in_a_circle():
    names = naming.add_game_name({}, "HotS (Retail)", "HotS")
    names = naming.add_game_name(names, "HotS", "Heroes of the Storm")
    # What led to the old name leads to the new one.
    assert names == {"HotS (Retail)": "Heroes of the Storm", "HotS": "Heroes of the Storm"}
    names = naming.add_game_name(names, "Heroes of the Storm", "HotS")
    assert names == {"HotS (Retail)": "HotS", "Heroes of the Storm": "HotS"}
    assert naming.add_game_name(names, "hots", "HotS") == names
    assert naming.add_game_name(names, " ", "X") == names


def test_the_game_of_a_fullscreen_window():
    assert naming.game_from_window("Heroes of the Storm™",
                                   r"C:\Games\HeroesOfTheStorm_x64.exe") == "Heroes of the Storm"
    assert naming.game_from_window("", r"C:\Games\Deep_Rock_Galactic.exe") == \
        "Deep Rock Galactic"
    # A video or a call filling the screen is no game.
    assert naming.game_from_window("YouTube", r"C:\Program Files\Mozilla Firefox\firefox.exe") == ""
    assert naming.game_from_window("Friends", r"C:\Users\a\Discord\Discord.exe") == ""
    assert naming.game_from_window("Overwatch", "") == "Overwatch"


def test_the_library_retags_a_game_and_follows_the_names():
    library = Library.in_memory()
    library.set_tags("a.mp4", "Heroes of the Storm(Retail)", [])
    library.set_tags("b.mp4", "Heroes of the Storm (Retail)", [])
    library.set_tags("c.mp4", "Heroes of the Storm", [])
    library.set_tags("d.mp4", "Overwatch", [])
    assert library.rename_game("heroes of the storm (retail)", "Heroes of the Storm") == 2
    assert {name: game for name, (game, _p) in library.tags().items()} == {
        "a.mp4": "Heroes of the Storm", "b.mp4": "Heroes of the Storm",
        "c.mp4": "Heroes of the Storm", "d.mp4": "Overwatch"}
    assert library.rename_game("Nothing", "X") == 0

    library.game_names = {"HeroesOfTheStorm_x64": "Heroes of the Storm",
                          "OVERWATCH-2": "Overwatch"}
    assert library.tag_recorded("e.mp4", "HeroesOfTheStorm_x64") == "Heroes of the Storm"
    assert library.autotag_games(["OVERWATCH-2__2024-06-16__19-45-23.mp4"]) == {
        "OVERWATCH-2__2024-06-16__19-45-23.mp4": "Overwatch"}


def test_game_names_are_kept_in_the_settings(tmp_path):
    config = Config.from_dict({"game_names": {
        "HotS (Retail)": "HotS", "HotS": "Heroes of the Storm", "Bad": 3, "": "X"}})
    assert config.game_names == {"HotS (Retail)": "Heroes of the Storm",
                                 "HotS": "Heroes of the Storm"}
    assert Config.from_dict(config.to_dict()).game_names == config.game_names


def test_importing_shows_games_as_the_names_have_them(tmp_path):
    (tmp_path / "Heroes-of-the-Storm-(Retail)__2024-06-16__19-45-23.mp4").write_bytes(b"")
    plan = importing.plan_import(
        str(tmp_path), names={"Heroes of the Storm (Retail)": "Heroes of the Storm"})
    assert set(plan.stored_as.values()) == {"Heroes of the Storm"}


def test_reading_names_again_groups_what_changes_by_game():
    import datetime

    when = datetime.datetime(2026, 8, 17, 23, 56, 10).timestamp()
    medal = PRESETS[0].pattern
    names = ["MedalTVHelldivers220260817235610725.mp4", "MedalTVHelldivers220260817235610726.mp4",
             "MedalTVValorant20260817235610725.mp4", "THE-FINALS__2026-08-17__23-56-10.mp4",
             "Replay_2026-08-17_23-56-10.mp4", "untouched.mp4"]
    tags = {names[0]: "Helldivers", names[1]: "Helldivers", names[2]: "Valorant",
            names[3]: "The Finals", "untouched.mp4": "Typed"}
    dates = {names[0]: 1.0, names[1]: when, names[2]: when, names[3]: when, names[4]: 5.0}
    groups = importing.plan_reread(names, tags, dates, [medal],
                                   {"Helldivers 2": "HELLDIVERS 2"})
    assert [(g.game_was, g.game, len(g.changes), g.dates) for g in groups] == [
        ("Helldivers", "HELLDIVERS 2", 2, 1), ("", "", 1, 1)]
    assert groups[1].changes[0].filename == "Replay_2026-08-17_23-56-10.mp4"

    # A name that says Desktop doesn't undo a game; it does tag an untagged clip.
    desktop = ["Desktop-Capture__2026-10-20__21-00-00.mp4",
               "Desktop-Capture__2026-10-20__21-05-00.mp4"]
    groups = importing.plan_reread(desktop, {desktop[0]: "Heroes of the Storm"},
                                   {name: importing.recorded_at(name) for name in desktop})
    assert [(g.game_was, g.game, len(g.changes)) for g in groups] == [("", "Desktop", 1)]
    # A tag the user kept over its name isn't asked about again; nor are dates kept.
    kept = importing.plan_reread(desktop, {}, {}, kept=[("", "desktop"), ("", "")])
    assert kept == []

    library = Library.in_memory()
    library.apply_reread({names[0]: "HELLDIVERS 2"}, {names[4]: when})
    assert library.tags()[names[0]][0] == "HELLDIVERS 2"
    assert library.recorded_dates()[names[4]] == when


def test_a_clip_named_after_its_game_reads_back():
    from vertex.core.naming import game_from_filename, moments_name, recorded_at

    name = moments_name("Replay_2026-10-20_21-00-00.mp4", "Helldivers 2")
    assert name == "Helldivers-2__2026-10-20__21-00-00.mp4"
    assert game_from_filename(name) == "Helldivers 2"
    assert recorded_at(name) == recorded_at("Replay_2026-10-20_21-00-00.mp4")
    assert moments_name("x.mp4", "Game") == ""
    assert moments_name("Replay_2026-10-20_21-00-00.mkv", 'A: "B"/C?') == \
        "A-B-C__2026-10-20__21-00-00.mkv"
