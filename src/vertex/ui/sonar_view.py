"""The Sonar page: channel strips, devices, and which app plays where."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt
from vertex.audio import channels, devices
from vertex.audio.pulse import from_server
from vertex.audio.sonar import AppCapture, AppStream, SonarStatus
from vertex.ui import icons, theme
from vertex.ui.widgets import (
    ElidedLabel,
    FlowLayout,
    IconButton,
    Section,
    Segmented,
    Toggle,
    button,
    hline,
    label,
)

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
    theme.style(badge, lambda: f"background: {theme.game_colour(key)}; border-radius: 6px; "
                               f"color: {theme.INK}; font-weight: 700; font-size: 8pt;")
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
        theme.style(self, lambda: f"#AppChip {{ background: {theme.CARD_BG}; border-radius: 8px; }}"
                                  f"#AppChip:hover {{ background: {theme.CARD_HOVER}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)
        layout.addWidget(app_icon(icon, key, name))
        text = QVBoxLayout()
        text.setSpacing(0)
        title = ElidedLabel(name)
        if dim:
            theme.style(title, lambda: f"color: {theme.TEXT_DIM};")
        text.addWidget(title)
        if note:
            detail = ElidedLabel(note)
            detail.setObjectName("Dim")
            if warn:
                theme.style(detail, lambda: f"color: {theme.WARN};")
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


class DeviceButton(QAbstractButton):
    """The device a channel plays through; click for the others."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(60)

    def sizeHint(self):
        return QSize(160, 30)

    def minimumSizeHint(self):
        return QSize(60, 30)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse() and self.isEnabled()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.CARD_HOVER if hover else theme.FIELD_BG))
        p.drawRoundedRect(QRectF(self.rect()), theme.RADIUS_SMALL, theme.RADIUS_SMALL)
        chevron = 16
        text_rect = self.rect().adjusted(10, 0, -(chevron + 12), 0)
        p.setPen(QColor(theme.TEXT if self.isEnabled() else theme.TEXT_DIM))
        p.setFont(self.font())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(self.font()).elidedText(self.text(), Qt.TextElideMode.ElideRight,
                                                        text_rect.width()))
        p.drawPixmap(self.width() - chevron - 8, (self.height() - chevron) // 2,
                     icons.pixmap("chevron-down", "TEXT_MUTED", chevron))


class DeviceList(QFrame):
    """A small list under a channel's device: every device it can use, the
    current one ticked. Picking one emits `picked` with its name."""

    picked = Signal(str)
    manage = Signal()

    def __init__(self, title: str, devices: list[tuple[str, str]], current: str,
                 parent=None, excluded: list[tuple[str, str]] = ()):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("DeviceList")
        self.setStyleSheet(
            f"#DeviceList {{ background: {theme.CARD_BG}; border: 1px solid {theme.SEAM}; "
            f"border-radius: 10px; }}"
            f"#DeviceList QPushButton {{ text-align: left; padding: 7px 10px; "
            f"border-radius: 8px; background: transparent; }}"
            f"#DeviceList QPushButton:hover {{ background: {theme.CARD_HOVER}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(2)
        heading = label(title, "Group")
        heading.setContentsMargins(6, 0, 0, 4)
        layout.addWidget(heading)
        self.buttons: dict[str, QPushButton] = {}
        for group, entries in ((None, devices), ("EXCLUDED DEVICES", excluded)):
            if group and entries:
                heading = label(group, "Group")
                heading.setContentsMargins(6, 8, 0, 4)
                layout.addWidget(heading)
            for name, text in entries:
                chosen = name == current
                item = QPushButton(text)
                item.setIcon(icons.icon("check", theme.ACCENT_EDGE, 16) if chosen
                             else icons.icon("check", "#00000000", 16))
                if chosen:
                    item.setStyleSheet("font-weight: 600;")
                item.setCursor(Qt.CursorShape.PointingHandCursor)
                item.clicked.connect(lambda _c=False, n=name: self.pick(n))
                layout.addWidget(item)
                self.buttons[name] = item
        if not devices and not excluded:
            layout.addWidget(label("No devices found", "Dim"))
        layout.addSpacing(6)
        manager = button("Device manager", "primary", on_click=self._manage)
        # Its own look: the list's buttons are plain, left-aligned rows.
        manager.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: {theme.ON_ACCENT}; "
            f"text-align: center; "
            f"padding: 8px; border-radius: 8px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT_HOVER}; }}")
        layout.addWidget(manager)

    def pick(self, name: str) -> None:
        self.close()
        self.picked.emit(name)

    def _manage(self) -> None:
        self.close()
        self.manage.emit()

    def show_under(self, anchor: QWidget) -> None:
        self.setMinimumWidth(max(anchor.width(), 260))
        self.adjustSize()
        self.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        self.show()


