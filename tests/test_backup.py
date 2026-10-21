import dataclasses
import json
import os
import time
import zipfile

import pytest

from vertex import backup, cli, ipc, paths, platform, setting_groups
from vertex.config import Config
from vertex.core import storage
from vertex.library import Library


@pytest.fixture(autouse=True)
def no_trash(monkeypatch):
    """What a restore replaces is kept beside it, not sent to the real Trash."""
    monkeypatch.setattr(storage, "send2trash", None)


def _install(tmp_path, clips=("a.mp4", "b.mp4")) -> Config:
    """A set-up Vertex: settings saved, a library knowing `clips`."""
    folder = tmp_path / "clips"
    folder.mkdir(exist_ok=True)
    config = Config(clip_path=str(folder), export_path=str(tmp_path / "exports"),
                    data_path=str(tmp_path / "data"), state_path=str(tmp_path / "state"),
                    cache_path=str(tmp_path / "cache"))
    config.game_names = {"Apex": "Apex Legends"}
    config.save()
    library = Library(config.resolved_data_dir())
    for name in clips:
        (folder / name).write_bytes(b"clip")
        library.set_tags(name, "Apex Legends", ["Sam"])
    library.close()
    return config


def _tags(config: Config) -> dict:
    library = Library(config.resolved_data_dir())
    try:
        return library.tags()
    finally:
        library.close()


def test_a_backup_holds_the_settings_and_library_and_puts_them_back(tmp_path):
    config = _install(tmp_path)
    target = tmp_path / "out" / backup.default_name()
    contents = backup.export(str(target), config)
    assert contents.parts == backup.PARTS and contents.clips == 2
    assert not [name for name in os.listdir(target.parent) if name.endswith(".part")]
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {backup.MANIFEST, backup.SETTINGS,
                                           backup.LIBRARY_FILE}
    read = backup.read(str(target))
    assert (read.parts, read.clips, read.recorder) == (backup.PARTS, 2, platform.RECORDER)

    # Things change after the backup; the restore puts them back.
    changed = Config.load()
    changed.game_names = {}
    changed.save()
    library = Library(config.resolved_data_dir())
    library.set_tags("a.mp4", "Valorant", [])
    library.close()
    restored = backup.restore(str(target), changed)
    assert restored.settings and "library" in restored.picks and restored.clips == 2
    assert Config.load().game_names == {"Apex": "Apex Legends"}
    assert _tags(config)["a.mp4"] == ("Apex Legends", ["Sam"])
    # What was replaced is kept, recoverably.
    assert restored.moved_to.endswith(".bak") and os.path.exists(restored.moved_to)


def test_a_restore_can_put_back_only_the_library(tmp_path):
    config = _install(tmp_path)
    target = str(tmp_path / "backup.zip")
    backup.export(target, config)
    changed = Config.load()
    changed.game_names = {}
    changed.save()
    library = Library(config.resolved_data_dir())
    library.set_tags("a.mp4", "Valorant", [])
    library.close()
    restored = backup.restore(target, changed, ["library"])
    assert restored.picks == ("library",) and not restored.settings
    assert Config.load().game_names == {}
    assert _tags(config)["a.mp4"][0] == "Apex Legends"


def test_folders_and_recorder_from_another_computer_stay_this_ones(tmp_path):
    config = _install(tmp_path)
    target = tmp_path / "backup.zip"
    backup.export(str(target), config)
    # The same backup as another computer, with another recorder, would make it.
    other = config.to_dict()
    other["clip_path"] = str(tmp_path / "not here")
    other["recorder"]["fps"] = 30
    with zipfile.ZipFile(target) as archive:
        library = archive.read(backup.LIBRARY_FILE)
        manifest = json.loads(archive.read(backup.MANIFEST))
    manifest["recorder"] = "obs" if platform.RECORDER == "gsr" else "gsr"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(backup.MANIFEST, json.dumps(manifest))
        archive.writestr(backup.SETTINGS, json.dumps(other))
        archive.writestr(backup.LIBRARY_FILE, library)
    current = Config.load()
    current.recorder.fps = 120
    current.game_names = {}
    offered = backup.choices(backup.read(str(target)), backup.load_settings(str(target)),
                             current)
    assert offered["clip_path"].note == "not on this computer"
    assert offered["capture"].note == "made for another recorder"
    assert offered["capture"].now == "Whole screen, 120 fps"
    assert offered["game_names"].default and offered["game_names"].now == "None"
    restored = backup.restore(str(target), current)
    assert {"clip_path", "capture", "quality"} <= set(restored.left_out)
    saved = Config.load()
    assert saved.clip_path == config.clip_path and saved.recorder.fps == 120
    assert saved.game_names == {"Apex": "Apex Legends"}
    # Picked by hand, they come along anyway.
    backup.restore(str(target), current, ["capture"])
    assert Config.load().recorder.fps == 30


