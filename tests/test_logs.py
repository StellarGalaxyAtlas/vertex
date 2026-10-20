"""The log files: one per part of Vertex, plain text, capped in size."""

import os
import re

from vertex import logs
from vertex.config import Config
from vertex.ui.control import _log_command

LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d  (INFO|WARNING|ERROR) +\S")


def _read(folder, name):
    with open(os.path.join(folder, name), encoding="utf-8") as handle:
        return handle.read()


def test_each_part_writes_its_own_file(tmp_path):
    folder = str(tmp_path / "logs")
    assert logs.setup(folder) == folder
    logs.RECORDER.warning("GPU Screen Recorder: not found")
    logs.CLIPS.error("Couldn't delete a.mp4: busy")
    logs.APP.info("Command save-clip: Saving the replay buffer…")
    assert sorted(os.listdir(folder)) == ["clips.log", "recorder.log", "vertex.log"]
    recorder = _read(folder, "recorder.log")
    assert "not found" in recorder and "Couldn't delete" not in recorder
    for name in logs.FILES.values():
        for line in _read(folder, name).splitlines():
            assert LINE.match(line), line


def test_a_full_file_starts_over_keeping_two_old_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "MAX_BYTES", 2000)
    folder = str(tmp_path / "logs")
    logs.setup(folder)
    for number in range(400):
        logs.CLIPS.info("Line %d of a long evening", number)
    names = sorted(name for name in os.listdir(folder) if name.startswith("clips"))
    assert names == ["clips.log", "clips.log.1", "clips.log.2"]
    assert all(os.path.getsize(os.path.join(folder, name)) <= 2000 for name in names)
    assert "Line 399 " in _read(folder, "clips.log")


def test_switched_off_nothing_is_written(tmp_path):
    folder = str(tmp_path / "logs")
    logs.apply(True, folder)
    logs.apply(False, folder)
    assert logs.folder() == ""
    logs.CLIPS.info("Not written")
    assert "Not written" not in _read(folder, "clips.log")
    assert "Logging turned off" in _read(folder, "vertex.log")
    logs.apply(True, folder)
    assert "Logging turned on" in _read(folder, "vertex.log")


def test_moving_the_folder_follows(tmp_path):
    first, second = str(tmp_path / "a"), str(tmp_path / "b")
    logs.setup(first)
    logs.setup(second)
    logs.APP.info("Here now")
    assert "Here now" in _read(second, "vertex.log")
    assert "Here now" not in _read(first, "vertex.log")
    assert f"moved here from {first}" in _read(second, "vertex.log")


def test_an_unwritable_folder_keeps_the_old_one(tmp_path):
    good = str(tmp_path / "logs")
    logs.setup(good)
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert logs.setup(str(blocker / "logs")) == good


def test_the_folder_defaults_to_the_state_folder(tmp_path):
    config = Config(state_path=str(tmp_path / "state"))
    assert config.resolved_log_dir() == str(tmp_path / "state" / "logs")
    config.log_path = str(tmp_path / "elsewhere")
    assert config.resolved_log_dir() == str(tmp_path / "elsewhere")
    assert Config().keep_logs
    assert not Config.from_dict({"keep_logs": False}).keep_logs


def test_commands_asked_all_the_time_stay_out(tmp_path):
    folder = str(tmp_path / "logs")
    logs.setup(folder)
    _log_command("state", {}, {"ok": True, "message": ""})
    _log_command("replay", {"action": "status"}, {"ok": True, "message": "running"})
    _log_command("replay", {"action": "toggle"},
                 {"ok": True, "message": "Starting the replay buffer."})
    _log_command("save-clip", {"seconds": 30},
                 {"ok": False, "error": "replay_off", "message": "The replay buffer is off."})
    text = _read(folder, "vertex.log")
    assert "state" not in text and "status" not in text and "running" not in text
    assert "Command replay action=toggle: Starting the replay buffer." in text
    assert "WARNING" in text and "The replay buffer is off." in text
