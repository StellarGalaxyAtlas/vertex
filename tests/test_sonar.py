import json
import os
import shutil
import subprocess
import time

import pytest

from vertex.audio import channels, pulse
from vertex.audio.sonar import Sonar
from vertex.config import SonarConfig

from fake_pactl import FakePactl


class TestPulseParsing:
    def test_proplist_quotes_values_and_strips_quotes(self):
        assert pulse.proplist({"device.description": 'Vertex "Game"', "x": "y"}) == \
            "'device.description=\"Vertex Game\" x=\"y\"'"

    def test_parse_modargs(self):
        args = pulse.parse_modargs(
            "sink_name=vertex_game sink_properties='device.description=\"Vertex Game\" a=b'"
            ' latency_msec=20 name="two words"')
        assert args == {
            "sink_name": "vertex_game",
            "sink_properties": 'device.description="Vertex Game" a=b',
            "latency_msec": "20",
            "name": "two words",
        }
        assert pulse.parse_modargs("") == {}

    def test_parse_event(self):
        event = pulse.parse_event("Event 'new' on sink-input #124")
        assert (event.kind, event.facility, event.index) == ("new", "sink-input", 124)
        assert pulse.parse_event("garbage") is None

    def test_device_and_stream_from_json(self):
        device = pulse.Device.from_json({
            "index": 3, "name": "vertex_game.monitor", "description": "Monitor of Vertex Game",
            "volume": {"front-left": {"value": 32768}, "front-right": {"value": 32768}},
            "mute": True, "owner_module": "536870915", "properties": {}}, "source")
        assert device.is_monitor and device.is_vertex and device.muted
        assert device.volume == 0.5 and device.owner_module == 536870915
        stream = pulse.Stream.from_json({"index": 9, "sink": 3, "properties": {
            "application.name": "Discord", "application.process.binary": "electron"}})
        assert stream.key == "discord"          # electron is too generic to key on
        stream = pulse.Stream.from_json({"index": 9, "sink": 3, "properties": {
            "application.name": "Spotify", "application.process.binary": "spotify"}})
        assert stream.key == "spotify" and stream.app_name == "Spotify"


def _sonar(tmp_path, fake=None, **config):
    fake = fake or FakePactl(sinks=("hw_headset", "hw_speakers"), sources=("hw_mic",))
    return Sonar(SonarConfig(enabled=True, **config), str(tmp_path / "sonar.json"), fake), fake