def test_the_groups_cover_every_setting():
    def fields(cls, prefix=""):
        found = set()
        for item in dataclasses.fields(cls):
            if prefix == "" and item.name in ("recorder", "sonar"):
                found |= fields(item.type if not isinstance(item.type, str) else
                                type(getattr(Config(), item.name)), item.name + ".")
            else:
                found.add(prefix + item.name)
        return found
    named = [name for item in setting_groups.items().values() for name in item.fields]
    assert len(named) == len(set(named))
    assert set(named) == fields(Config)


def test_what_isnt_a_backup_is_refused_and_nothing_changes(tmp_path):
    config = _install(tmp_path)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(backup.BackupError):
        backup.read(str(junk))
    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(newer, "w") as archive:
        archive.writestr(backup.MANIFEST, json.dumps({"format": backup.FORMAT + 1,
                                                      "version": "9.0"}))
    with pytest.raises(backup.BackupError, match="newer"):
        backup.restore(str(newer), config)
    assert _tags(config)["a.mp4"][0] == "Apex Legends"
    assert sorted(os.listdir(config.resolved_data_dir())) == ["library.db"]


def test_daily_backups_keep_the_newest_few(tmp_path):
    config = _install(tmp_path)
    day = 24 * 3600
    start = time.time() - 10 * day
    made = [backup.back_up_daily(config, start + i * day) for i in range(backup.AUTOMATIC_KEPT + 2)]
    assert all(made)
    assert backup.back_up_daily(config, start + (backup.AUTOMATIC_KEPT + 1.5) * day) == ""
    kept = backup.automatic(config)
    assert [path for path, _contents in kept] == made[::-1][:backup.AUTOMATIC_KEPT]
    config.daily_backup = False
    assert backup.back_up_daily(config, time.time()) == ""


def test_missing_clips_are_counted(tmp_path):
    config = _install(tmp_path, ("a.mp4", "b.mp4", "c.mp4"))
    os.remove(os.path.join(config.clip_path, "a.mp4"))
    assert backup.missing_clips(config) == (1, 3)


def test_cli_exports_and_imports(tmp_path, monkeypatch, capsys):
    config = _install(tmp_path)
    monkeypatch.setattr(ipc, "is_running", lambda: False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["backup", "export"]) == 0
    target = tmp_path / backup.default_name()
    assert target.exists()
    assert "settings and library (2 clips)" in capsys.readouterr().out
    library = Library(config.resolved_data_dir())
    library.set_tags("a.mp4", "Valorant", [])
    library.close()
    # Not a terminal: it asks for --yes rather than guessing.
    assert cli.main(["backup", "import", str(target)]) == 2
    assert _tags(config)["a.mp4"][0] == "Valorant"
    assert cli.main(["backup", "import", str(target), "--only", "library", "--yes"]) == 0
    assert "Restored your library (2 clips)." in capsys.readouterr().out
    assert Config.load().game_names == {"Apex": "Apex Legends"}
    assert _tags(config)["a.mp4"][0] == "Apex Legends"
    # Most clips gone from the clips folder: it says where to look.
    for name in ("a.mp4", "b.mp4"):
        os.remove(os.path.join(config.clip_path, name))
    assert cli.main(["backup", "import", str(target), "--yes"]) == 0
    assert "2 of the library's 2 clips aren't in" in capsys.readouterr().out


def test_cli_import_waits_for_vertex_to_quit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ipc, "is_running", lambda: True)
    assert cli.main(["backup", "import", str(tmp_path / "backup.zip"), "--yes"]) == 1
    assert "Quit it from the tray first" in capsys.readouterr().err
    assert not paths.config_path().exists()


def test_without_sonar_its_settings_stay_in_the_backup(tmp_path, monkeypatch):
    saved = Config()
    saved.sonar.enabled = True
    monkeypatch.setattr(platform, "WINDOWS", True)
    assert "Sonar" not in [group.title for group in setting_groups.groups()]
    assert setting_groups.left_here(saved) == ["Sonar"]
    contents = backup.Contents(time.time(), "2.0", "gsr", backup.PARTS, 3)
    offered = backup.choices(contents, saved, Config())
    assert "sonar_devices" not in offered and offered["library"].shown == "3 clips"