class DeviceOrder(QListWidget):
    """Devices in the order Sonar picks them, reordered by dragging. Devices
    drag between a panel's priority and excluded lists too."""

    changed = Signal()
    ROW = 34

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.placeholder = placeholder
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setIconSize(QSize(16, 16))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Long device names are cut short with "…" rather than scrolled to.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        theme.style(self, lambda: (
            f"QListWidget {{ background: {theme.FIELD_BG}; border-radius: 8px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 6px 6px; border-radius: 6px; }}"
            f"QListWidget::item:hover {{ background: {theme.CARD_HOVER}; }}"
            f"QListWidget::item:selected {{ background: {theme.ACCENT_SOFT}; "
            f"color: {theme.TEXT}; }}"))
        self._quiet = False
        self._dragging = False
        self._pending: list | None = None
        self._rows: list[tuple[str, str, bool, bool]] = []
        # A move between lists is a removal here and an insertion there:
        # report once both have happened.
        self._timer = QTimer(self, singleShot=True, interval=0)
        self._timer.timeout.connect(self.changed.emit)
        model = self.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.rowsMoved):
            signal.connect(self._touched)
        self.fill([])
        # Its rows' ticks and text take their colours from the scheme.
        theme.themed(self, lambda: self.fill(self._rows), "rows")

    def _touched(self, *_args) -> None:
        if not self._quiet:
            self._timer.start()

    def fill(self, rows: list[tuple[str, str, bool, bool]]) -> None:
        """(name, text, connected, current) for each device, in order."""
        if self._dragging:
            # Rebuilding now would delete the item being dragged.
            self._pending = rows
            return
        self._rows = rows
        self._quiet = True
        self.clear()
        for name, text, connected, current in rows:
            item = QListWidgetItem(
                icons.icon("check" if current else "grip",
                           theme.ACCENT_EDGE if current else theme.TEXT_DIM, 16),
                text if connected else f"{text} · not connected")
            item.setData(Qt.ItemDataRole.UserRole, name)
            if current:
                font = QFont(item.font())
                font.setWeight(QFont.Weight.DemiBold)
                item.setFont(font)
            if not connected:
                item.setForeground(QColor(theme.TEXT_DIM))
            item.setToolTip(f"{text}\n{name}")
            self.addItem(item)
        self._quiet = False
        self.setFixedHeight(max(2, len(rows)) * self.ROW + 10)

    def names(self) -> list[str]:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def startDrag(self, actions):
        self._dragging = True
        try:
            super().startDrag(actions)
        finally:
            self._dragging = False
            if self._pending is not None:
                rows, self._pending = self._pending, None
                self.fill(rows)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.count():
            p = QPainter(self.viewport())
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.viewport().rect().adjusted(10, 0, -10, 0),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.placeholder)


def neutral_slider() -> str:
    """A device's volume: neutral, since the accent never marks an audio control."""
    return f"QSlider::sub-page:horizontal {{ background: {theme.TEXT_MUTED}; border-radius: 2px; }}"


