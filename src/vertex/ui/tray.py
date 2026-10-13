"""The tray icon: Vertex keeps routing audio and buffering replays while the
window is closed, and this is how you reach it."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from vertex import APP_NAME, notifications
from vertex.recorder.replay import RecorderError
from vertex.ui import icons


class Tray(QSystemTrayIcon):
    def __init__(self, window, context):
        super().__init__(icons.app_icon(context.config.logo_variant), window)
        self.window = window
        self.context = context
        self.setToolTip(APP_NAME)
        menu = QMenu()
        self.show_action = self._add(menu, f"Show {APP_NAME}", window.bring_to_front)
        menu.addSeparator()
        self.replay_action = self._add(menu, "Start replay buffer", context.recorder.toggle)
        self.save_action = self._add(menu, "Save clip", lambda: self._save(None))
        self.save_30_action = self._add(menu, "Save the last 30 seconds", lambda: self._save(30))
        menu.addSeparator()
        self.sonar_action = self._add(menu, "Sonar", lambda: context.sonar.set_enabled(
            not context.config.sonar.enabled))
        self.sonar_action.setCheckable(True)
        menu.addSeparator()
        self._add(menu, "Quit", window.quit)
        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._activated)
        self.messageClicked.connect(window.bring_to_front)
        context.recorder.state_changed.connect(self._recorder_state)
        context.sonar.status_changed.connect(lambda _s: self._sonar_state())
        context.config_changed.connect(self._sonar_state)
        self._recorder_state("stopped", "")
        self._sonar_state()

    @staticmethod
    def _add(menu: QMenu, text: str, handler) -> QAction:
        action = QAction(text, menu)
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

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
        running = state == "running"
        self.replay_action.setText("Stop replay buffer"
                                   if running or state in ("starting", "restarting")
                                   else "Start replay buffer")
        self.save_action.setEnabled(running)
        self.save_30_action.setEnabled(running)
        tip = {"running": "replay buffer on", "starting": "starting the replay buffer",
               "restarting": "restarting the replay buffer",
               "failed": "replay buffer stopped"}.get(state, "replay buffer off")
        self.setToolTip(f"{APP_NAME} — {tip}")

    def _sonar_state(self) -> None:
        self.sonar_action.setChecked(self.context.config.sonar.enabled)

    def pop_up(self, notice: notifications.Notice) -> None:
        """Show a notice on the desktop."""
        level = notifications.BY_ID[notice.kind].level
        title = notice.title or APP_NAME
        if level in ("warn", "error"):
            self.showMessage(title, notice.body, QSystemTrayIcon.MessageIcon.Warning,
                             8000 if level == "error" else 6000)
        else:
            self.showMessage(title, notice.body,
                             icons.app_icon(self.context.config.logo_variant), 4000)
