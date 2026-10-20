"""The clip's audio tracks, in Settings › Recording and in setup: the device
each one records."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QWidget

from vertex.audio import channels
from vertex.recorder import gsr
from vertex.ui.settings.clip_choices import fill
from vertex.ui.widgets import label

# (channel, the row's name, the Sonar channels it can record): one track
# each, in the clip's order.
TRACKS = ((channels.GAME, "Game", channels.OUTPUTS), (channels.CHAT, "Chat", channels.OUTPUTS),
          (channels.MEDIA, "Media", channels.OUTPUTS), (channels.MIC, "Microphone",
                                                        (channels.MIC,)))

NOTE = "Each is saved as a separate audio track; one set to None isn't recorded."


class TrackTable(QWidget):
    """A row per track: its name and the device it records."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.addWidget(label("Track", "Dim"), 0, 0)
        grid.addWidget(label("Records", "Dim"), 0, 1)
        self.devices: dict[str, QComboBox] = {}
        for row, (channel, name, _own) in enumerate(TRACKS, start=1):
            grid.addWidget(label(name), row, 0)
            device = QComboBox()
            device.setMinimumWidth(190)
            device.currentIndexChanged.connect(lambda _i: self.changed.emit())
            self.devices[channel.id] = device
            grid.addWidget(device, row, 1)

    def show_devices(self, devices: list[tuple[str, str]], rec) -> None:
        """Each track's choices: none, the default, Sonar's channels (always:
        Sonar may just be off), then the real devices GSR can record
        (`devices`: its names and descriptions). One missing now says what
        records in its place."""
        known = {name for name, _d in devices}
        outputs, inputs = [], []
        for name, description in devices:
            if name.startswith("default_") or name.startswith(channels.NODE_PREFIX):
                continue
            if name.endswith(".monitor"):
                outputs.append((f"device:{name}", description.removeprefix("Monitor of ")))
            else:
                inputs.append((f"device:{name}", description))
        for channel, _name, own in TRACKS:
            fallback = gsr.fallback_source(channel.id)
            output = fallback == "default_output"
            instead = "default output" if output else "default microphone"
            items = [("", "None"), (fallback, "Default output" if output
                                    else "Default microphone")]
            for sonar in own:
                text = sonar.description
                if known and sonar.record_source not in known:
                    text += f" (Sonar off: {instead})"
                items.append((f"device:{sonar.record_source}", text))
            fill(self.devices[channel.id], items + (outputs if output else inputs),
                 getattr(rec, f"{channel.id}_audio"),
                 lambda value, instead=instead: f"{value.removeprefix('device:')} "
                                                f"(not available: {instead})")

    def apply(self, rec) -> None:
        for channel_id, device in self.devices.items():
            if device.currentData() is not None:
                setattr(rec, f"{channel_id}_audio", device.currentData())
