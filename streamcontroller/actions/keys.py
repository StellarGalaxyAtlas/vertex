"""The keys: a channel's volume or mute, the next output or mic, a toggle
between two mics or two outputs, the replay buffer, save a clip, and bring
Vertex to the front."""

from __future__ import annotations

import threading

from src.backend.DeckManagement.InputIdentifier import Input

from .. import vertex_client as vc
from .base import CHANNELS, VertexAction

NOT_RUNNING = "Vertex off"
SONAR_OFF = "Sonar off"
VOLUME_STEP = 5


class Volume(VertexAction):
    """Shows a Sonar channel's volume. A press can mute it; on a dial,
    turning sets the volume and pressing mutes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def _channel(self) -> str:
        return self.setting("channel", "game")

    def show(self, state):
        label = dict(CHANNELS)[self._channel()]
        entry = vc.channel(state, self._channel())
        if state is None or entry is None:
            value = NOT_RUNNING if state is None else ""
        elif not vc.sonar(state).get("active"):
            value = SONAR_OFF
        else:
            value = "Muted" if entry["muted"] else f"{entry['volume']}%"
        self.set_top_label(label if self._channel() != "mic" else "Mic")
        self.set_center_label(value)

    def on_key_down(self):
        if self.setting("press", "nothing") == "mute":
            self.send("mute", channel=self._channel())

    def event_callback(self, event, data=None):
        if event == Input.Dial.Events.TURN_CW:
            self.send("volume", channel=self._channel(), action="up", step=VOLUME_STEP)
        elif event == Input.Dial.Events.TURN_CCW:
            self.send("volume", channel=self._channel(), action="down", step=VOLUME_STEP)
        elif event == Input.Dial.Events.DOWN:
            self.send("mute", channel=self._channel())
        else:
            super().event_callback(event, data)

    def get_config_rows(self):
        return [self.choice_row("Channel", "channel", CHANNELS, "game"),
                self.choice_row("When pressed", "press",
                                (("nothing", "Nothing"), ("mute", "Mute or unmute")),
                                "nothing")]


class _NextDevice(VertexAction):
    """Switches to the next device in the device manager's priority list, for
    now (as `vertex device next` does), and shows the one in use."""

    title = ""
    channel = None

    def _device(self, state) -> str:
        raise NotImplementedError

    def show(self, state):
        self.set_top_label(self.title)
        if state is None:
            name = NOT_RUNNING
        elif not vc.sonar(state).get("active"):
            name = SONAR_OFF
        else:
            name = self._device(state) or "None"
        self.set_bottom_label(name)

    def on_key_down(self):
        args = {"channel": self.channel} if self.channel else {}
        self.send("device", action="next", **args)


class NextOutput(_NextDevice):
    title = "Output"

    def _device(self, state):
        return vc.device_name(vc.sonar(state).get("output"))


class NextMic(_NextDevice):
    title = "Mic"
    channel = "mic"

    def _device(self, state):
        return vc.device_name(vc.sonar(state).get("mic"))


class Mute(VertexAction):
    """Mutes or unmutes a Sonar channel, and shows which it is."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def _channel(self) -> str:
        return self.setting("channel", "mic")

    def show(self, state):
        channel_id = self._channel()
        title = "Mic" if channel_id == "mic" else dict(CHANNELS)[channel_id]
        entry = vc.channel(state, channel_id)
        if state is None or entry is None:
            self.show_labels(title, NOT_RUNNING if state is None else "")
        elif not vc.sonar(state).get("active"):
            self.show_labels(title, SONAR_OFF)
        else:
            self.show_labels(title, "Muted" if entry["muted"] else "On")
            self.face("muted" if entry["muted"] else "unmuted")

    def on_key_down(self):
        self.send("mute", channel=self._channel())

    def get_config_rows(self):
        return [self.choice_row("Channel", "channel", CHANNELS, "mic")]


