import os

from vertex import notifications, sounds
from vertex.config import Config


def test_every_sound_belongs_to_a_kind_and_has_its_file():
    for sound in sounds.SOUNDS:
        assert sound.kind in notifications.BY_ID and sound.name
        assert os.path.isfile(sounds.own_file(sound.kind))


def test_only_switches_changed_from_their_default_are_stored():
    choices = sounds.changed_choices(
        {"clip_saved": True, "replay_started": True, "replay_failed": False, "gone": True,
         "clip_not_saved": "no"})
    assert choices == {"replay_started": True, "replay_failed": False}
    assert sounds.enabled(choices, "clip_saved")           # default on
    assert sounds.enabled(choices, "replay_started")       # switched on
    assert not sounds.enabled(choices, "replay_failed")    # switched off
    assert not sounds.enabled(choices, "replay_stopped")   # default off
    assert not sounds.enabled(choices, "in_tray")          # a kind without a sound


def test_own_file_plays_while_it_is_there(tmp_path):
    mine = tmp_path / "ding.mp3"
    mine.write_bytes(b"ID3")
    files = {"clip_saved": str(mine), "clip_not_saved": str(tmp_path / "gone.ogg")}
    assert sounds.file_for(files, "clip_saved") == str(mine)
    assert sounds.file_for(files, "clip_not_saved") == sounds.own_file("clip_not_saved")
    assert sounds.file_for({}, "replay_failed") == sounds.own_file("replay_stopped")


def test_config_keeps_known_sounds_and_a_volume_in_range():
    config = Config.from_dict({
        "sounds": {"clip_saved": False, "clip_not_saved": True, "gone": False},
        "sound_files": {"clip_saved": "/a.mp3", "gone": "/b.mp3", "replay_failed": " ",
                        "clip_not_saved": 3},
        "sound_volume": 250})
    assert config.sounds == {"clip_saved": False}
    assert config.sound_files == {"clip_saved": "/a.mp3"}
    assert config.sound_volume == 100
    assert Config.from_dict({}).sound_volume == sounds.DEFAULT_VOLUME


def test_player_plays_on_the_device_asked_for_or_the_default(fake_mpv_sounds):
    player = sounds.Player()
    player.play("/a.wav", 40)
    player.play("/b.wav", 150, sink="alsa_output.usb-headset")
    player.play("/c.wav", 60, sink="unplugged")
    assert len(fake_mpv_sounds) == 1          # one libmpv, kept
    assert fake_mpv_sounds[0].played == [
        ("/a.wav", "auto", 40), ("/b.wav", "pulse/alsa_output.usb-headset", 100),
        ("/c.wav", "auto", 60)]
    player.close()
    assert fake_mpv_sounds[0].terminated