class TestSonar:
    def test_up_creates_every_channel_once(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        assert sonar.up() == []
        status = sonar.status()
        assert status.active and status.output == "hw_headset" and status.mic == "hw_mic"
        assert all(entry.routed for entry in status.channels.values())
        assert fake.default_sink_ == "vertex_game"
        assert fake.default_source_ == "vertex_mic"
        loads = len([c for c in fake.calls if c[0] == "load"])
        assert loads == 2 * len(channels.OUTPUTS) + 1

        assert sonar.up() == []                     # idempotent
        assert len([c for c in fake.calls if c[0] == "load"]) == loads

    def test_descriptions_survive_the_module_parser(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        game = next(s for s in fake.sinks_ if s.name == "vertex_game")
        assert game.description == "Vertex Game"
        assert game.properties["vertex.channel"] == "game"

    def test_duplicates_are_removed(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        fake.load_module("module-null-sink", {"sink_name": "vertex_chat"})
        sonar.up()
        assert len([s for s in fake.sinks_ if s.name == "vertex_chat"]) == 1

    def test_output_change_moves_the_loopbacks(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        sonar.set_output("hw_speakers")
        targets = {m.args["sink"] for m in fake.modules_ if m.name == "module-loopback"}
        assert targets == {"hw_speakers"}
        assert len([m for m in fake.modules_ if m.name == "module-loopback"]) == 3

    def test_unlinked_channels_play_through_their_own_devices(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()

        def targets():
            return {name: entry.output for name, entry in sonar.status().channels.items()
                    if entry.channel.is_output}

        assert targets() == {"game": "hw_headset", "chat": "hw_headset",
                             "media": "hw_headset"}
        # Unlinked, each keeps the shared device until it is given its own.
        sonar.set_linked(False, "game")
        assert targets() == {"game": "hw_headset", "chat": "hw_headset",
                             "media": "hw_headset"}
        sonar.set_channel_output("media", "hw_speakers")
        assert targets() == {"game": "hw_headset", "chat": "hw_headset",
                             "media": "hw_speakers"}
        # Its own device unplugged: the shared one meanwhile; back when it is.
        fake.remove_device("hw_speakers")
        sonar.reconcile()
        assert targets()["media"] == "hw_headset"
        fake.add_sink("hw_speakers")
        sonar.reconcile()
        assert targets()["media"] == "hw_speakers"
        # Linking from Media plays everything through Media's device.
        sonar.set_linked(True, "media")
        assert set(targets().values()) == {"hw_speakers"}
        assert sonar.config.output_device == "hw_speakers"
        # Linked, picking a device for one channel picks it for all.
        sonar.set_channel_output("chat", "hw_headset")
        assert set(targets().values()) == {"hw_headset"}

    def test_device_manager_picks_by_priority(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        sonar.learn_devices(sonar.outputs(), sonar.inputs())
        # The device in use goes on top the first time; the rest follow.
        assert sonar.config.output_priority == ["hw_headset", "hw_speakers"]
        assert sonar.config.mic_priority == ["hw_mic"]

        # Auto: the highest connected device plays, and plugging a higher
        # one back in switches to it.
        sonar.config.output_priority = ["hw_speakers", "hw_headset"]
        sonar.reconcile()
        assert sonar.status().output == "hw_speakers"
        fake.remove_device("hw_speakers")
        sonar.reconcile()
        assert sonar.status().output == "hw_headset"
        fake.add_sink("hw_speakers")
        sonar.reconcile()
        assert sonar.status().output == "hw_speakers"
        # Excluded devices are never picked automatically.
        sonar.config.output_excluded = ["hw_speakers"]
        sonar.reconcile()
        assert sonar.status().output == "hw_headset"

        # Picking one in Auto puts it on top, out of excluded.
        sonar.set_channel_output("game", "hw_speakers")
        assert sonar.config.output_priority[0] == "hw_speakers"
        assert sonar.config.output_excluded == []
        assert sonar.status().output == "hw_speakers"

        # Manual: the device picked, whatever the order; the list only says
        # what plays while it is unplugged.
        sonar.config.output_auto = False
        sonar.config.output_priority = ["hw_headset", "hw_speakers"]
        sonar.set_channel_output("game", "hw_speakers")
        assert sonar.config.output_priority == ["hw_headset", "hw_speakers"]
        assert sonar.status().output == "hw_speakers"
        fake.remove_device("hw_speakers")
        sonar.reconcile()
        assert sonar.status().output == "hw_headset"

    def test_new_devices_go_to_the_bottom(self, tmp_path):
        sonar, fake = _sonar(tmp_path, output_priority=["hw_speakers", "hw_headset"])
        sonar.up()
        fake.add_sink("hw_usb", props={"device.description": "USB Headset"})
        assert sonar.learn_devices(sonar.outputs(), sonar.inputs())
        assert sonar.config.output_priority == ["hw_speakers", "hw_headset", "hw_usb"]
        assert sonar.config.device_names["hw_usb"] == "USB Headset"
        assert not sonar.learn_devices(sonar.outputs(), sonar.inputs())
        sonar.reconcile()
        assert sonar.status().output == "hw_speakers"    # not switched to the new one

    def test_channels_also_play_through_a_second_device(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()

        def targets(channel_id):
            return sorted(m.args["sink"] for m in fake.modules_ if m.name == "module-loopback"
                          and m.args["source"] == f"vertex_{channel_id}.monitor")

        sonar.set_second_output("hw_speakers")
        assert all(targets(c) == ["hw_headset", "hw_speakers"]
                   for c in ("game", "chat", "media"))
        entry = sonar.status().channels["chat"]
        assert entry.output == "hw_headset" and entry.also
        # Chat kept private: headset only.
        sonar.set_also_second("chat", False)
        assert targets("chat") == ["hw_headset"]
        assert targets("game") == ["hw_headset", "hw_speakers"]
        assert not sonar.status().channels["chat"].also
        # Second device unplugged: the first carries on alone; back, it joins in.
        fake.remove_device("hw_speakers")
        sonar.reconcile()
        assert targets("game") == ["hw_headset"]
        fake.add_sink("hw_speakers")
        sonar.reconcile()
        assert targets("game") == ["hw_headset", "hw_speakers"]
        # The second device being the first one too: one loopback, not two.
        sonar.set_channel_output("game", "hw_speakers")
        assert targets("game") == ["hw_speakers"]
        sonar.set_second_output("")
        sonar.set_channel_output("game", "hw_headset")
        assert all(targets(c) == ["hw_headset"] for c in ("game", "chat", "media"))

    def test_retired_channels_are_removed(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        # What an older Vertex left behind: Vertex Aux and its loopback.
        fake.load_module("module-null-sink", {"sink_name": "vertex_aux"})
        fake.load_module("module-loopback", {"source": "vertex_aux.monitor",
                                             "sink": "hw_headset"})
        sonar.up()
        assert not [s for s in fake.sinks_ if s.name == "vertex_aux"]
        assert not [m for m in fake.modules_ if "vertex_aux" in str(m.args)]
        assert "aux" not in sonar.status().channels

    def test_unplugged_output_falls_back_without_stealing_defaults(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        fake.set_default_sink("hw_headset")         # the user picked the headset by hand
        fake.remove_device("hw_headset")
        fake.default_sink_ = "hw_speakers"
        sonar.reconcile()
        targets = {m.args["sink"] for m in fake.modules_ if m.name == "module-loopback"}
        assert targets == {"hw_speakers"}
        assert fake.default_sink_ == "hw_speakers"  # a repair does not retake defaults

    def test_no_output_warns(self, tmp_path):
        sonar, _ = _sonar(tmp_path, FakePactl(sinks=(), sources=()))
        warnings = sonar.up()
        assert len(warnings) == 2

    def test_mic_rebuilt_when_it_returns(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        fake.remove_device("hw_mic")
        assert sonar.reconcile()                    # warns, keeps Vertex Mic
        assert any(s.name == "vertex_mic" for s in fake.sources_)
        fake.add_source("hw_mic")
        before = len([c for c in fake.calls if c[0] == "load"])
        sonar.reconcile()
        assert len([c for c in fake.calls if c[0] == "load"]) == before + 1

    def test_routing_rules(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        spotify = fake.play("Spotify")
        discord = fake.play("Discord", binary="electron")
        assert {s.key: s.channel for s in sonar.streams()} == {"spotify": "game",
                                                              "discord": "game"}
        assert sonar.route("spotify", "media") == 1
        assert sonar.route("discord", "chat") == 1
        assert {s.key: s.channel for s in sonar.streams()} == {"spotify": "media",
                                                              "discord": "chat"}
        # A new stream from a routed app is moved when it appears.
        again = fake.play("Spotify")
        assert again.sink == fake._sink("vertex_game").index
        assert sonar.handle(pulse.Event("new", "sink-input", again.index)) is None
        assert again.sink == fake._sink("vertex_media").index
        # Clearing the rule sends it back to the default channel.
        sonar.route("spotify", None)
        assert spotify.sink == fake._sink("vertex_game").index
        assert "spotify" not in sonar.config.app_rules
        with pytest.raises(ValueError):
            sonar.route("spotify", "mic")
        assert sonar.game_apps() == ["Spotify", "Spotify"]   # both streams moved back
        assert discord.sink == fake._sink("vertex_chat").index

    def test_a_stream_that_refuses_to_move_is_retried(self, tmp_path):
        """Reported bug: after a drop the app showed on both channels. One of
        its streams refused the move and stayed behind on the old channel."""
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        fake.play("Discord", binary="Discord")
        notifications = fake.play("Discord", binary="Discord")
        fake.refuse_moves[notifications.index] = 1        # refuses once, then moves
        sonar.route("discord", "chat")
        channels_now = {s.channel for s in sonar.streams() if s.key == "discord"}
        assert channels_now == {"game", "chat"}           # the bug, reproduced
        assert [s.stuck for s in sonar.streams() if s.channel == "game"] == [True]
        assert sonar.apply_rules() == 1                   # the retry moves it
        assert {s.channel for s in sonar.streams() if s.key == "discord"} == {"chat"}
        assert not any(s.stuck for s in sonar.streams())

    def test_a_stream_that_never_moves_is_marked_stuck(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        stubborn = fake.play("Game")
        fake.refuse_moves[stubborn.index] = -1
        sonar.route("game", "media")
        assert sonar.apply_rules() == 0
        (stream,) = sonar.streams()
        assert stream.channel == "game" and stream.rule == "media" and stream.stuck

    def test_loopbacks_are_never_routed(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.config.app_rules[""] = "chat"
        sonar.up()
        assert all(s.key for s in sonar.streams())
        loops = [s for s in fake.inputs_ if "vertex.loopback" in s.properties]
        assert {s.sink for s in loops} == {fake._sink("hw_headset").index}

    def test_streams_report_their_device_and_skip_non_apps(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        fake.play("Game", sink="hw_headset")
        meter = fake.play("pavucontrol")
        meter.properties["stream.monitor"] = "true"
        streams = {s.key: s for s in sonar.streams()}
        assert set(streams) == {"game"}           # loopbacks and meters left out
        assert streams["game"].channel is None    # playing past every channel
        assert streams["game"].device == "hw_headset"

    def test_recorders(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        fake.record("Discord", "vertex_mic")
        fake.record("OBS", "hw_mic")
        fake.record("gpu-screen-recorder", "vertex_game.monitor")   # desktop audio
        fake.record("pavucontrol", "hw_mic", props={"media.name": "Peak detect"})
        found = {r.key: r for r in sonar.recorders()}
        assert set(found) == {"discord", "obs"}
        assert found["discord"].via_vertex and not found["obs"].via_vertex
        assert found["obs"].device == "hw_mic"

    def test_volumes(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.config.channel("chat").volume = 0.25
        sonar.up()
        assert fake._device("vertex_chat").volume == 0.25
        sonar.set_volume("mic", 1.7)
        assert fake._device("vertex_mic").volume == 1.0
        sonar.set_muted("media", True)
        assert sonar.status().channels["media"].muted

    def test_down_restores_everything(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        stream = fake.play("Game")
        sonar.down()
        assert not [m for m in fake.modules_ if "vertex" in m.argument]
        assert fake.default_sink_ == "hw_headset" and fake.default_source_ == "hw_mic"
        assert stream.sink == fake._sink("hw_headset").index
        assert json.loads((tmp_path / "sonar.json").read_text())["previous_sink"] == ""

    def test_previous_defaults_survive_a_restart(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.up()
        again = Sonar(SonarConfig(enabled=True), str(tmp_path / "sonar.json"), fake)
        assert again.state.previous_sink == "hw_headset"
        again.down()
        assert fake.default_sink_ == "hw_headset"

    def test_events_that_need_a_repair(self, tmp_path):
        sonar, _ = _sonar(tmp_path)
        assert sonar.handle(pulse.Event("remove", "sink", 1)) == "reconcile"
        assert sonar.handle(pulse.Event("new", "source", 1)) == "reconcile"
        assert sonar.handle(pulse.Event("change", "sink", 1)) is None
        assert sonar.handle(pulse.Event("change", "server", 0)) is None


# --- Against a real audio server -------------------------------------------
# These change the running server's devices, so they only run when asked:
#   VERTEX_TEST_PIPEWIRE=1 pytest -m pipewire

def _live():
    if os.environ.get("VERTEX_TEST_PIPEWIRE") != "1" or not shutil.which("pactl"):
        return False
    return pulse.Pactl().available()


live = pytest.mark.skipif(not _live(), reason="set VERTEX_TEST_PIPEWIRE=1 with a running server")


@pytest.mark.pipewire
@live
class TestLive:
    @pytest.fixture
    def server(self):
        pactl = pulse.Pactl()
        made = [
            pactl.load_module("module-null-sink", {
                "sink_name": "vertex_test_out",
                "sink_properties": pulse.proplist({"device.description": "Test Out"})}),
        ]
        before_sink, before_source = pactl.default_sink(), pactl.default_source()
        yield pactl
        Sonar(SonarConfig(enabled=True), None, pactl).down()
        for index in made:
            try:
                pactl.unload_module(index)
            except pulse.AudioError:
                pass
        for setter, value in ((pactl.set_default_sink, before_sink),
                              (pactl.set_default_source, before_source)):
            try:
                setter(value)
            except pulse.AudioError:
                pass

    def test_round_trip(self, server, tmp_path):
        config = SonarConfig(enabled=True, output_device="vertex_test_out")
        sonar = Sonar(config, str(tmp_path / "state.json"), server)
        sonar.up()
        status = sonar.status()
        assert all(status.channels[c.id].present for c in channels.OUTPUTS)
        names = {d.name: d.description for d in server.sinks()}
        assert names["vertex_game"] == "Vertex Game"
        assert server.default_sink() == "vertex_game"
        modules = len(server.modules())
        sonar.up()
        assert len(server.modules()) == modules
        sonar.down()
        assert not [d for d in server.sinks() if d.name.startswith("vertex_") and
                    d.name != "vertex_test_out"]

    def test_watcher_reports_events(self, server):
        seen = []
        watcher = server.watch(seen.append)
        try:
            proc = subprocess.Popen(["pactl", "load-module", "module-null-sink",
                                     "sink_name=vertex_test_event"], stdout=subprocess.PIPE,
                                    text=True)
            index = int(proc.communicate()[0].strip())
            time.sleep(0.5)
            server.unload_module(index)
            time.sleep(0.5)
        finally:
            watcher.stop()
        assert any(e.facility == "sink" and e.kind == "new" for e in seen)
