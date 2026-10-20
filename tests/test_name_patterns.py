import datetime

import pytest

from vertex import config
from vertex.core import importing, naming
from vertex.core.name_patterns import (
    PRESETS,
    Mark,
    NamePattern,
    PatternError,
    Reading,
    formats_for,
    from_marks,
    parse,
    template_of,
)


def _when(*parts):
    return datetime.datetime(*parts).timestamp()


def test_every_preset_reads_its_own_sample():
    for preset in PRESETS:
        reading = preset.pattern.read(preset.sample)
        assert reading is not None and reading.when, preset.app


def test_medal_names_give_the_game_with_its_words_apart():
    medal = next(p for p in PRESETS if p.app == "Medal").pattern
    reading = medal.read("MedalTV007FirstLight20260817235610725.mp4")
    assert reading.game == "007 First Light"
    assert reading.when == _when(2026, 8, 17, 23, 56, 10)
    assert medal.read("MedalTVApexLegends20260101120000001 (trimmed).mp4").game == \
        "Apex Legends"
    assert medal.read("THE-FINALS__2024-06-16__19-45-23.mp4") is None


def test_the_amd_preset_reads_replays_seconds_and_counters():
    amd = next(p for p in PRESETS if p.app == "AMD Adrenalin").pattern
    for name in ("Cyberpunk 2077_2024.05.18-20.32.mp4",
                 "Cyberpunk 2077_replay_2024.05.18-20.32.mp4",
                 "Cyberpunk 2077_2024.05.18-20.32.45.mp4",
                 "Cyberpunk 2077_2024.05.18-20.32_1.mp4"):
        assert amd.read(name) == Reading("Cyberpunk 2077", _when(2024, 5, 18, 20, 32)), name


def test_a_template_round_trips_and_bad_ones_are_refused():
    template = "Clip {{1}} {game} {datetime:YYYY-MM-DD_HH-mm-ss}{skip}"
    assert template_of(parse(template)) == template
    for bad in ("{map}", "{date}", "{game}{game}", "{datetime:YYYYMMDD}{date:YYYY}", "a{b"):
        with pytest.raises(PatternError):
            parse(bad)


def test_formats_are_offered_only_when_they_read_a_real_moment():
    assert formats_for("date", "20260817") == ["YYYYMMDD"]
    assert formats_for("date", "06-07-2024") == ["DD-MM-YYYY", "MM-DD-YYYY"]
    assert formats_for("date", "17-08-2026") == ["DD-MM-YYYY"]
    assert formats_for("time", "23.56.10") == ["HH.mm.ss"]
    assert formats_for("time", "25.00.00") == []
    assert formats_for("datetime", "2026-08-17 23-56-10") == ["YYYY-MM-DD HH-mm-ss"]
    assert formats_for("date", "Apex") == []


def test_marking_up_a_name_makes_a_pattern_for_the_others():
    name = "Outplayed_Valorant_06-16-2024_19-45-23-123.mp4"
    stem = name[:-4]

    def mark(text, kind, fmt=""):
        start = stem.index(text)
        return Mark(start, start + len(text), kind, fmt)

    pattern = from_marks(name, [mark("Valorant", "game"), mark("06-16-2024", "date", "MM-DD-YYYY"),
                                mark("19-45-23", "time", "HH-mm-ss"), mark("123", "skip")],
                         app="Outplayed")
    assert pattern.template == "Outplayed_{game}_{date:MM-DD-YYYY}_{time:HH-mm-ss}-{skip}"
    other = pattern.read("Outplayed_Counter_Strike_2_01-02-2025_08-00-00-7.mp4")
    assert other.game == "Counter_Strike_2"
    assert other.when == _when(2025, 1, 2, 8, 0, 0)
    spaced = NamePattern("Outplayed", pattern.template, spaces="_")
    assert spaced.read("Outplayed_Counter_Strike_2_01-02-2025_08-00-00-7.mp4").game == \
        "Counter Strike 2"
    with pytest.raises(PatternError):
        from_marks(name, [mark("Valorant", "game"), mark("Valo", "skip")])


def test_an_ignored_part_beside_the_game_keeps_its_length():
    name = "MedalTVAssassinsCreedII20260102140204766.mp4"
    stem = name[:-4]

    def mark(text, kind, fmt=""):
        start = stem.index(text)
        return Mark(start, start + len(text), kind, fmt)

    pattern = from_marks(name, [mark("MedalTV", "skip"), mark("AssassinsCreedII", "game"),
                                mark("20260102", "date", "YYYYMMDD"),
                                mark("1402", "time", "HHmm"), mark("04766", "skip")])
    assert pattern.template == "{skip:7}{game}{date:YYYYMMDD}{time:HHmm}{skip}"
    assert pattern.read(name).game == "AssassinsCreedII"
    assert pattern.read("MedalTVHalo20260102140204766.mp4").game == "Halo"
    assert template_of(parse("{skip:7}{game}")) == "{skip:7}{game}"
    for bad in ("{skip:x}", "{skip:0}", "{game:7}"):
        with pytest.raises(PatternError):
            parse(bad)


def test_taught_patterns_tag_and_date_imports(tmp_path):
    for name in ("MedalTVFirstLight20260817235610725.mp4", "THE-FINALS__2024-06-16__19-45-23.mp4",
                 "Something.mp4"):
        (tmp_path / name).write_bytes(b"x")
    medal = [PRESETS[0].pattern]
    plan = importing.plan_import(str(tmp_path), patterns=medal)
    assert set(plan.games) == {"First Light", "THE FINALS"}     # Moments' still read
    assert plan.dates["MedalTVFirstLight20260817235610725.mp4"] == \
        _when(2026, 8, 17, 23, 56, 10)
    assert plan.strays == ["Something.mp4"]
    assert "First Light" not in importing.plan_import(str(tmp_path)).games
    naming.use_patterns(medal)
    try:
        assert naming.game_from_filename("MedalTVFirstLight20260817235610725.mp4") == \
            "First Light"
    finally:
        naming.use_patterns([])


def test_patterns_in_the_settings_survive_a_round_trip_and_bad_ones_go(tmp_path):
    path = tmp_path / "config.json"
    saved = config.Config(name_patterns=[PRESETS[0].pattern.to_dict()])
    saved.save(path)
    loaded = config.Config.from_dict({"name_patterns": [
        PRESETS[0].pattern.to_dict(), {"app": "x", "template": "{nope}"}, "junk"]})
    assert config.Config.load(path).patterns() == loaded.patterns() == [PRESETS[0].pattern]