class DevicePanel(QFrame):
    """One kind of device in the device manager: the outputs, or the mics."""

    def __init__(self, view, kind: str, title: str, icon_name: str, colour: str,
                 parent=None):
        super().__init__(parent)
        self.view = view
        self.kind = kind                 # "output" or "mic", as in SonarConfig
        self.current = ""
        self.setObjectName("DevicePanel")
        theme.style(self, lambda: f"#DevicePanel {{ background: {theme.CARD_BG}; "
                                  f"border-radius: 12px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel()
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.themed(badge, lambda: badge.setPixmap(icons.pixmap(icon_name, colour, 18)), "icon")
        theme.style(badge, lambda: f"background: {theme.shade(theme.colour(colour), 0.25)}; "
                                   f"border-radius: 9px;")
        header.addWidget(badge)
        name = label(title)
        name.setStyleSheet("font-weight: 600;")
        header.addWidget(name, 1)
        self.mode = Segmented([("manual", "Manual"), ("auto", "Auto")], "auto")
        self.mode.changed.connect(self._on_mode)
        header.addWidget(self.mode)
        layout.addLayout(header)
        self.mode_hint = label("", "Dim", wrap=True)
        layout.addWidget(self.mode_hint)

        # The device in use, without a volume of its own: the channels'
        # sliders above set what is heard.
        self.now = ElidedLabel("")
        self.now.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.now)
        self.format = label("", "Dim")
        layout.addWidget(self.format)
        self._quiet = False

        # Outputs: a device every channel also plays through, unless the
        # channel's own "Also on" switch is off.
        self.second = None
        self.second_device = ""
        if kind == "output":
            layout.addSpacing(4)
            layout.addWidget(label("ALSO PLAY THROUGH", "Group"))
            row = QHBoxLayout()
            row.setSpacing(8)
            self.second = QComboBox()
            self.second.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.second.setMinimumContentsLength(10)
            self.second.activated.connect(lambda _i: view.controller.set_second_output(
                self.second.currentData() or ""))
            row.addWidget(self.second, 1)
            self.second_volume = QSlider(Qt.Orientation.Horizontal)
            self.second_volume.setRange(0, 100)
            self.second_volume.setFixedWidth(96)
            self.second_volume.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            theme.style(self.second_volume, neutral_slider)
            self.second_volume.setToolTip("The second device's own volume")
            self.second_volume.valueChanged.connect(self._on_second_volume)
            row.addWidget(self.second_volume)
            self.second_readout = label("", "Muted")
            self.second_readout.setFixedWidth(38)
            self.second_readout.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(self.second_readout)
            layout.addLayout(row)
            layout.addWidget(label("Every channel plays here too, unless its “Also on” "
                                   "switch is off.", "Dim", wrap=True))
            layout.addSpacing(6)
            self._second_timer = QTimer(self, singleShot=True, interval=120)
            self._second_timer.timeout.connect(lambda: view.controller.set_device_volume(
                "sink", self.second_device, self.second_volume.value() / 100))

        layout.addSpacing(4)
        layout.addWidget(label("PRIORITY", "Group"))
        self.priority = DeviceOrder("No devices found.")
        layout.addWidget(self.priority)
        layout.addWidget(label("EXCLUDED", "Group"))
        self.excluded = DeviceOrder("Drag a device here to keep Vertex from picking it "
                                    "by itself.")
        layout.addWidget(self.excluded)
        layout.addStretch(1)
        for order in (self.priority, self.excluded):
            order.changed.connect(lambda: view.device_order_changed(
                kind, self.priority.names(), self.excluded.names()))

    def show_devices(self, priority: list, excluded: list, auto: bool, current,
                     current_text: str) -> None:
        self.mode.set_current("auto" if auto else "manual")
        self._show_hint(auto)
        self.priority.fill(priority)
        self.excluded.fill(excluded)
        self.current = current.name if current is not None else ""
        self.now.setText(current_text)
        self.format.setText(devices.describe_format(current.sample_spec)
                            if current is not None else "")

    def show_second(self, choices: list[tuple[str, str]], current: str, device,
                    current_text: str, connected: bool = True) -> None:
        """The second device's drop-down: none, or a device from the list."""
        if self.second is None:
            return
        self.second.blockSignals(True)
        self.second.clear()
        self.second.addItem("Nothing else", "")
        for name, text in choices:
            self.second.addItem(text, name)
        if current and self.second.findData(current) < 0:
            # Set before it was excluded, or unplugged: kept, and shown as such.
            self.second.addItem(current_text if connected else
                                f"{current_text} (not connected)", current)
        self.second.setCurrentIndex(max(0, self.second.findData(current)))
        self.second.blockSignals(False)
        self.second_device = device.name if device is not None else ""
        self._quiet = True
        if device is not None and not self.second_volume.isSliderDown():
            self.second_volume.setValue(round(from_server(device.volume) * 100))
        self._quiet = False
        self.second_volume.setEnabled(device is not None)
        self.second_readout.setText(f"{self.second_volume.value()}%" if device is not None
                                    else "")

    def _on_second_volume(self, value: int) -> None:
        self.second_readout.setText(f"{value}%")
        if not self._quiet and self.second_device:
            self._second_timer.start()

    def _on_mode(self, key: str, _descending: bool = True) -> None:
        self._show_hint(key == "auto")
        self.view.controller.set_auto(self.kind, key == "auto")

    def _show_hint(self, auto: bool) -> None:
        device = "device" if self.kind == "output" else "mic"
        self.mode_hint.setText(
            f"Uses the highest connected {device} in the list." if auto else
            f"Uses the {device} you pick; while it is unplugged, the highest connected one.")



