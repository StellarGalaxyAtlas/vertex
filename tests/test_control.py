import pytest

from vertex import control, notifications
from vertex.config import Config


def test_arguments_are_checked():
    assert control.choice_arg({}, "action", ("on", "off", "toggle"), "toggle") == "toggle"
    with pytest.raises(control.BadArgument):
        control.choice_arg({"action": "sideways"}, "action", ("up", "down"))


def test_state_describes_what_buttons_show():
    state = control.state(Config(), "running")
    assert state["api"] == control.API_VERSION
    assert state == {"api": control.API_VERSION,
                     "replay": {"state": "running", "running": True, "seconds": 60}}
    assert not control.state(Config(), "stopped")["replay"]["running"]


def test_replies_and_events():
    assert control.ok("Done.") == {"ok": True, "message": "Done."}
    assert control.ok("Done.", seconds=30)["data"] == {"seconds": 30}
    assert control.error(control.REPLAY_OFF, "Off.") == {"ok": False, "error": "replay_off",
                                                         "message": "Off."}
    event = control.notice_event(notifications.Notice("clip_saved", "Clip saved", "a.mp4"))
    assert event == {"event": "notice", "data": {"kind": "clip_saved", "category": "clips",
                                                 "title": "Clip saved", "body": "a.mp4"}}
