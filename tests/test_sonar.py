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
        assert len([m for m in fake.modules_ if m.name == "module-loopback"]) == 4

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

    def test_loopbacks_are_never_routed(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.config.app_rules[""] = "chat"
        sonar.up()
        assert all(s.key for s in sonar.streams())
        loops = [s for s in fake.inputs_ if "vertex.loopback" in s.properties]
        assert {s.sink for s in loops} == {fake._sink("hw_headset").index}

    def test_volumes(self, tmp_path):
        sonar, fake = _sonar(tmp_path)
        sonar.config.channel("chat").volume = 0.25
        sonar.up()
        assert fake._device("vertex_chat").volume == 0.25
        sonar.set_volume("mic", 1.7)
        assert fake._device("vertex_mic").volume == 1.0
        sonar.set_muted("aux", True)
        assert sonar.status().channels["aux"].muted

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
