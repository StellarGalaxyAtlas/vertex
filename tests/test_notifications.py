from vertex import notifications
from vertex.config import Config


def test_every_kind_is_complete_and_filed_under_a_category():
    ids = [kind.id for kind in notifications.KINDS]
    assert len(ids) == len(set(ids))
    categories = {category.id for category in notifications.CATEGORIES}
    for kind in notifications.KINDS:
        assert kind.category in categories
        assert kind.level in notifications.LEVELS
        assert kind.name
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


def test_gsr_notifier_arguments():
    from vertex.recorder import notifier

    assert notifier.argv("gsr-notify", "Clip saved: a.mp4", "ok", "#a1b2c3", "#ffffff",
                         "replay") == [
        "gsr-notify", "--text", "Clip saved: a.mp4", "--timeout", "3.0",
        "--icon-color", "FFFFFF", "--bg-color", "A1B2C3", "--icon", "replay"]
    args = notifier.argv("gsr-notify", "Sonar ran into a problem", "error", "#ff6b70", "#000")
    assert "--icon" not in args and args[args.index("--timeout") + 1] == "5.0"
    for kind in notifications.KINDS:
        assert kind.icon in ("", *notifier.ICONS)


def test_gsr_notifier_shows_one_toast_at_a_time(tmp_path):
    import stat
    import time

    from vertex.recorder import notifier

    log = tmp_path / "calls"
    fake = tmp_path / "gsr-notify"
    fake.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nexec sleep 30\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    def calls(count):
        deadline = time.monotonic() + 5
        while (not log.exists() or len(log.read_text().splitlines()) < count) and \
                time.monotonic() < deadline:
            time.sleep(0.02)
        return [line.split(" ")[1] for line in log.read_text().splitlines()]

    assert not notifier.Notifier("").show("x", "info", "#000000", "#ffffff")
    assert not notifier.Notifier(str(tmp_path / "missing")).show(
        "x", "info", "#000000", "#ffffff")

    shown = notifier.Notifier(str(fake))
    assert shown.available and shown.show("One", "ok", "#112233", "#ffffff", "replay")
    first = shown._shown
    assert calls(1) == ["One"]
    assert shown.show("Two", "info", "#112233", "#ffffff")
    assert first.wait(timeout=5) != 0           # the first was told to go
    assert calls(2) == ["One", "Two"]
    second = shown._shown
    shown.dismiss()
    assert second.wait(timeout=5) != 0 and shown._shown is None
