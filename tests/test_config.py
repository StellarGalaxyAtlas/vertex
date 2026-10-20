import json
import os

import pytest

from vertex import config, paths, system


def test_unknown_keys_are_ignored_and_dropped(tmp_path):
    """Settings Vertex no longer has don't stop a config from loading, and go
    on the next save; missing sections fall back to their defaults."""
    data = {
        "clip_path": "~/Videos/Game Recordings",
        "export_path": "~/Videos/Game Recordings/Vertex/Exports",
        "logo_variant": "dark",
        "game_device": "Virtual_Game_Sink.monitor",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    loaded = config.Config.load(path)
    assert loaded.clip_path == data["clip_path"]
    assert loaded.export_path == data["export_path"]
    assert loaded.recorder.replay_seconds == 60
    loaded.save(path)
    saved = json.loads(path.read_text())
    assert "game_device" not in saved and "logo_variant" not in saved


def test_round_trip_with_new_sections(tmp_path):
    cfg = config.default_config()
    cfg.recorder.chat_audio = ""
    cfg.recorder.mic_audio = "device:alsa_input.usb-mic"
    cfg.colour_scheme = "spooky"
    path = tmp_path / "config.json"
    cfg.save(path)
    again = config.Config.load(path)
    assert again == cfg


def test_bad_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "clip_path": 5,
        "colour_scheme": 5,
        "card_width": 5000,
        "recorder": {"fps": "sixty", "cursor": "yes", "replay_seconds": 30},
    }))
    loaded = config.Config.load(path)
    assert loaded.clip_path == ""
    assert loaded.colour_scheme == "navy"
    assert loaded.card_width == config.CARD_WIDTH_RANGE[1]
    assert loaded.recorder.fps == 60 and loaded.recorder.cursor is True
    assert loaded.recorder.replay_seconds == 30


def test_needs_setup(tmp_path):
    path = tmp_path / "config.json"
    assert config.needs_setup(path)
    cfg = config.default_config()
    cfg.save(path)
    assert not config.needs_setup(path)


def test_missing_dirs_and_ensure(tmp_path):
    cfg = config.Config(clip_path=str(tmp_path / "clips"), data_path=str(tmp_path / "data"),
                        export_path=str(tmp_path / "exports"))
    assert {key for key, _ in cfg.missing_dirs()} == {"clip_path", "data_path"}
    assert cfg.ensure_dirs() == []
    assert cfg.missing_dirs() == []
    assert os.path.isdir(tmp_path / "exports")


@pytest.mark.skipif(system.WINDOWS, reason="the XDG layout is Linux's (see test_windows)")
def test_xdg_env_is_honoured(isolated_home):
    assert str(paths.config_path()).startswith(str(isolated_home / ".config"))
    assert paths.normalize("~/x/../y/") == os.path.join(str(isolated_home), "y")
    assert paths.tilde(str(isolated_home / "a")) == "~/a"


def test_assets_exist():
    for variant in paths.LOGO_VARIANTS:
        assert paths.mark_path(variant).is_file()
        assert paths.wordmark_path(variant).is_file()
