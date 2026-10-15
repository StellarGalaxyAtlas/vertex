import os
from pathlib import Path

from vertex import paths, reset
from vertex.config import Config
from vertex.core import storage
from vertex.library import Library
from vertex.media.thumbnails import ThumbnailCache


def test_discard_goes_to_the_trash(tmp_path, monkeypatch):
    trashed = []
    monkeypatch.setattr(storage, "send2trash", lambda path: (trashed.append(path),
                                                             os.remove(path)))
    target = tmp_path / "config.json"
    target.write_text("{}")
    assert reset.discard(target) == "the Trash"
    assert trashed == [str(target)] and not target.exists()
    assert reset.discard(target) == ""            # already gone


def test_discard_keeps_a_backup_without_a_trash(tmp_path, monkeypatch):
    def refuse(_path):
        raise OSError("no trash on this volume")
    target = tmp_path / "config.json"
    for send in (None, refuse):
        monkeypatch.setattr(storage, "send2trash", send)
        target.write_text('{"kept": true}')
        backup = reset.discard(target)
        assert not target.exists()
        assert backup.startswith(str(target)) and backup.endswith(".bak")
        assert Path(backup).read_text() == '{"kept": true}'
        os.remove(backup)


def test_discard_settings_and_library(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "send2trash", None)
    config = Config(clip_path=str(tmp_path / "clips"))
    config.save()
    assert reset.discard_settings().startswith(str(paths.config_path()))
    assert not paths.config_path().exists()

    data = tmp_path / "data"
    library = Library(str(data))
    library.set_tags("a.mp4", "The Finals", [])
    library.close()
    (data / "library.db-wal").write_text("")
    assert reset.discard_library(str(data)).endswith(".bak")
    assert not any(name.startswith("library.db") and not name.endswith(".bak")
                   for name in os.listdir(data))
    fresh = Library(str(data))
    assert fresh.tags() == {}
    fresh.close()


def test_reset_in_place_keeps_the_objects(tmp_path):
    config = Config(clip_path="/somewhere")
    config.sonar.enabled = True
    config.sonar.app_rules["spotify"] = "media"
    config.recorder.replay_seconds = 120
    config.notifications = {"replay_started": True}
    sonar, recorder = config.sonar, config.recorder
    reset.reset_in_place(config, Config())
    assert config == Config()
    assert config.sonar is sonar and config.recorder is recorder


def test_thumbnail_cache_clears_only_its_own_folders(tmp_path):
    folder = tmp_path / "cache"
    folder.mkdir()
    (folder / "keep.txt").write_text("not the cache's")
    cache = ThumbnailCache(str(folder))
    (folder / "thumbnails" / "x.jpg").write_text("")
    (folder / "previews" / "y").mkdir(parents=True)
    cache.clear()
    assert sorted(os.listdir(folder)) == ["keep.txt", "thumbnails"]
    assert os.listdir(folder / "thumbnails") == []
