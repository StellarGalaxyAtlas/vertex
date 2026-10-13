"""Starting the application: Qt, the control socket, the window and the tray."""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from vertex import APP_ID, APP_NAME, __version__, ipc
from vertex.config import Config, needs_setup
from vertex.recorder.replay import RecorderError
from vertex.ui import icons, theme
from vertex.ui.main_window import MainWindow
from vertex.ui.services import Context
from vertex.ui.tray import Tray


class Commands(QObject):
    """Runs control-socket commands on the UI thread and returns their reply.

    The socket server calls `dispatch` from its own threads; the blocking
    queued connection runs the handler on the UI thread and waits for it.
    """

    # `object`, not dict/list: Qt copies those across threads, and the reply
    # has to land in the very list the socket thread is waiting on.
    request = Signal(str, object, object)

    def __init__(self, window: MainWindow, context: Context):
        super().__init__()
        self.window = window
        self.context = context
        self.request.connect(self._handle, Qt.ConnectionType.BlockingQueuedConnection)

    def dispatch(self, command: str, args: dict) -> dict:
        box: list = []
        self.request.emit(command, args, box)
        return box[0] if box else {"ok": False, "message": "No reply."}

    def _handle(self, command: str, args: dict, box: list) -> None:
        try:
            box.append(self._run(command, args))
        except Exception as exc:     # reported to the caller
            box.append({"ok": False, "message": str(exc)})

    def _run(self, command: str, args: dict) -> dict:
        recorder, sonar = self.context.recorder, self.context.sonar
        if command == "show":
            self.window.bring_to_front()
            return {"ok": True, "message": ""}
        if command == "save-clip":
            seconds = args.get("seconds")
            try:
                return {"ok": True, "message": recorder.save(int(seconds) if seconds else None)}
            except RecorderError as exc:
                return {"ok": False, "message": str(exc)}
        if command == "replay":
            action = args.get("action")
            if action == "status":
                return {"ok": True, "message": f"The replay buffer is {recorder.state.value}."}
            if action == "start" or (action == "toggle" and not recorder.running):
                recorder.start()
                return {"ok": True, "message": "Starting the replay buffer."}
            recorder.stop()
            return {"ok": True, "message": "Stopping the replay buffer."}
        if command == "sonar":
            action = args.get("action")
            if action == "status":
                status = sonar.status
                return {"ok": True, "message": f"Sonar is {'up' if status.active else 'down'}."}
            sonar.set_enabled(action == "up")
            return {"ok": True, "message": f"Sonar is going {'up' if action == 'up' else 'down'}."}
        return {"ok": False, "message": f"Unknown command: {command}"}


def _create_app() -> QApplication:
    QApplication.setApplicationName(APP_ID)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    # The Wayland app id and X11 WM class both come from this, and must match
    # the desktop entry for the window to land on its own taskbar icon.
    QApplication.setDesktopFileName(APP_ID)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.STYLESHEET)
    app.setQuitOnLastWindowClosed(False)
    return app


def run(background: bool = False) -> int:
    app = _create_app()
    config = Config.load_or_default()
    app.setWindowIcon(icons.app_icon(config.logo_variant))
    context = Context(config)
    window = MainWindow(context)

    commands = Commands(window, context)
    control = ipc.ControlServer(commands.dispatch)
    if not control.start():
        # Lost a race with another instance starting at the same moment.
        try:
            ipc.send("show")
        except ipc.NotRunning:
            pass
        return 0

    if QSystemTrayIcon.isSystemTrayAvailable():
        window.tray = Tray(window, context)
        window.tray.show()

    setup = needs_setup()
    missing = [] if setup else config.missing_dirs()
    if setup or missing:
        window.show_setup(config if missing else None, missing)
    else:
        window.start_services()
        window.navigate("library")

    if setup or missing or not background or window.tray is None:
        window.show()

    # Ctrl+C in the terminal, and SIGTERM from a session ending, quit cleanly:
    # the recorder is stopped and Sonar gives the system its defaults back.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_args: window.quit())
    ticker = QTimer()
    ticker.timeout.connect(lambda: None)    # lets Python run its signal handlers
    ticker.start(300)

    def shutdown():
        control.stop()
        context.shutdown()

    app.aboutToQuit.connect(shutdown)
    return app.exec()
