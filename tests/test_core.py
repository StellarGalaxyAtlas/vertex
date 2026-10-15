import datetime
import os

import pytest

from vertex import fmt
from vertex.core import clips, importing, naming, storage


class TestNaming:
    @pytest.mark.parametrize("name, game", [
        ("THE-FINALS__2024-06-16__19-45-23.mp4", "THE FINALS"),
        ("Apex-Legends__2026-08-11__22-14-07.mp4", "Apex Legends"),
        ("Overwatch®-2__2025-01-02__03-04-05.mp4", "Overwatch 2"),
        ("Apex-Legends__2026-08-11__22-14-07_trim.mp4", "Apex Legends"),
        ("Apex-Legends__2026-08-11__22-14-07 (trimmed).mp4", "Apex Legends"),
        ("Apex-Legends__2026-08-11__22-14-07 (trimmed 3).mp4", "Apex Legends"),
        ("DesktopCapture__2026-08-11__22-14-07.mp4", naming.DESKTOP_TAG),
        # GPU Screen Recorder names carry no game; a wrong tag beats no tag.
        ("Replay_2026-03-28_05-28-25.mp4", ""),
        ("random video.mp4", ""),
        ("Game__2026-13-11__22-14-07x.mp4", ""),
    ])
    def test_game_from_filename(self, name, game):
        assert naming.game_from_filename(name) == game

    def test_recorded_at_both_conventions(self):
        expected = datetime.datetime(2026, 3, 28, 5, 28, 25).timestamp()
        assert naming.recorded_at("Replay_2026-03-28_05-28-25.mp4") == expected
        assert naming.recorded_at("X__2026-03-28__05-28-25.mp4") == expected

    def test_recorded_at_rejects_impossible_dates(self):
        assert naming.recorded_at("Replay_2026-13-28_05-28-25.mp4") == 0.0
        assert naming.recorded_at("clip.mp4") == 0.0

    def test_game_key_ignores_case_and_punctuation_not_words(self):
        assert naming.game_key("R.E.P.O.") == naming.game_key("r.e.p.o")
        assert naming.game_key("THE FINALS") == naming.game_key("The Finals")
        assert naming.game_key("Overwatch 2") != naming.game_key("Overwatch")

    def test_clean_tags_keeps_first_spelling(self):
        assert naming.clean_tags(["Anna", " anna ", "", "Ben  K"]) == ["Anna", "Ben K"]

    @pytest.mark.parametrize("app, game", [
        ("Overwatch.exe", "Overwatch"),
        ("Deep_Rock_Galactic", "Deep Rock Galactic"),
        ("Counter-Strike 2", "Counter-Strike 2"),
        ("steam", ""),
        ("wine64-preloader", ""),
        ("Firefox", ""),
        ("", ""),
    ])
    def test_game_from_app(self, app, game):
        assert naming.game_from_app(app) == game


class TestFormatting:
    def test_size(self):
        assert fmt.size(0) == "0 Bytes"
        assert fmt.size(512) == "512 Bytes"
        assert fmt.size(1536 * 1024 * 1024) == "1.50 GB"

    def test_duration(self):
        assert fmt.duration(59.6) == "1:00"
        assert fmt.duration(3725) == "1:02:05"

    def test_relative_time(self):
        now = 1_000_000_000
        assert fmt.relative_time(now - 30, now) == "just now"
        assert fmt.relative_time(now - 3 * 3600, now) == "3 hours ago"
        assert fmt.relative_time(now - 86400, now) == "1 day ago"
        assert fmt.relative_time(now - 40 * 86400, now) == fmt.date(now - 40 * 86400)

    def test_plural_and_oxford(self):
        assert fmt.plural(1, "clip") == "1 clip"
        assert fmt.plural(2, "clip") == "2 clips"
        assert fmt.oxford(["a", "b", "c"]) == "a, b and c"


def _touch(folder, name, size=10, mtime=None):
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        handle.write(b"x" * size)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