class _Toggle(VertexAction):
    """Switches between two devices picked in the key's settings, for now (as
    picking one on the Sonar page does), and shows which is in use: the
    first, the second, or neither (another device, or none)."""

    title = ""
    kind = ""          # the `devices` list: "mics" or "outputs"
    channel = None
    none = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def _current(self, state) -> dict | None:
        raise NotImplementedError

    def _picks(self) -> tuple[str, str]:
        return self.setting("first", ""), self.setting("second", "")

    def _in_use(self) -> str:
        state = self.vertex.state
        if state is None or not vc.sonar(state).get("active"):
            return ""
        return (self._current(state) or {}).get("name", "")

    def show(self, state):
        first, second = self._picks()
        if state is None or not vc.sonar(state).get("active"):
            self.show_labels(self.title, NOT_RUNNING if state is None else SONAR_OFF)
            self.face(f"{self.face_name}-none")
            return
        current = self._current(state)
        name = (current or {}).get("name", "")
        if name and name in (first, second):
            number = 1 if name == first else 2
            self.show_labels(f"{self.title} {number}", "", vc.device_name(current))
            self.face(f"{self.face_name}-{number}")
        else:
            self.show_labels(self.title, self.none, vc.device_name(current))
            self.face(f"{self.face_name}-none")

    @property
    def face_name(self) -> str:
        return self.title.lower()

    def on_key_down(self):
        first, second = self._picks()
        current = self._in_use()
        order = (second, first) if current == first else (first, second)
        targets = [target for target in order if target and target != current]
        args = {"channel": self.channel} if self.channel else {}

        def switch():
            # The other pick; if it isn't plugged in, the first one that is.
            for target in targets:
                try:
                    if self.vertex.send("device", action="set", name=target, **args).get("ok"):
                        return
                except vc.NotRunning:
                    break
            try:
                self.show_error(duration=1)
            except Exception:
                pass
        threading.Thread(target=switch, daemon=True, name="vertex-toggle").start()

    def _choices(self) -> tuple[list[tuple[str, str]], str]:
        """The devices to pick from, as Sonar lists them now, and a note when
        Vertex couldn't be asked."""
        note = ""
        try:
            reply = self.vertex.send("devices", timeout=2)
        except vc.NotRunning:
            reply, note = {}, "Vertex isn't running, so only the devices picked so far are listed."
        choices = [("", "None")]
        for device in (reply.get("data") or {}).get(self.kind) or []:
            label = device["description"]
            if not device["connected"]:
                label += " (not plugged in)"
            choices.append((device["name"], label))
        for picked in self._picks():
            if picked and picked not in [value for value, _label in choices]:
                choices.append((picked, picked))
        return choices, note

    def get_config_rows(self):
        choices, note = self._choices()
        return [self.choice_row(f"{self.title} 1", "first", choices, "", note),
                self.choice_row(f"{self.title} 2", "second", choices, "")]


class MicToggle(_Toggle):
    title = "Mic"
    kind = "mics"
    channel = "mic"
    none = "No mic"

    def _current(self, state):
        return vc.sonar(state).get("mic")


class OutputToggle(_Toggle):
    title = "Output"
    kind = "outputs"
    none = "No output"

    def _current(self, state):
        return vc.sonar(state).get("output")


REPLAY_PHASES = {"running": "On", "stopped": "Off", "starting": "Starting",
                 "restarting": "Starting", "failed": "Failed"}


class Replay(VertexAction):
    """Starts or stops the replay buffer, and shows whether it runs."""

    def show(self, state):
        if state is None:
            self.show_labels("Replay", NOT_RUNNING)
            return
        phase = ((state.get("replay") or {}).get("state")) or "stopped"
        self.show_labels("Replay", REPLAY_PHASES.get(phase, phase.capitalize()))
        self.face("replay-on" if phase == "running" else "replay-off")

    def on_key_down(self):
        self.send("replay", action="toggle")


SAVE_LENGTHS = ((0, "Replay length"), (10, "10 seconds"), (30, "30 seconds"),
                (60, "1 minute"), (300, "5 minutes"), (600, "10 minutes"), (1800, "30 minutes"))


FLASH = (40, 160, 90, 255)      # green, while a clip has just landed
FLASH_SECONDS = 1.5


def _length(seconds: int) -> str:
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min"


class SaveClip(VertexAction):
    """Saves the replay buffer to a clip: all of it, or the last few seconds."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def show(self, state):
        replay = (state or {}).get("replay") or {}
        if state is None:
            text = NOT_RUNNING
        elif not replay.get("running"):
            text = "Replay off"
        else:
            text = _length(self.setting("seconds", 0) or replay.get("seconds") or 0)
        self.set_bottom_label(text)

    def on_key_down(self):
        seconds = self.setting("seconds", 0)
        self.send("save-clip", **({"seconds": seconds} if seconds else {}))

    def on_notice(self, notice):
        """The key lights up green when a clip lands, however it was saved,
        and shows an error when saving failed."""
        if notice.get("kind") == "clip_saved":
            self.set_background_color(list(FLASH))
            threading.Timer(FLASH_SECONDS, self._unflash).start()
        elif notice.get("kind") == "clip_not_saved":
            self.show_error(duration=2)

    def _unflash(self):
        try:
            self.set_background_color([0, 0, 0, 0])
        except Exception:      # the key went away meanwhile
            pass

    def get_config_rows(self):
        return [self.choice_row("Length", "seconds", SAVE_LENGTHS, 0)]


class ShowVertex(VertexAction):
    """Brings the Vertex window to the front."""

    def on_key_down(self):
        self.send("show")
