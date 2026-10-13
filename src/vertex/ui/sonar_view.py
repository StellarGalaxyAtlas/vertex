"""The Sonar page: channel strips, devices, and which app plays where."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vertex.audio import channels
from vertex.audio.sonar import AppCapture, AppStream, SonarStatus
from vertex.ui import icons, theme
from vertex.ui.widgets import ElidedLabel, FlowLayout, IconButton, Section, Toggle, hline, label

APP_MIME = "application/x-vertex-app"


def app_icon(icon_name: str, key: str, name: str, size: int = 22) -> QLabel:
    """The app's own icon from the desktop's icon theme, or its initial."""
    badge = QLabel()
    badge.setFixedSize(size, size)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    for candidate in (icon_name, key):
        icon = QIcon.fromTheme(candidate) if candidate else QIcon()
        if not icon.isNull():
            badge.setPixmap(icon.pixmap(size, size))
            return badge
    badge.setText((name[:1] or "?").upper())
    badge.setStyleSheet(f"background: {theme.game_colour(key)}; border-radius: 6px; "
                        f"color: white; font-weight: 700; font-size: 8pt;")
    return badge


class AppChip(QFrame):
    """One application. Drag it onto a channel to send it there for good;
    right-click for the same without dragging."""

    def __init__(self, view, key: str, name: str, icon: str = "", note: str = "",
                 rule: str | None = None, draggable: bool = True, dim: bool = False,
                 tooltip: str = "", warn: bool = False, parent=None):
        super().__init__(parent)
        self.view = view
        self.key = key
        self.name = name
        self.rule = rule
        self.draggable = draggable
        self._press = None
        self.setObjectName("AppChip")
        self.setStyleSheet(
            f"#AppChip {{ background: {theme.CARD_BG}; border-radius: 8px; }}"
            f"#AppChip:hover {{ background: {theme.CARD_HOVER}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)
        layout.addWidget(app_icon(icon, key, name))
        text = QVBoxLayout()
        text.setSpacing(0)
        title = ElidedLabel(name)
        if dim:
            title.setStyleSheet(f"color: {theme.TEXT_DIM};")
        text.addWidget(title)
        if note:
            detail = ElidedLabel(note)
            detail.setObjectName("Dim")
            if warn:
                detail.setStyleSheet(f"color: {theme.WARN};")
            text.addWidget(detail)
        layout.addLayout(text, 1)
        if draggable:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tooltip or (f"{name} ({key}) — drag onto another channel"
                                    if draggable else f"{name} ({key})"))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.draggable or self._press is None or \
                not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < \
                QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)
        data = QMimeData()
        data.setData(APP_MIME, self.key.encode())
        drag.setMimeData(data)
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        self.view.drag_started()
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.view.drag_finished()

    def contextMenuEvent(self, event):
        if not self.draggable:
            return
        menu = QMenu(self)
        for output in channels.OUTPUTS:
            action = menu.addAction(icons.icon(icons.channel_icon_name(output.id),
                                               theme.channel_colour(output.id), 16),
                                    f"Send to {output.label}")
            action.triggered.connect(lambda _c=False, c=output.id: self.view.route(self.key, c))
        if self.rule:
            menu.addSeparator()
            reset = menu.addAction("Use the default channel")
            reset.setToolTip("Forget where this app was sent")
            reset.triggered.connect(lambda: self.view.route(self.key, None))
        menu.exec(event.globalPos())


class ChannelColumn(QFrame):
    """One channel: its volume and the apps on it. Output channels accept
    dropped apps."""

    def __init__(self, view, controller, channel: channels.Channel, parent=None):
        super().__init__(parent)
        self.view = view
        self.controller = controller
        self.channel = channel
        self.colour = theme.channel_colour(channel.id)
        self.setObjectName("Strip")
        self._paint_frame(False)
        self.setMinimumWidth(170)
        self.setAcceptDrops(channel.is_output)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel()
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icons.pixmap(icons.channel_icon_name(channel.id), self.colour, 20))
        badge.setStyleSheet(f"background: {theme.shade(self.colour, 0.25)}; border-radius: 10px;")
        header.addWidget(badge)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = label(channel.label)
        name.setStyleSheet("font-weight: 600;")
        names.addWidget(name)
        device = label(channel.description, "Dim")
        device.setToolTip(f"{channel.blurb}\nDevice: {channel.node}")
        names.addWidget(device)
        header.addLayout(names, 1)
        layout.addLayout(header)

        volume = QHBoxLayout()
        volume.setSpacing(6)
        self.mute = IconButton("volume", "Mute", 16, theme.TEXT_MUTED)
        self.mute.setCheckable(True)
        self.mute.toggled.connect(self._on_mute)
        volume.addWidget(self.mute)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.setStyleSheet(
            f"QSlider::sub-page:horizontal {{ background: {self.colour}; border-radius: 2px; }}")
        self.slider.valueChanged.connect(self._on_slider)
        volume.addWidget(self.slider, 1)
        self.readout = label("100%", "Muted")
        self.readout.setFixedWidth(38)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        volume.addWidget(self.readout)
        layout.addLayout(volume)

        layout.addWidget(hline())
        layout.addWidget(label("RECORDING FROM IT" if not channel.is_output else "APPS",
                               "Group"))
        self.apps = QVBoxLayout()
        self.apps.setSpacing(6)
        layout.addLayout(self.apps)
        layout.addStretch(1)

        settings = controller.context.config.sonar.channel(channel.id)
        self._quiet = True
        self.slider.setValue(round(settings.volume * 100))
        self.mute.setChecked(settings.muted)
        self._quiet = False
        self._paint_mute()
        self.set_apps([])

    # --- Volume ----------------------------------------------------------------

    def show_status(self, volume: float, muted: bool) -> None:
        """Follow the device — the system mixer can change it too."""
        if self.slider.isSliderDown():
            return
        self._quiet = True
        self.slider.setValue(round(volume * 100))
        self.mute.setChecked(muted)
        self._quiet = False
        self._paint_mute()

    def _on_slider(self, value: int) -> None:
        self.readout.setText(f"{value}%")
        if not self._quiet:
            self.controller.set_volume(self.channel.id, value / 100)

    def _on_mute(self, muted: bool) -> None:
        self._paint_mute()
        if not self._quiet:
            self.controller.context.config.sonar.channel(self.channel.id).muted = muted
            self.controller.set_muted(self.channel.id, muted)

    def _paint_mute(self) -> None:
        muted = self.mute.isChecked()
        self.mute.set_icon("mute" if muted else "volume",
                           theme.DANGER if muted else theme.TEXT_MUTED)
        self.mute.setToolTip("Unmute" if muted else "Mute")

    # --- Apps ------------------------------------------------------------------

    def set_apps(self, chips: list[QWidget]) -> None:
        while self.apps.count():
            item = self.apps.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for chip in chips:
            self.apps.addWidget(chip)
        if not chips:
            empty = ("Drop an app here" if self.channel.is_output
                     else "No app is using the mic")
            hint = label(empty, "Dim")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setMinimumHeight(36)
            hint.setStyleSheet(f"color: {theme.TEXT_DIM}; border: 1px dashed {theme.SEAM}; "
                               f"border-radius: 8px;")
            self.apps.addWidget(hint)

    def _paint_frame(self, highlight: bool) -> None:
        border = self.colour if highlight else "transparent"
        self.setStyleSheet(f"#Strip {{ background: {theme.SECTION_BG}; border-radius: 14px; "
                           f"border: 2px solid {border}; }}")

    def dragEnterEvent(self, event):
        if self.channel.is_output and event.mimeData().hasFormat(APP_MIME):
            event.acceptProposedAction()
            self._paint_frame(True)

    def dragLeaveEvent(self, event):
        self._paint_frame(False)

    def dropEvent(self, event):
        self._paint_frame(False)
        key = bytes(event.mimeData().data(APP_MIME)).decode()
        if key:
            event.acceptProposedAction()
            self.view.route(key, self.channel.id)


class DeviceField(QWidget):
    """One device setting: a badge and title, what it does, then its drop-down."""

    def __init__(self, title: str, hint: str, combo: QComboBox, parent=None):
        super().__init__(parent)
        self.colour = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.badge = QLabel()
        self.badge.setFixedSize(26, 26)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.badge)
        name = label(title)
        name.setStyleSheet("font-weight: 600;")
        header.addWidget(name, 1)
        layout.addLayout(header)
        self.hint = label(hint, "Dim", wrap=True)
        layout.addWidget(self.hint)
        # Hints wrap to different heights; the stretch keeps the three
        # drop-downs level with each other.
        layout.addStretch(1)
        # A combo box is as wide as its longest device name unless told
        # otherwise, and some are very long.
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(10)
        layout.addWidget(combo)

    def set_colour(self, icon_name: str, colour: str) -> None:
        self.colour = colour
        self.badge.setPixmap(icons.pixmap(icon_name, colour, 16))
        self.badge.setStyleSheet(f"background: {theme.shade(colour, 0.25)}; border-radius: 8px;")


class SonarView(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.controller = context.sonar
        self._names: dict[str, str] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(theme.CONTENT_MARGIN, 18, theme.CONTENT_MARGIN, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(label("Sonar", "Heading"))
        self.subtitle = label("", "Muted", wrap=True)
        title.addWidget(self.subtitle)
        header.addLayout(title, 1)
        self.toggle = Toggle(context.config.sonar.enabled)
        self.toggle.toggled.connect(self.controller.set_enabled)
        header.addWidget(label("Enabled", "Muted"))
        header.addWidget(self.toggle)
        layout.addLayout(header)

        self.strips_host = QWidget()
        strips = QHBoxLayout(self.strips_host)
        strips.setContentsMargins(0, 0, 0, 0)
        strips.setSpacing(12)
        self.strips: dict[str, ChannelColumn] = {}
        for channel in channels.ALL:
            column = ChannelColumn(self, self.controller, channel)
            strips.addWidget(column, 1)
            self.strips[channel.id] = column
        layout.addWidget(self.strips_host)

        # Apps that picked an output themselves, past every channel. Only
        # shown while there are any.
        self.unrouted = Section("Not routed", "These apps play straight to a device instead "
                                              "of the default, so no channel controls them. "
                                              "Drag one onto a channel to route it.")
        self.unrouted_host = QWidget()
        self.unrouted_flow = FlowLayout(self.unrouted_host, spacing=8)
        self.unrouted.add(self.unrouted_host)
        self.unrouted.hide()
        layout.addWidget(self.unrouted)

        self.devices = Section("Devices")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.output = QComboBox()
        self.mic = QComboBox()
        self.default_channel = QComboBox()
        for output in channels.OUTPUTS:
            self.default_channel.addItem(
                icons.icon(icons.channel_icon_name(output.id), theme.channel_colour(output.id), 16),
                output.label, output.id)
        self.default_channel.setCurrentIndex(
            max(0, self.default_channel.findData(context.config.sonar.default_channel)))
        self.output_field = DeviceField(
            "Output", "The headset or speakers every channel plays through.", self.output)
        self.output_field.set_colour("headphones", theme.TEXT_MUTED)
        self.mic_field = DeviceField(
            "Microphone", "The real mic behind Vertex Mic. In Discord and other chat apps, "
                          "pick Vertex Mic as the input.", self.mic)
        self.mic_field.set_colour(icons.channel_icon_name("mic"), theme.channel_colour("mic"))
        self.unrouted_field = DeviceField(
            "Unrouted apps", "The channel apps play on until you drag them to another one.",
            self.default_channel)
        self._paint_unrouted()
        for field in (self.output_field, self.mic_field, self.unrouted_field):
            row.addWidget(field, 1)
        self.devices.body.addLayout(row)
        layout.addWidget(self.devices)
        self.output.activated.connect(lambda _i: self.controller.set_output(
            self.output.currentData() or ""))
        self.mic.activated.connect(lambda _i: self.controller.set_mic(
            self.mic.currentData() or ""))
        self.default_channel.activated.connect(self._on_default_channel)

        layout.addStretch(1)

        self.controller.status_changed.connect(self._show_status)
        self._dragging = False
        self._pending: dict[str, list] = {}
        self.controller.streams_changed.connect(lambda s: self._update("streams", s))
        self.controller.recorders_changed.connect(lambda r: self._update("recorders", r))
        self.controller.devices_changed.connect(self._show_devices)
        self._show_status(self.controller.status)

    def showEvent(self, event):
        super().showEvent(event)
        self.controller.refresh()
        self.controller.refresh_streams()
        self.controller.refresh_devices()

    def _show_status(self, status: SonarStatus) -> None:
        enabled = self.context.config.sonar.enabled
        if self.toggle.isChecked() != enabled:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(enabled)
            self.toggle.blockSignals(False)
        if not status.available and status.error:
            self.subtitle.setText(f"No audio server: {status.error}")
        elif enabled and status.active:
            output = self._names.get(status.output, status.output)
            where = f" through {output}" if output else ""
            self.subtitle.setText(f"Running — every channel plays{where}.")
        elif enabled:
            self.subtitle.setText("Starting…")
        else:
            self.subtitle.setText("Off. Turn it on to create Vertex's virtual devices: one "
                                  "output per channel and a shared Vertex Mic.")
        self.strips_host.setEnabled(enabled and status.active)
        for channel_id, entry in status.channels.items():
            if entry.present:
                self.strips[channel_id].show_status(entry.volume, entry.muted)

    def _on_default_channel(self, _index: int) -> None:
        self._paint_unrouted()
        self.controller.set_default_channel(self.default_channel.currentData())

    def _paint_unrouted(self) -> None:
        """The Unrouted apps badge takes the colour of the channel it names, so
        it matches that channel's column above."""
        channel_id = self.default_channel.currentData() or channels.OUTPUTS[0].id
        self.unrouted_field.set_colour(icons.channel_icon_name(channel_id),
                                       theme.channel_colour(channel_id))

    def _show_devices(self, outputs, inputs) -> None:
        self._names = {device.name: device.label for device in [*outputs, *inputs]}
        self._show_status(self.controller.status)
        sonar = self.context.config.sonar
        for combo, devices, current in ((self.output, outputs, sonar.output_device),
                                        (self.mic, inputs, sonar.mic_device)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("System default", "")
            for device in devices:
                combo.addItem(device.label, device.name)
            if current and combo.findData(current) < 0:
                combo.addItem(f"{current} (not connected)", current)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)

    # --- Apps on channels --------------------------------------------------------

    def route(self, key: str, channel_id: str | None) -> None:
        """Send an app to a channel from now on (None: back to the default)."""
        self.controller.route(key, channel_id)

    def drag_started(self) -> None:
        self._dragging = True

    def drag_finished(self) -> None:
        # Lists that changed mid-drag were held back: rebuilding them would
        # have deleted the very chip being dragged.
        self._dragging = False
        pending, self._pending = self._pending, {}
        for kind, items in pending.items():
            self._update(kind, items)

    def _update(self, kind: str, items: list) -> None:
        if self._dragging:
            self._pending[kind] = items
        elif kind == "streams":
            self._show_streams(items)
        else:
            self._show_recorders(items)

    def _show_streams(self, streams: list[AppStream]) -> None:
        """Each app under the channel it plays on; apps with a rule that are
        not playing are shown faintly under the channel they will go to."""
        rules = dict(self.context.config.sonar.app_rules)
        per_channel: dict[str, dict[str, AppChip]] = {c.id: {} for c in channels.OUTPUTS}
        unrouted: dict[str, AppChip] = {}
        playing = set()
        for stream in streams:
            playing.add(stream.key)
            if stream.channel in per_channel:
                bucket = per_channel[stream.channel]
                if stream.key not in bucket or stream.stuck:
                    bucket[stream.key] = self._chip(stream, rules.get(stream.key))
            elif stream.key not in unrouted:
                unrouted[stream.key] = self._chip(
                    stream, rules.get(stream.key),
                    f"on {stream.device}" if stream.device else "")
        for key, channel_id in sorted(rules.items()):
            if key not in playing and channel_id in per_channel:
                per_channel[channel_id][key] = AppChip(
                    self, key, key, note="not playing", rule=channel_id, dim=True,
                    tooltip=f"{key} goes to {channels.BY_ID[channel_id].label} whenever it "
                            f"plays. Drag it to change that; right-click to reset it.")
        for channel_id, chips in per_channel.items():
            self.strips[channel_id].set_apps(list(chips.values()))

        while self.unrouted_flow.count():
            item = self.unrouted_flow.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for chip in unrouted.values():
            # A flow layout sizes children by their hint, and an eliding
            # label hints next to nothing — give the chips a real width.
            chip.setFixedWidth(240)
            self.unrouted_flow.addWidget(chip)
        self.unrouted.setVisible(bool(unrouted) and self.context.config.sonar.enabled)

    def _chip(self, stream: AppStream, rule: str | None, note: str = "") -> AppChip:
        if stream.stuck:
            target = channels.BY_ID[stream.rule].label
            return AppChip(
                self, stream.key, stream.name, stream.icon, rule=rule,
                note=f"still here — moving to {target}…", warn=True,
                tooltip=f"Part of {stream.name}'s sound hasn't moved to {target} yet: the "
                        f"audio server refused, which happens while a stream is starting "
                        f"or stopping. Vertex retries on every change. If it stays, "
                        f"restarting the app's audio moves it.")
        return AppChip(self, stream.key, stream.name, stream.icon, note=note, rule=rule)

    def _show_recorders(self, recorders: list[AppCapture]) -> None:
        """Apps recording the mic, under the Mic channel. One recording the
        real mic directly is flagged: Vertex Mic's volume and mute don't reach it."""
        chips: dict[str, AppChip] = {}
        for capture in recorders:
            if capture.key in chips:
                continue
            note = "" if capture.via_vertex else f"direct from {capture.device}"
            tip = (f"{capture.name} records Vertex Mic." if capture.via_vertex else
                   f"{capture.name} records {capture.device} directly, so Vertex Mic's volume "
                   f"and mute don't apply to it. Pick “Vertex Mic” as its input to change that.")
            chips[capture.key] = AppChip(self, capture.key, capture.name, capture.icon,
                                         note=note, draggable=False, tooltip=tip)
        self.strips[channels.MIC.id].set_apps(list(chips.values()))