class TestClips:
    def test_scan_lists_recordings_only(self, tmp_path):
        folder = str(tmp_path)
        _touch(folder, "Replay_2026-03-28_05-28-25.mp4", 100)
        _touch(folder, "b.mkv", 50)
        _touch(folder, ".hidden.vertex-trim.mp4")
        _touch(folder, "x.mp4.part")
        _touch(folder, "notes.txt")
        os.mkdir(os.path.join(folder, "sub.mp4"))
        scan = clips.scan_clips(folder)
        assert sorted(c.name for c in scan.clips) == ["Replay_2026-03-28_05-28-25.mp4", "b.mkv"]
        assert scan.total_bytes == 150

    def test_sort_by_game_keeps_untagged_last(self):
        a, b, c = (clips.Clip(n, 1, mtime=i) for i, n in enumerate("abc"))
        games = {"a": "Zelda", "c": "Apex"}
        assert [x.name for x in clips.sort_clips([a, b, c], "game", False, games)] == \
            ["c", "a", "b"]
        assert [x.name for x in clips.sort_clips([a, b, c], "game", True, games)] == \
            ["a", "c", "b"]

    def test_sort_by_date(self):
        old = clips.Clip("old", 1, mtime=1)
        new = clips.Clip("new", 1, mtime=2)
        assert clips.sort_clips([old, new])[0] is new
        assert clips.sort_clips([old, new], descending=False)[0] is old

    def test_filter_every_word_must_match(self):
        one, two = clips.Clip("one.mp4", 1), clips.Clip("two.mp4", 1)
        tags = {"one.mp4": ("The Finals", ["Anna"]), "two.mp4": ("The Finals", [])}
        assert clips.filter_clips([one, two], "anna finals", tags) == [one]
        assert clips.filter_clips([one, two], "", tags) == [one, two]
        assert clips.filter_clips([one, two], "two") == [two]

    def test_trimmed_copy_path_is_free(self, tmp_path):
        original = _touch(str(tmp_path), "clip.mp4")
        first = clips.trimmed_copy_path(original)
        assert first.endswith("clip (trimmed).mp4")
        _touch(str(tmp_path), "clip (trimmed).mp4")
        assert clips.trimmed_copy_path(original).endswith("clip (trimmed 2).mp4")

    def test_staging_path_is_hidden_sibling(self, tmp_path):
        staged = clips.staging_path(str(tmp_path / "clip.mp4"), "vertex-trim")
        assert os.path.basename(staged).startswith(".")
        assert not clips.is_clip(os.path.basename(staged))