class ChannelColumn(QFrame):
    """One channel: its volume and the apps on it. Output channels accept
    dropped apps."""

    def __init__(self, view, controller, channel: channels.Channel, parent=None):
        super().__init__(parent)
        self.view = view
        self.controller = controller
        self.channel = channel
        self.setObjectName("Strip")
        self._paint_frame(False)
        self.setMinimumWidth(150)
        self.setAcceptDrops(channel.is_output)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel()
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.themed(badge, lambda: badge.setPixmap(
            icons.pixmap(icons.channel_icon_name(channel.id), self.colour, 20)), "icon")
        theme.style(badge, lambda: f"background: {theme.shade(self.colour, 0.25)}; "
                                   f"border-radius: 10px;")
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

        # The real device it plays through (the Mic: the mic behind it). Output
        # channels share one while linked.
        row = QHBoxLayout()
        row.setSpacing(4)
        self.link = None
        if channel.is_output:
            self.link = IconButton("link", "", 16, "ACCENT_EDGE")
            self.link.clicked.connect(lambda: view.toggle_link(channel.id))
            row.addWidget(self.link)
        self.device = DeviceButton()
        self.device.clicked.connect(lambda: view.choose_device(channel.id))
        row.addWidget(self.device, 1)
        self.current_device = ""
        layout.addLayout(row)

        # Whether it also plays through the second device, when one is set.
        self.also_row = QWidget()
        also = QHBoxLayout(self.also_row)
        also.setContentsMargins(4, 0, 0, 0)
        also.setSpacing(6)
        self.also_label = ElidedLabel("")
        self.also_label.setObjectName("Dim")
        also.addWidget(self.also_label, 1)
        self.also = Toggle()
        self.also.toggled.connect(
            lambda on: None if self._quiet else controller.set_also_second(channel.id, on))
        also.addWidget(self.also)
        layout.addWidget(self.also_row)
        self.also_row.hide()

        volume = QHBoxLayout()
        volume.setSpacing(6)
        self.mute = IconButton("volume", "Mute", 16, "TEXT_MUTED")
        self.mute.setCheckable(True)
        self.mute.toggled.connect(self._on_mute)
        volume.addWidget(self.mute)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        theme.style(self.slider, lambda: f"QSlider::sub-page:horizontal {{ background: "
                                         f"{self.colour}; border-radius: 2px; }}")
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

    @property
    def colour(self) -> str:
        return theme.channel_colour(self.channel.id)

    def show_also(self, device_text: str, on: bool, shown: bool) -> None:
        self.also_row.setVisible(shown and self.channel.is_output)
        self.also_label.setText(f"Also on {device_text}")
        self.also_row.setToolTip(f"{self.channel.label} also plays through {device_text}, "
                                 f"the second device set in the device manager."
                                 if on else f"{self.channel.label} stays off {device_text}.")
        if self.also.isChecked() != on:
            self._quiet = True
            self.also.blockSignals(True)
            self.also.setChecked(on)
            self.also.blockSignals(False)
            self._quiet = False

    def show_device(self, name: str, text: str, linked: bool) -> None:
        self.current_device = name
        self.device.setText(text)
        self.device.setToolTip(f"{self.channel.label} plays through {text}. Click to pick "
                               f"another device." if self.channel.is_output else
                               f"Vertex Mic is fed by {text}. Click to pick another mic.")
        if self.link is not None:
            self.link.set_icon("link" if linked else "unlink",
                               "ACCENT_EDGE" if linked else "TEXT_DIM")
            self.link.setToolTip(
                "Every output channel plays through the same device. Click to give "
                "each its own." if linked else
                f"{self.channel.label} has its own device. Click to play every output "
                f"channel through this one's.")

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
                           "DANGER" if muted else "TEXT_MUTED")
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
            hint = label(empty, "Dim", wrap=True)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setMinimumHeight(36)
            theme.style(hint, lambda: f"color: {theme.TEXT_DIM}; border: 1px dashed "
                                      f"{theme.SEAM}; border-radius: 8px;")
            self.apps.addWidget(hint)

    def _paint_frame(self, highlight: bool) -> None:
        theme.style(self, lambda: f"#Strip {{ background: {theme.SECTION_BG}; border-radius: "
                                  f"14px; border: 2px solid "
                                  f"{self.colour if highlight else 'transparent'}; }}")

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
        if hint:
            layout.addWidget(label(hint, "Dim", wrap=True))
        # A combo box is as wide as its longest device name unless told
        # otherwise, and some are very long.
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(10)
        layout.addWidget(combo)

    def set_colour(self, icon_name: str, colour: str) -> None:
        """`colour`: a token of the scheme in use ("MIC") or a colour of its own."""
        self.colour = colour
        theme.themed(self.badge, lambda: self.badge.setPixmap(
            icons.pixmap(icon_name, colour, 16)), "icon")
        theme.style(self.badge, lambda: f"background: {theme.shade(theme.colour(colour), 0.25)}; "
                                        f"border-radius: 8px;")


