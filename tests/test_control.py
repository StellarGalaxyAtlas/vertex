import pytest

from vertex import control, notifications
from vertex.audio import channels, devices
from vertex.audio.sonar import ChannelStatus, SonarStatus
from vertex.config import Config


def test_volume_steps_and_limits():
    assert control.volume_after(50, "up") == 55
    assert control.volume_after(50, "down", step=10) == 40
    assert control.volume_after(98, "up") == 100
    assert control.volume_after(3, "down") == 0
    assert control.volume_after(50, "set", 20) == 20


def test_arguments_are_checked():
    assert control.channel_arg({"channel": "mic"}) is channels.MIC
    assert control.channel_arg({}, required=False) is None
    for bad in ({}, {"channel": "aux"}):
        with pytest.raises(control.BadArgument):
            control.channel_arg(bad)
    assert control.choice_arg({}, "action", ("on", "off", "toggle"), "toggle") == "toggle"
    with pytest.raises(control.BadArgument):
        control.choice_arg({"action": "sideways"}, "action", ("up", "down"))
    assert control.number_arg({"value": 40.4}, "value", 0, 100) == 40
    for bad in ({"value": 101}, {"value": "40"}, {"value": True}, {}):
        with pytest.raises(control.BadArgument):
            control.number_arg(bad, "value", 0, 100)


def test_cycling_follows_the_priority_list():
    priority, excluded = ["a", "b", "c", "d"], ["c"]
    connected = ["d", "b", "a", "c", "new"]
    assert devices.cycle(priority, excluded, connected, "a", 1) == "b"
    assert devices.cycle(priority, excluded, connected, "b", 1) == "d"     # c is excluded
    assert devices.cycle(priority, excluded, connected, "d", 1) == "new"   # not listed yet
    assert devices.cycle(priority, excluded, connected, "new", 1) == "a"   # round again
    assert devices.cycle(priority, excluded, connected, "a", -1) == "new"
    assert devices.cycle(priority, excluded, ["a"], "a", 1) == ""          # nowhere to go
    assert devices.cycle(priority, excluded, connected, "gone", 1) == "a"


def test_device_list_follows_the_device_manager():
    listed = control.device_list(["a", "b"], ["b"], ["b", "new"], {"a": "Headset"})
    assert listed == [
        {"name": "a", "description": "Headset", "connected": False, "excluded": False},
        {"name": "b", "description": "b", "connected": True, "excluded": True},
        {"name": "new", "description": "new", "connected": True, "excluded": False}]


def test_state_describes_what_buttons_show():
    config = Config()
    config.sonar.enabled = True
    config.sonar.device_names = {"hw_headset": "Headset", "hw_mic": "Desk mic"}
    status = SonarStatus(available=True, active=True, output="hw_headset", mic="hw_mic",
                         output_picked=True, channels={
                             "game": ChannelStatus(channels.GAME, present=True, volume=0.8),
                             "mic": ChannelStatus(channels.MIC, present=True, muted=True)})
    state = control.state(config, status, "running")
    assert state["api"] == control.API_VERSION
    assert state["replay"] == {"state": "running", "running": True, "seconds": 60}
    sonar = state["sonar"]
    assert sonar["output"] == {"name": "hw_headset", "description": "Headset"}
    assert sonar["output_picked"] and not sonar["mic_picked"]
    game, mic = sonar["channels"]["game"], sonar["channels"]["mic"]
    assert (game["volume"], game["muted"], game["device"]["description"]) == (80, False,
                                                                              "Headset")
    assert (mic["muted"], mic["device"]["description"]) == (True, "Desk mic")
    # A channel Sonar doesn't report yet shows its setting.
    config.sonar.channel("chat").volume = 0.5
    assert control.state(config, status, "running")["sonar"]["channels"]["chat"][
        "volume"] == 50
    # Off: no devices.
    off = control.state(config, SonarStatus(), "stopped")["sonar"]
    assert off["output"] is None and off["channels"]["game"]["device"] is None


def test_replies_and_events():
    assert control.ok("Done.") == {"ok": True, "message": "Done."}
    assert control.ok("Done.", volume=5)["data"] == {"volume": 5}
    assert control.error(control.SONAR_OFF, "Off.") == {"ok": False, "error": "sonar_off",
                                                         "message": "Off."}
    event = control.notice_event(notifications.Notice("clip_saved", "Clip saved", "a.mp4"))
    assert event == {"event": "notice", "data": {"kind": "clip_saved", "category": "clips",
                                                 "title": "Clip saved", "body": "a.mp4"}}
