"""Game names the user fixed, and the game read from a fullscreen window."""

from vertex.config import Config
from vertex.core import importing, naming
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
    assert library.tag_if_untagged("e.mp4", "HeroesOfTheStorm_x64") == "Heroes of the Storm"
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
