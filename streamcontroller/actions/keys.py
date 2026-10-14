"""The keys: a channel's volume, the next output or mic, save a clip, and
bring Vertex to the front."""

from __future__ import annotations

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


SAVE_LENGTHS = ((0, "Replay length"), (10, "10 seconds"), (30, "30 seconds"),
                (60, "1 minute"), (300, "5 minutes"), (600, "10 minutes"), (1800, "30 minutes"))


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

    def get_config_rows(self):
        return [self.choice_row("Length", "seconds", SAVE_LENGTHS, 0)]


class ShowVertex(VertexAction):
    """Brings the Vertex window to the front."""

    def on_key_down(self):
        self.send("show")
