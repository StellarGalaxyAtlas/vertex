"""One mixer row per audio track: colour, mute, name, volume, readout."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSlider, QWidget

from vertex.media.probe import AudioTrack
from vertex.ui import icons, theme
from vertex.ui.editor.timeline import LANE_H
from vertex.ui.widgets import IconButton, label

PANEL_W = 340
MAX_GAIN = 150        # percent; a quiet track can be lifted, not just lowered


class TrackRow(QWidget):
    changed = Signal()

    def __init__(self, track: AudioTrack, colour: str, parent=None):
        super().__init__(parent)
        self.track = track
        self.setFixedHeight(LANE_H)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        bar = QFrame()
        bar.setFixedSize(3, LANE_H - 6)
        bar.setStyleSheet(f"background: {colour}; border-radius: 1px;")
        layout.addWidget(bar)
        self.mute = IconButton("volume", "Mute", 16, theme.TEXT_MUTED)
        self.mute.clicked.connect(self.toggle_mute)
        layout.addWidget(self.mute)
        icon = QLabel()
        icon.setPixmap(icons.pixmap(icons.channel_icon_name(track.channel), colour, 14))
        layout.addWidget(icon)
        name = label(track.label, "Muted")
        name.setToolTip(track.name)
        layout.addWidget(name, 1)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, MAX_GAIN)
        self.slider.setFixedWidth(130)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.setValue(round(track.volume * 100))
        self.slider.setStyleSheet(
            f"QSlider::sub-page:horizontal {{ background: {colour}; border-radius: 2px; }}")
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.setToolTip("Double-click to reset to 100%")
        self.slider.mouseDoubleClickEvent = lambda _e: self.slider.setValue(100)
        layout.addWidget(self.slider)
        self.readout = label("", "Muted")
        self.readout.setFixedWidth(44)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.readout)
        self._refresh()

    def _refresh(self) -> None:
        muted = self.track.muted
        self.mute.set_icon("mute" if muted else "volume",
                           theme.DANGER if muted else theme.TEXT_MUTED)
        self.mute.setToolTip("Unmute" if muted else "Mute")
        self.readout.setText("muted" if muted else f"{round(self.track.volume * 100)}%")

    def toggle_mute(self) -> None:
        self.track.muted = not self.track.muted
        self._refresh()
        self.changed.emit()

    def _on_slider(self, value: int) -> None:
        self.track.volume = value / 100
        self.track.muted = False        # touching the slider un-mutes, as expected
        self._refresh()
        self.changed.emit()
