"""The tray icon: Vertex keeps buffering replays (and routing audio, with
Sonar) while the window is closed, and this is how you reach it."""

from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from vertex import APP_NAME, notifications
from vertex.audio import channels, devices
from vertex.recorder.replay import RecorderError
from vertex.ui import icons


class Tray(QSystemTrayIcon):
    def __init__(self, window, context):
        super().__init__(icons.app_icon(icons.desktop_ink()), window)
        self.window = window
        self.context = context
        self.setToolTip(APP_NAME)
        menu = QMenu()
        self.show_action = self._add(menu, f"Show {APP_NAME}", window.bring_to_front)
        self._add(menu, "Open Library", lambda: self._open("library"))
        if context.sonar is not None:
            self._add(menu, "Open Sonar", lambda: self._open("sonar"))
        self.recording_actions = [menu.addSeparator()]
        self.replay_action = self._add(menu, "Start replay buffer", context.recorder.toggle)
        self.save_action = self._add(menu, "Save clip", lambda: self._save(None))
        self.save_30_action = self._add(menu, "Save the last 30 seconds", lambda: self._save(30))
        self.recording_actions += [self.replay_action, self.save_action, self.save_30_action]
        menu.addSeparator()
        self._shown_devices = None
        if context.sonar is not None:
            self.sonar_action = self._add(menu, "Sonar", lambda: context.sonar.set_enabled(
                not context.config.sonar.enabled))
            self.sonar_action.setCheckable(True)
            # Switching devices for now, as on the Sonar page: the lists keep their order.
            self.output_menu = menu.addMenu("Output device")
            self.mic_menu = menu.addMenu("Microphone")
            menu.addSeparator()
        self._add(menu, "Quit", window.quit)
        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._activated)
        self.messageClicked.connect(window.bring_to_front)
        context.recorder.state_changed.connect(self._recorder_state)
        context.config_changed.connect(
            lambda: self._recorder_state(context.recorder.phase, ""))
        self._recorder_state("stopped", "")
        if context.sonar is not None:
            context.sonar.status_changed.connect(lambda _s: self._sonar_state())
            context.sonar.devices_changed.connect(lambda _o, _i: self._sonar_state())
            context.config_changed.connect(self._sonar_state)
            self._sonar_state()

    @staticmethod
    def _add(menu: QMenu, text: str, handler) -> QAction:
        action = QAction(text, menu)
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

    def _open(self, page: str) -> None:
        self.window.bring_to_front()
        self.window.navigate(page)

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.window.isVisible() and not self.window.isMinimized():
                self.window.hide()
            else:
                self.window.bring_to_front()

    def _save(self, seconds) -> None:
        try:
            self.context.recorder.save(seconds)
        except RecorderError:
            pass         # the recorder has told the user

    def _recorder_state(self, state: str, error: str) -> None:
        for action in self.recording_actions:
            action.setVisible(self.context.recorder.enabled)
        running = state == "running"
        self.replay_action.setText("Stop replay buffer"
                                   if running or state in ("starting", "restarting")
                                   else "Start replay buffer")
        self.save_action.setEnabled(running)
        self.save_30_action.setEnabled(running)
        tip = {"running": "replay buffer on", "starting": "starting the replay buffer",
               "restarting": "restarting the replay buffer",
               "failed": "replay buffer stopped"}.get(state, "replay buffer off")
        if not self.context.recorder.enabled:
            tip = "recording off"
        self.setToolTip(f"{APP_NAME} — {tip}")

    def _sonar_state(self) -> None:
        self.sonar_action.setChecked(self.context.config.sonar.enabled)
        self._fill_devices()

    def device_lists(self) -> tuple[list[tuple[str, str, bool]], list[tuple[str, str, bool]]]:
        """The outputs and the mics the submenus offer, as (name, label, in use),
        in the device manager's order, without excluded devices."""
        controller, sonar = self.context.sonar, self.context.config.sonar
        status = controller.status

        def entries(found, priority, excluded, current):
            labels = {device.name: device.description or device.name for device in found}
            names = devices.pickable(priority, excluded, [device.name for device in found])
            return [(name, labels[name], name == current) for name in names]

        return (entries(controller.outputs, sonar.output_priority, sonar.output_excluded,
                        status.output),
                entries(controller.inputs, sonar.mic_priority, sonar.mic_excluded, status.mic))

    def _fill_devices(self) -> None:
        on = self.context.config.sonar.enabled and self.context.sonar.status.active
        lists = self.device_lists() if on else ([], [])
        if (on, lists) == self._shown_devices:
            return
        self._shown_devices = (on, lists)
        for submenu, entries, channel_id in ((self.output_menu, lists[0], ""),
                                             (self.mic_menu, lists[1], channels.MIC.id)):
            submenu.clear()
            for old in submenu.findChildren(QActionGroup):
                old.deleteLater()
            submenu.menuAction().setEnabled(on)
            group = QActionGroup(submenu)
            for name, text, in_use in entries:
                action = self._add(submenu, text, lambda _c=False, n=name, c=channel_id:
                                   self.context.sonar.pick_device(n, c))
                action.setCheckable(True)
                action.setChecked(in_use)
                group.addAction(action)
            if on and not entries:
                self._add(submenu, "Nothing connected", lambda: None).setEnabled(False)

    def pop_up(self, notice: notifications.Notice) -> None:
        """Show a notice on the desktop."""
        level = notifications.BY_ID[notice.kind].level
        title = notice.title or APP_NAME
        if level in ("warn", "error"):
            self.showMessage(title, notice.body, QSystemTrayIcon.MessageIcon.Warning,
                             8000 if level == "error" else 6000)
        else:
            self.showMessage(title, notice.body, icons.app_icon(icons.desktop_ink()), 4000)
