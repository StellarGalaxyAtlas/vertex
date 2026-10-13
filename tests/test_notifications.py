from vertex import notifications
from vertex.config import Config


def test_every_kind_is_complete_and_filed_under_a_category():
    ids = [kind.id for kind in notifications.KINDS]
    assert len(ids) == len(set(ids))
    categories = {category.id for category in notifications.CATEGORIES}
    for kind in notifications.KINDS:
        assert kind.category in categories
        assert kind.level in notifications.LEVELS
        assert kind.name and kind.description
    for category in categories:
        assert notifications.in_category(category)


def test_only_switches_changed_from_their_default_are_stored():
    choices = notifications.changed_choices(
        {"clip_saved": True, "replay_started": True, "in_tray": False, "gone": False})
    assert choices == {"replay_started": True, "in_tray": False}
    assert notifications.enabled(choices, "clip_saved")          # default on
    assert notifications.enabled(choices, "replay_started")      # switched on
    assert not notifications.enabled(choices, "in_tray")         # switched off
    assert not notifications.enabled(choices, "replay_stopped")  # default off


def test_notice_line():
    assert notifications.Notice("clip_saved", "Clip saved", "a.mp4").line == \
        "Clip saved: a.mp4"
    assert notifications.Notice("replay_stopped", "Replay buffer off").line == \
        "Replay buffer off"


def test_config_keeps_known_changed_switches_only():
    config = Config.from_dict({"notifications": {
        "replay_started": True, "clip_saved": True, "in_tray": "no", "gone": False}})
    assert config.notifications == {"replay_started": True}
    assert Config.from_dict({"notifications": ["clip_saved"]}).notifications == {}