class ColumnGrid(QWidget):
    """Columns side by side, or half as many per row when the page is too
    narrow for all of them in one: the channels go two by two, the device
    manager's panels one under the other. Each is as tall as what it holds."""

    def __init__(self, columns: list[QWidget], spacing: int = 12, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.spacing = spacing
        self._per_row = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        # Its width comes from the page, never the other way round: a row of
        # columns too wide for the window would otherwise scroll sideways.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._arrange(len(columns))

    def _arrange(self, per_row: int) -> None:
        if per_row == self._per_row:
            return
        self._per_row = per_row
        for column in self.columns:
            self.grid.removeWidget(column)
        for index, column in enumerate(self.columns):
            self.grid.addWidget(column, index // per_row, index % per_row,
                                Qt.AlignmentFlag.AlignTop)
        for index in range(len(self.columns)):
            self.grid.setColumnStretch(index, 1 if index < per_row else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        need = sum(column.minimumSizeHint().width() for column in self.columns) + \
            self.spacing * (len(self.columns) - 1)
        self._arrange(len(self.columns) if self.width() >= need else
                      (len(self.columns) + 1) // 2)


class SonarView(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.controller = context.sonar
        self._names: dict[str, str] = {}
        self._outputs: list = []
        self._inputs: list = []
        self._popup: DeviceList | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = scroll = QScrollArea()
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
        # The channel apps play on until they are dragged to another one.
        header.addWidget(label("New apps go to", "Muted"))
        self.default_channel = QComboBox()
        self.default_channel.setToolTip("Apps play on this channel until you drag them to "
                                        "another one.")
        for output in channels.OUTPUTS:
            self.default_channel.addItem(output.label, output.id)
        theme.themed(self.default_channel, self._paint_default_channel, "icon")
        self.default_channel.setCurrentIndex(
            max(0, self.default_channel.findData(context.config.sonar.default_channel)))
        self.default_channel.setMinimumWidth(120)
        self.default_channel.activated.connect(self._on_default_channel)
        header.addWidget(self.default_channel)
        header.addSpacing(10)
        header.addWidget(label("Enabled", "Muted"))
        self.toggle = Toggle(context.config.sonar.enabled)
        self.toggle.toggled.connect(self.controller.set_enabled)
        header.addWidget(self.toggle)
        layout.addLayout(header)

        self.strips: dict[str, ChannelColumn] = {}
        for channel in channels.ALL:
            self.strips[channel.id] = ChannelColumn(self, self.controller, channel)
        self.strips_host = ColumnGrid(list(self.strips.values()))
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

        self.manager = Section("Device manager", "Which devices Vertex plays through and "
                                                 "records from. Drag them to reorder, or "
                                                 "into Excluded to keep Vertex from picking "
                                                 "them by itself.")
        self.show_disconnected = Toggle(context.config.sonar.show_disconnected)
        self.show_disconnected.toggled.connect(self._on_show_disconnected)
        self.manager.add_row("Show disconnected devices", self.show_disconnected,
                             "Ones Vertex has seen before, so they can be placed in the "
                             "list before they are plugged in.")
        self.output_panel = DevicePanel(self, "output", "Output devices", "headphones",
                                        "ACCENT_EDGE")
        self.mic_panel = DevicePanel(self, "mic", "Microphones",
                                     icons.channel_icon_name("mic"), "MIC")
        self.panels_host = ColumnGrid([self.output_panel, self.mic_panel], spacing=16)
        self.manager.body.addWidget(self.panels_host)
        layout.addWidget(self.manager)
        # What each panel's lists held when last filled: the full lists and
        # the names shown, so a drag can be laid back onto the full lists.
        self._lists: dict[str, tuple[list[str], list[str], set[str]]] = {}

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
        elif enabled and status.active and not self.context.config.sonar.linked:
            self.subtitle.setText("Running — each channel plays through its own device.")
        elif enabled and status.active:
            output = self._names.get(status.output, status.output)
            where = f" through {output}" if output else ""
            second = self.context.config.sonar.second_output
            also = [entry.channel.label for entry in status.channels.values() if entry.also]
            outputs = [entry for entry in status.channels.values() if entry.channel.is_output]
            if second and also:
                where += (f", and also {self._label(second)}" if len(also) == len(outputs)
                          else f", and {fmt.oxford(also)} also through {self._label(second)}")
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
        self._show_channel_devices(status)

    # --- Devices ---------------------------------------------------------------

    def _show_channel_devices(self, status: SonarStatus) -> None:
        """Each channel's device: what it plays through while Sonar runs, else
        what it is set to."""
        sonar = self.context.config.sonar
        for channel in channels.ALL:
            entry = status.channels.get(channel.id)
            if channel.is_output:
                configured = sonar.output_device if sonar.linked else \
                    sonar.channel(channel.id).output_device or sonar.output_device
                current = (entry.output if entry and entry.output else "") or configured
            else:
                current = status.mic or sonar.mic_device
            text = self._names.get(current, current) or "System default"
            self.strips[channel.id].show_device(current, text, sonar.linked)
            second = sonar.second_output
            self.strips[channel.id].show_also(self._label(second) if second else "",
                                              sonar.channel(channel.id).also_second,
                                              bool(second))
        self._show_manager(status)

    def _ordered(self, kind: str) -> tuple[list[str], list[str]]:
        """The device manager's lists for `kind`, with connected devices it
        hasn't learned yet at the bottom (they join it on the next refresh)."""
        sonar = self.context.config.sonar
        connected = self._outputs if kind == "output" else self._inputs
        priority = list(getattr(sonar, f"{kind}_priority"))
        excluded = list(getattr(sonar, f"{kind}_excluded"))
        priority += [d.name for d in connected if d.name not in priority and d.name not in excluded]
        return priority, excluded

    def _label(self, name: str) -> str:
        return self._names.get(name) or self.context.config.sonar.device_names.get(name, name)

    def _show_manager(self, status: SonarStatus) -> None:
        sonar = self.context.config.sonar
        for panel, kind, connected, current in (
                (self.output_panel, "output", self._outputs, status.output),
                (self.mic_panel, "mic", self._inputs, status.mic)):
            present = {device.name: device for device in connected}
            priority, excluded = self._ordered(kind)

            def rows(names, present=present, current=current):
                return [(name, self._label(name), name in present, name == current)
                        for name in names if name in present or sonar.show_disconnected]

            shown_priority, shown_excluded = rows(priority), rows(excluded)
            self._lists[kind] = (priority, excluded,
                                 {row[0] for row in (*shown_priority, *shown_excluded)})
            now = present.get(current)
            text = self._label(current) if now is not None else (
                "Sonar is off" if not sonar.enabled else "No device in use")
            panel.show_devices(shown_priority, shown_excluded, getattr(sonar, f"{kind}_auto"),
                               now, text)
        # The second device is one of the priority list's: connected, not
        # excluded, and not the one already in use.
        second = sonar.second_output
        present = {device.name for device in self._outputs}
        priority, _excluded = self._ordered("output")
        choices = [(name, self._label(name)) for name in priority
                   if name in present and name != status.output]
        self.output_panel.show_second(choices, second,
                                      next((d for d in self._outputs if d.name == second), None),
                                      self._label(second) if second else "",
                                      connected=second in present)

    def device_order_changed(self, kind: str, priority: list[str], excluded: list[str]) -> None:
        """A drag in the device manager: lay the shown order back onto the full
        lists, which may hold disconnected devices that aren't shown."""
        full_priority, full_excluded, shown = self._lists.get(kind, ([], [], set()))
        self.controller.set_device_order(
            kind, devices.reorder(full_priority, shown, priority),
            devices.reorder(full_excluded, shown, excluded))

    def _on_show_disconnected(self, shown: bool) -> None:
        self.controller.set_show_disconnected(shown)
        self._show_manager(self.controller.status)

    def show_manager(self) -> None:
        self.scroll.verticalScrollBar().setValue(self.manager.y())

    def choose_device(self, channel_id: str) -> DeviceList:
        channel = channels.BY_ID[channel_id]
        column = self.strips[channel_id]
        kind = "output" if channel.is_output else "mic"
        present = {d.name for d in (self._outputs if channel.is_output else self._inputs)}
        priority, excluded = self._ordered(kind)
        self._popup = DeviceList(
            "OUTPUT DEVICES" if channel.is_output else "INPUT DEVICES",
            [(name, self._label(name)) for name in priority if name in present],
            column.current_device, self,
            excluded=[(name, self._label(name)) for name in excluded if name in present])
        self._popup.picked.connect(lambda name: self._pick_device(channel_id, name))
        self._popup.manage.connect(self.show_manager)
        self._popup.show_under(column.device)
        return self._popup

    def _pick_device(self, channel_id: str, name: str) -> None:
        if channel_id == channels.MIC.id:
            self.controller.set_mic(name)
        else:
            self.controller.set_channel_output(channel_id, name)

    def toggle_link(self, channel_id: str) -> None:
        self.controller.set_linked(not self.context.config.sonar.linked, channel_id)

    def _paint_default_channel(self) -> None:
        for index in range(self.default_channel.count()):
            channel = self.default_channel.itemData(index)
            self.default_channel.setItemIcon(index, icons.icon(
                icons.channel_icon_name(channel), theme.channel_colour(channel), 16))

    def _on_default_channel(self, _index: int) -> None:
        self.controller.set_default_channel(self.default_channel.currentData())

    def _show_devices(self, outputs, inputs) -> None:
        self._outputs, self._inputs = list(outputs), list(inputs)
        self._names = {device.name: device.label for device in [*outputs, *inputs]}
        self._show_status(self.controller.status)

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
