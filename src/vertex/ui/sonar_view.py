"""The Sonar page: channel strips, devices, and which app plays where."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vertex import paths
from vertex.audio import channels
from vertex.audio.sonar import AppStream, SonarStatus
from vertex.recorder import gsr
from vertex.ui import icons, theme
from vertex.ui.widgets import IconButton, Section, Toggle, label


class ChannelStrip(QFrame):
    """One channel: icon, name, a vertical fader, mute, and "in clips"."""

    def __init__(self, controller, channel: channels.Channel, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.channel = channel
        colour = theme.channel_colour(channel.id)
        self.setObjectName("Strip")
        self.setStyleSheet(f"#Strip {{ background: {theme.SECTION_BG}; border-radius: 14px; }}")
        self.setMinimumWidth(128)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        badge = QLabel()
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icons.pixmap(icons.channel_icon_name(channel.id), colour, 22))
        badge.setStyleSheet(f"background: {theme.shade(colour, 0.25)}; border-radius: 12px;")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        name = label(channel.label)
        name.setStyleSheet("font-weight: 600;")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)
        device = label(channel.description, "Dim")
        device.setAlignment(Qt.AlignmentFlag.AlignCenter)
        device.setToolTip(f"{channel.blurb}\nDevice: {channel.node}")
        layout.addWidget(device)

        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setMinimumHeight(150)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.setStyleSheet(
            f"QSlider::add-page:vertical {{ background: {colour}; border-radius: 2px; }}")
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider, 1, Qt.AlignmentFlag.AlignHCenter)
        self.readout = label("100%", "Muted")
        self.readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.readout)

        self.mute = IconButton("volume", "Mute", 18, theme.TEXT_MUTED, kind="")
        self.mute.setCheckable(True)
        self.mute.toggled.connect(self._on_mute)
        layout.addWidget(self.mute, 0, Qt.AlignmentFlag.AlignHCenter)

        self.record = QCheckBox("In clips")
        self.record.setToolTip("Record this channel as its own track in every clip")
        self.record.toggled.connect(lambda on: controller.set_record(channel.id, on))
        layout.addWidget(self.record, 0, Qt.AlignmentFlag.AlignHCenter)

        settings = controller.context.config.sonar.channel(channel.id)
        self._quiet = True
        self.slider.setValue(round(settings.volume * 100))
        self.mute.setChecked(settings.muted)
        self.record.setChecked(settings.record)
        self._quiet = False
        self._paint_mute()

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


class AppRow(QWidget):
    def __init__(self, controller, key: str, name: str, channel: str | None,
                 rule: str | None, playing: bool, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        avatar = QLabel(name[:1].upper() or "?")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(f"background: {theme.game_colour(key)}; border-radius: 9px; "
                             f"color: white; font-weight: 700;")
        layout.addWidget(avatar)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(label(name))
        state = "Playing" if playing else "Not playing — the rule applies when it starts"
        text.addWidget(label(f"{state} · {key}", "Dim"))
        layout.addLayout(text, 1)
        self.combo = QComboBox()
        self.combo.addItem("Default channel", None)
        for output in channels.OUTPUTS:
            self.combo.addItem(icons.icon(icons.channel_icon_name(output.id),
                                          theme.channel_colour(output.id), 16),
                               output.label, output.id)
        self.combo.setCurrentIndex(max(0, self.combo.findData(rule)))
        self.combo.setMinimumWidth(170)
        self.combo.currentIndexChanged.connect(
            lambda _i: controller.route(key, self.combo.currentData()))
        layout.addWidget(self.combo)
        if not playing:
            forget = IconButton("close", "Forget this rule", 14, theme.TEXT_MUTED)
            forget.clicked.connect(lambda: controller.forget_rule(key))
            layout.addWidget(forget)
        elif channel and channel != (rule or controller.context.config.sonar.default_channel):
            layout.addWidget(label(f"on {channels.BY_ID[channel].label}", "Dim"))


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
        self.strips = {}
        for channel in channels.ALL:
            strip = ChannelStrip(self.controller, channel)
            strips.addWidget(strip)
            self.strips[channel.id] = strip
        layout.addWidget(self.strips_host)

        devices = Section("Devices", "Where the channels play, and which microphone feeds "
                                     "Vertex Mic. Pick “Vertex Mic” as the input in Discord "
                                     "and other chat apps.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.output = QComboBox()
        self.mic = QComboBox()
        self.default_channel = QComboBox()
        for output in channels.OUTPUTS:
            self.default_channel.addItem(output.label, output.id)
        self.default_channel.setCurrentIndex(
            max(0, self.default_channel.findData(context.config.sonar.default_channel)))
        for row, (text, widget, hint) in enumerate((
                ("Output", self.output, "Your headset or speakers"),
                ("Microphone", self.mic, "The real mic behind Vertex Mic"),
                ("Unrouted apps", self.default_channel,
                 "The channel any app without a rule plays on"))):
            grid.addWidget(label(text), row, 0)
            grid.addWidget(widget, row, 1)
            grid.addWidget(label(hint, "Dim"), row, 2)
        grid.setColumnStretch(1, 1)
        devices.body.addLayout(grid)
        layout.addWidget(devices)
        self.output.activated.connect(lambda _i: self.controller.set_output(
            self.output.currentData() or ""))
        self.mic.activated.connect(lambda _i: self.controller.set_mic(
            self.mic.currentData() or ""))
        self.default_channel.activated.connect(lambda _i: self.controller.set_default_channel(
            self.default_channel.currentData()))

        self.apps = Section("Applications", "Send each app to a channel. The choice is "
                                            "remembered and applied whenever it plays.")
        self.apps_list = QVBoxLayout()
        self.apps_list.setSpacing(4)
        self.apps.body.addLayout(self.apps_list)
        layout.addWidget(self.apps)

        self.clips = Section("In your clips", "")
        self.tracks_text = label("", "Muted", wrap=True)
        self.clips.add(self.tracks_text)
        layout.addWidget(self.clips)
        layout.addStretch(1)

        self.controller.status_changed.connect(self._show_status)
        self.controller.streams_changed.connect(self._show_streams)
        self.controller.devices_changed.connect(self._show_devices)
        context.config_changed.connect(self._show_tracks)
        context.recorder.info_changed.connect(lambda _i: self._show_tracks())
        self._show_status(self.controller.status)
        self._show_tracks()

    def showEvent(self, event):
        super().showEvent(event)
        self.controller.refresh()
        self.controller.refresh_streams()
        self.controller.refresh_devices()
        QTimer.singleShot(0, self._show_tracks)

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

    def _show_streams(self, streams: list[AppStream]) -> None:
        while self.apps_list.count():
            item = self.apps_list.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        rules = dict(self.context.config.sonar.app_rules)
        seen = set()
        for stream in streams:
            if stream.key in seen:
                continue
            seen.add(stream.key)
            self.apps_list.addWidget(AppRow(self.controller, stream.key, stream.name,
                                            stream.channel, rules.get(stream.key), True))
        for key, channel_id in sorted(rules.items()):
            if key not in seen:
                self.apps_list.addWidget(AppRow(self.controller, key, key, None, channel_id,
                                                False))
        if not seen and not rules:
            self.apps_list.addWidget(label("Nothing is playing right now. Apps show up "
                                           "here while they make sound.", "Dim", wrap=True))

    def _show_tracks(self) -> None:
        config = self.context.config
        tracks = gsr.audio_tracks(config)
        if config.sonar.enabled:
            names = " · ".join(track.title for track in tracks) or "no audio"
            text = (f"New clips get one track per channel: {names}. Untick “In clips” on a "
                    f"channel to leave it out.")
            info = self.context.recorder.info
            if info.available and not info.supports_track_names:
                text += (f" GPU Screen Recorder {info.version_text} names tracks after the "
                         f"device (“Monitor of Vertex Game”); 5.15 or newer names them by "
                         f"channel. Vertex recognises both.")
        else:
            sources = ", ".join(track.source for track in tracks) or "no audio"
            text = (f"With Sonar off, clips record: {sources} (set in Settings → Recording). "
                    f"Turn Sonar on to give every clip the same Game, Chat, Media and Mic "
                    f"tracks.")
        self.tracks_text.setText(text)
        self.clips.setToolTip(paths.tilde(config.resolved_recording_dir()))