class TestImporting:
    def test_copy_skips_existing_and_writes_atomically(self, tmp_path):
        src, dst = tmp_path / "src", tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        _touch(str(src), "new.mp4", 1000)
        _touch(str(src), "dup.mp4", 10)
        _touch(str(dst), "dup.mp4", 5)
        _touch(str(src), "thumb.jpg")
        plan = importing.plan_copy(str(src), str(dst))
        assert plan.files == [("new.mp4", 1000)]
        assert plan.present == ["dup.mp4"]
        progress = []
        copied, failed = importing.copy_clips(plan, lambda *a: progress.append(a))
        assert copied == ["new.mp4"] and not failed
        assert os.path.getsize(dst / "new.mp4") == 1000
        assert os.path.getsize(dst / "dup.mp4") == 5      # never overwritten
        assert progress[-1] == (1, "new.mp4", 1000)
        assert not [n for n in os.listdir(dst) if n.endswith(".part")]

    def test_copy_into_a_folder_not_made_yet(self, tmp_path):
        # Setup copies into the clips folder it is about to create.
        src, dst = tmp_path / "src", tmp_path / "videos" / "Game Recordings"
        src.mkdir()
        _touch(str(src), "a.mp4", 100)
        plan = importing.plan_copy(str(src), str(dst))
        assert plan.files == [("a.mp4", 100)]
        assert plan.free_bytes > 0 and plan.fits
        copied, failed = importing.copy_clips(plan)
        assert copied == ["a.mp4"] and not failed
        assert os.path.getsize(dst / "a.mp4") == 100

    def test_copy_can_be_cancelled(self, tmp_path):
        src, dst = tmp_path / "src", tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        _touch(str(src), "a.mp4")
        plan = importing.plan_copy(str(src), str(dst))
        copied, _ = importing.copy_clips(plan, cancelled=lambda: True)
        assert copied == []

    def test_plan_import_reuses_known_spelling(self, tmp_path):
        folder = str(tmp_path)
        _touch(folder, "THE-FINALS__2024-06-16__19-45-23.mp4")
        _touch(folder, "Replay_2026-03-28_05-28-25.mp4")
        _touch(folder, "Apex-Legends__2026-08-11__22-14-07.mp4")
        plan = importing.plan_import(
            folder, known_games=["The Finals"],
            tagged=["Apex-Legends__2026-08-11__22-14-07.mp4"])
        assert plan.stored_as == {"THE FINALS": "The Finals"}
        assert plan.strays == ["Replay_2026-03-28_05-28-25.mp4"]
        assert plan.already == ["Apex-Legends__2026-08-11__22-14-07.mp4"]
        assert plan.clip_count == 3
        assert plan.assignments({"THE FINALS": "Finals"}) == {
            "THE-FINALS__2024-06-16__19-45-23.mp4": "Finals"}
        assert len(plan.dates) == 3


class TestStorage:
    def test_stats_count_clips(self, tmp_path):
        _touch(str(tmp_path), "a.mp4", 2048)
        stats = storage.storage_stats(str(tmp_path))
        assert stats.clips_bytes == 2048
        assert stats.disk_total > 0
        assert 0 <= stats.fraction(stats.disk_free) <= 1

    def test_delete_file(self, tmp_path):
        path = _touch(str(tmp_path), "a.mp4")
        storage.delete_file(path)
        assert not os.path.exists(path)


class TestDeviceOrder:
    def test_learn_choose_promote(self):
        from vertex.audio import devices
        assert devices.learn([], [], ["a", "b", "c"], first="b") == ["b", "a", "c"]
        assert devices.learn(["c"], ["x"], ["a", "x", "c"]) == ["c", "a"]
        assert devices.choose(["a", "b"], [], ["b"]) == "b"
        assert devices.choose(["a", "b"], ["a"], ["a", "b"]) == "b"
        assert devices.choose(["a", "b"], [], ["a", "b"], "b") == "b"      # picked for now
        assert devices.choose(["a", "b"], [], ["a"], "b") == "a"           # unplugged
        assert devices.choose(["a"], ["a"], ["a"], "a") == "a"             # picked by hand
        assert devices.choose(["a"], [], ["z"]) == ""
        assert devices.promote(["a", "b"], ["c"], "c") == (["c", "a", "b"], [])

    def test_reorder_keeps_hidden_entries_in_place(self):
        from vertex.audio import devices
        # "h" is disconnected and hidden; "a" and "b" swap round it.
        assert devices.reorder(["a", "h", "b"], {"a", "b"}, ["b", "a"]) == ["b", "h", "a"]
        # One moved in from the other list goes after the rest; one moved out goes.
        assert devices.reorder(["a", "h", "b"], {"a", "b"}, ["b", "a", "x"]) == [
            "b", "h", "a", "x"]
        assert devices.reorder(["a", "h", "b"], {"a", "b"}, ["b"]) == ["b", "h"]

    def test_describe_format(self):
        from vertex.audio import devices
        assert devices.describe_format("s24le 2ch 48000Hz") == "24-bit · 48 kHz · stereo"
        assert devices.describe_format("float32le 1ch 44100Hz") == \
            "32-bit float · 44.1 kHz · mono"
        assert devices.describe_format("s24-32le 6ch 96000Hz") == "24-bit · 96 kHz · 6 channels"
        assert devices.describe_format("") == ""

