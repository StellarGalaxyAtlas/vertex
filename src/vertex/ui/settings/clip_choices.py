"""The basic recording choices: the monitor, a clip's duration, its video
quality, resolution and frame rate, and how big a clip comes out.

Settings › Recording and first-run setup both show these, built here once so
they look and behave the same in both places.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from vertex import fmt
from vertex.config import Config, RecorderConfig
from vertex.recorder import gsr, monitors, presets
from vertex.ui import screens, theme
from vertex.ui.settings import monitors as monitor_map
from vertex.ui.widgets import FieldGrid, Meter, Section, label

# Video quality levels by GSR's names (see recorder.presets), as Vertex calls them.
QUALITY_NAMES = {"medium": "Low", "high": "Medium", "very_high": "High", "ultra": "Ultra"}


def mbps(kbps: int) -> str:
    return f"{kbps / 1000:g} Mbps"


def fill(widget: QComboBox, items, current, describe) -> None:
    """Fill a drop-down and keep `current` chosen. A value it doesn't offer,
    from older settings, stays chosen too, written out by `describe`."""
    widget.blockSignals(True)
    widget.clear()
    for value, text in items:
        widget.addItem(text, value)
    if widget.findData(current) < 0:
        widget.addItem(describe(current), current)
    widget.setCurrentIndex(widget.findData(current))
    widget.blockSignals(False)


class ClipChoices(QObject):
    """The monitor map and the four drop-downs under it.

    `changed` fires when a monitor is picked or a drop-down changes,
    `quality_picked` when a video quality is chosen by hand, and
    `monitors_changed` when the desktop's monitors are plugged in, unplugged
    or rearranged (after the map has been redrawn).
    """

    changed = Signal()
    quality_picked = Signal()
    monitors_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.capture = "screen"
        self.capture_options: list[gsr.CaptureOption] = []
        self.capture_note = label("", "Muted")
        self.monitor_map = monitor_map.MonitorMap()
        self.monitor_map.picked.connect(self.pick_monitor)
        # Plugging in, unplugging or rearranging monitors redraws the map.
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._watch_screen)
        app.screenRemoved.connect(self._screens_changed)
        for screen in app.screens():
            self._watch_screen(screen, initial=True)
        self.duration = QComboBox()
        self.video_quality = QComboBox()
        self.resolution = QComboBox()
        self.fps = QComboBox()
        self.grid = FieldGrid()
        for title, widget in (("Duration", self.duration), ("Video quality", self.video_quality),
                              ("Resolution", self.resolution), ("Frame rate", self.fps)):
            self.grid.add(title, widget)
        for widget in (self.duration, self.resolution, self.fps):
            widget.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.video_quality.activated.connect(lambda _i: self.quality_picked.emit())

    def add_to(self, section: Section) -> None:
        section.add_row("Monitor", self.capture_note, "Click the monitor to record.")
        section.add(self.monitor_map)
        section.add(self.grid)

    # --- The monitor --------------------------------------------------------------

    def set_capture_options(self, options: list[gsr.CaptureOption]) -> None:
        """What GPU Screen Recorder says it can record ([] when it can't say)."""
        self.capture_options = list(options)
        self.show_capture()

    def show_capture(self) -> None:
        """Draw the monitors, mark the one that will be recorded, and say which."""
        arranged = monitors.arrange(self.capture_options, screens.desktop_screens())
        self.monitor_map.set_monitors(arranged)
        recorded = monitors.target(self.capture, arranged)
        self.monitor_map.set_current(recorded)
        chosen = next((m for m in arranged if m.name == recorded), None)
        size = monitor_map.resolution(chosen) if chosen else ""
        warn = False
        if chosen is None:
            text, tip, warn = "No monitors found", "", True
        elif recorded == self.capture:
            text, tip = " · ".join(part for part in (recorded, size) if part), ""
        elif not monitors.names_monitor(self.capture):
            text = f"{recorded} · primary monitor" if chosen.primary else recorded
            tip = "No monitor picked yet, so Vertex records this one."
        else:
            text, warn = f"{self.capture} isn't connected · recording {recorded}", True
            tip = (f"{self.capture} isn't connected, so Vertex records {recorded} until it "
                   f"is back. Click a monitor to record that one instead.")
        self.capture_note.setText(text)
        self.capture_note.setToolTip(tip)
        theme.style(self.capture_note, lambda: f"color: {theme.WARN};" if warn else "")

    def pick_monitor(self, name: str) -> None:
        self.capture = name
        self.show_capture()
        self.changed.emit()

    def _watch_screen(self, screen, initial: bool = False) -> None:
        screen.geometryChanged.connect(self._screens_changed)
        if not initial:
            self._screens_changed()

    def _screens_changed(self, *_args) -> None:
        # Qt may still list a screen while announcing its removal; look once it's gone.
        QTimer.singleShot(0, self._rearrange)

    def _rearrange(self) -> None:
        self.show_capture()
        self.monitors_changed.emit()

    # --- The drop-downs ---------------------------------------------------------------

    def recorded(self, rec: RecorderConfig) -> RecorderConfig:
        """The settings as GSR will get them, for the monitor that is recorded."""
        return presets.resolve(rec, self.monitor_map.monitors)

    def show(self, rec: RecorderConfig) -> None:
        """Offer the durations, sizes, qualities and frame rates for the monitor
        recorded: sizes up to its own, turned with it, and each quality with the
        bitrate it comes to at the chosen size and frame rate."""
        monitor = presets.recorded_monitor(rec, self.monitor_map.monitors)
        pixels = monitor.pixels if monitor and all(monitor.pixels) else (0, 0)
        fill(self.duration, [(s, f"{s} seconds") for s in presets.DURATIONS],
             rec.replay_seconds, lambda s: f"{s} seconds")
        fill(self.fps, [(f, f"{f} fps") for f in presets.FRAME_RATES], rec.fps,
             lambda f: f"{f} fps")

        sizes = []
        for height in presets.HEIGHTS:
            if pixels[0] and height >= min(pixels):
                continue
            width, tall = presets.output_size(f"{height}p", pixels)
            sizes.append((f"{height}p", f"{height}p · {width} × {tall}" if pixels[0]
                          else f"{height}p"))
        sizes.append(("", f"Native · {pixels[0]} × {pixels[1]}" if pixels[0] else "Native"))
        fill(self.resolution, sizes, rec.resolution, lambda r: r.replace("x", " × "))

        constant = rec.bitrate_mode == "cbr"
        size = presets.output_size(rec.resolution, pixels)
        levels = []
        for level in presets.LEVELS:
            name = QUALITY_NAMES[level]
            if constant:
                name += f" · {mbps(presets.video_kbps(level, size, rec.fps))}"
            levels.append((level, name))
        current = rec.quality
        if constant and rec.bitrate_kbps:
            levels.append(("custom", f"Custom · {mbps(rec.bitrate_kbps)}"))
            current = "custom"
        fill(self.video_quality, levels, current, lambda q: q.replace("_", " ").capitalize())

    def apply(self, rec: RecorderConfig) -> None:
        """Write the choices into `rec`."""
        rec.capture = self.capture
        # Empty only while the drop-downs are first being filled in.
        for widget, name in ((self.duration, "replay_seconds"), (self.resolution, "resolution"),
                             (self.fps, "fps")):
            if widget.currentData() is not None:
                setattr(rec, name, widget.currentData())
        if self.video_quality.currentData() not in (None, "custom"):
            rec.quality = self.video_quality.currentData()


class ClipSize(QWidget):
    """How big a clip gets with these settings: the size, a bar against the
    biggest the choices allow, and what the replay buffer holds meanwhile."""

    def __init__(self, parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(label("CLIP SIZE", "Group"))
        self.figure = label()
        self.figure.setStyleSheet("font-size: 13pt; font-weight: 600;")
        column.addWidget(self.figure)
        self.meter = Meter()
        column.addWidget(self.meter)
        self.detail = label("", "Dim", wrap=True)
        column.addWidget(self.detail)
        column.addStretch(1)

    def estimate(self, config: Config,
                 recorded: Callable[[RecorderConfig], RecorderConfig]) -> int:
        """Show the estimate for `config`, with `recorded` turning its recorder
        settings into what GSR gets (ClipChoices.recorded). Returns the bytes."""
        rec = config.recorder
        tracks = len(gsr.audio_tracks(config))
        size = presets.clip_bytes(recorded(rec), tracks)
        largest = presets.clip_bytes(recorded(dataclasses.replace(
            rec, quality=presets.LEVELS[-1], resolution="", fps=max(presets.FRAME_RATES),
            replay_seconds=max(presets.DURATIONS), bitrate_kbps=0)), tracks)
        constant = rec.bitrate_mode == "cbr"
        self.figure.setText(f"{'About' if constant else 'Roughly'} {fmt.size(size, 0)} per clip")
        self.meter.set_fraction(size / largest if largest else 0)
        where = "in memory" if rec.replay_storage == "ram" else "on disk"
        detail = f"The replay buffer holds about {fmt.size(size, 0)} {where} while it runs."
        if not constant:
            detail = f"It depends on what is on screen. {detail}"
        self.detail.setText(detail)
        return size
