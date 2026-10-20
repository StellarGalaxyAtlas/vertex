"""Settings › Recording's audio tracks: the device each one records and, where
the recorder can set it, how loud."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QSlider, QWidget

from vertex.config import TRACK_VOLUME_RANGE
from vertex.media import roles
from vertex.recorder import backend, gsr
from vertex.ui import theme
from vertex.ui.settings.clip_choices import fill
from vertex.ui.widgets import label

# (role, the row's name): one track each, in the clip's order.
TRACKS = ((roles.GAME, "Game"), (roles.CHAT, "Chat"), (roles.MEDIA, "Media"),
          (roles.MIC, "Microphone"))


def tracks_note() -> str:
    """The line under the table."""
    return ("Each is saved as a separate audio track; one set to None isn't recorded."
            + (" The volume is what the track is recorded at, so clips play back right "
               "at 100%." if backend.has_track_volume() else ""))


class TrackTable(QWidget):
    """A row per track: its name, the device it records, its volume."""

    changed = Signal()

    def __init__(self, with_volume: bool, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 2)
        grid.addWidget(label("Track", "Dim"), 0, 0)
        grid.addWidget(label("Records", "Dim"), 0, 1)
        if with_volume:
            grid.addWidget(label("Recording volume", "Dim"), 0, 2, 1, 2)
        self.devices: dict[str, QComboBox] = {}
        self.volumes: dict[str, QSlider] = {}
        self.readouts: dict[str, QWidget] = {}
        for row, (role, name) in enumerate(TRACKS, start=1):
            grid.addWidget(label(name), row, 0)
            device = QComboBox()
            device.setMinimumWidth(190)
            device.currentIndexChanged.connect(lambda _i, r=role.id: self._device_changed(r))
            self.devices[role.id] = device
            grid.addWidget(device, row, 1)
            if not with_volume:
                continue
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(*TRACK_VOLUME_RANGE)
            slider.setMinimumWidth(120)
            theme.style(slider, lambda r=role.id: (
                f"QSlider::sub-page:horizontal {{ background: {theme.channel_colour(r)}; "
                f"border-radius: 2px; }} QSlider::sub-page:horizontal:disabled {{ "
                f"background: {theme.EDGE}; }}"))
            slider.setToolTip("Double-click to reset to 100%")
            slider.mouseDoubleClickEvent = lambda _e, s=slider: s.setValue(100)
            slider.valueChanged.connect(lambda _v, r=role.id: self._volume_changed(r))
            self.volumes[role.id] = slider
            grid.addWidget(slider, row, 2)
            readout = label("100%", "Muted")
            readout.setFixedWidth(44)
            readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.readouts[role.id] = readout
            grid.addWidget(readout, row, 3)
        if with_volume:
            grid.setColumnStretch(2, 3)

    def show_devices(self, devices: list[tuple[str, str]], rec) -> None:
        """Each track's choices: none, the default, then the real devices the
        recorder can record (`devices`: its names and descriptions). One
        missing now says what records in its place."""
        outputs, inputs = [], []
        for name, description in devices:
            if name.startswith("default_"):
                continue
            if backend.is_output(name):
                outputs.append((f"device:{name}", description.removeprefix("Monitor of ")))
            else:
                inputs.append((f"device:{name}", description))
        for role, _name in TRACKS:
            fallback = gsr.fallback_source(role.id)
            output = fallback == "default_output"
            instead = "default output" if output else "default microphone"
            fill(self.devices[role.id],
                 [("", "None"), (fallback, "Default output" if output else "Default microphone"),
                  *(outputs if output else inputs)],
                 getattr(rec, f"{role.id}_audio"),
                 lambda value, instead=instead: f"{value.removeprefix('device:')} "
                                                f"(not available: {instead})")
            self._show(role.id)

    def load(self, rec) -> None:
        for role_id, slider in self.volumes.items():
            slider.blockSignals(True)
            slider.setValue(getattr(rec, f"{role_id}_volume"))
            slider.blockSignals(False)
            self._show(role_id)

    def apply(self, rec) -> None:
        for role_id, device in self.devices.items():
            if device.currentData() is not None:
                setattr(rec, f"{role_id}_audio", device.currentData())
        for role_id, slider in self.volumes.items():
            setattr(rec, f"{role_id}_volume", slider.value())

    def _device_changed(self, role_id: str) -> None:
        self._show(role_id)
        self.changed.emit()

    def _volume_changed(self, role_id: str) -> None:
        self._show(role_id)
        self.changed.emit()

    def _show(self, role_id: str) -> None:
        """A track that records nothing has no volume to set."""
        if role_id not in self.volumes:
            return
        on = bool(self.devices[role_id].currentData())
        self.volumes[role_id].setEnabled(on)
        self.readouts[role_id].setEnabled(on)
        self.readouts[role_id].setText(f"{self.volumes[role_id].value()}%")
