"""Starting the application: Qt, the control socket, the window and the tray."""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from vertex import APP_ID, APP_NAME, __version__, ipc, logs, system
from vertex.config import Config, needs_setup
from vertex.ui import icons, theme
from vertex.ui.control import Commands
from vertex.ui.main_window import MainWindow
from vertex.ui.services import Context
from vertex.ui.tray import Tray


def _create_app() -> QApplication:
    QApplication.setApplicationName(APP_ID)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    # The Wayland app id and X11 WM class both come from this, and must match
    # the desktop entry for the window to land on its own taskbar icon.
    QApplication.setDesktopFileName(APP_ID)
    system.set_app_id(f"{APP_NAME}.{APP_NAME}")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.STYLESHEET)
    app.setQuitOnLastWindowClosed(False)
    return app


def run(background: bool = False) -> int:
    app = _create_app()
    config = Config.load_or_default()
    theme.use(config.colour_scheme)
    app.setWindowIcon(icons.app_icon(icons.desktop_ink()))
    context = Context(config)
    window = MainWindow(context)

    commands = Commands(window, context)
    control = ipc.ControlServer(commands.dispatch, subscribers=commands.subscribers)
    if not control.start():
        # Lost a race with another instance starting at the same moment.
        try:
            ipc.send("show")
        except ipc.NotRunning:
            pass
        return 0
    window.add_to_start_menu()
    context.hotkeys.start()
    if logs.apply(config.keep_logs, config.resolved_log_dir()):
        logs.started()
        logs.APP.info("Logs in %s", logs.folder())
    elif config.keep_logs:
        context.notify("vertex_problem", "Couldn't write logs", config.resolved_log_dir())

    if QSystemTrayIcon.isSystemTrayAvailable():
        window.tray = Tray(window, context)
        window.tray.show()

    setup = needs_setup()
    missing = [] if setup else config.missing_dirs()
    if setup or missing:
        if missing:
            logs.APP.warning("Folders missing: %s", ", ".join(path for _key, path in missing))
        logs.APP.info("Showing first-run setup")
        window.show_setup(config if missing else None, missing)
    else:
        window.start_services()
        window.navigate("home")

    if setup or missing or not background or window.tray is None:
        window.show()

    # Ctrl+C in the terminal, and SIGTERM from a session ending, quit cleanly:
    # the recorder is stopped.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_args: window.quit())
    ticker = QTimer()
    ticker.timeout.connect(lambda: None)    # lets Python run its signal handlers
    ticker.start(300)

    def shutdown():
        logs.APP.info("Quitting")
        control.stop()
        context.shutdown()

    app.aboutToQuit.connect(shutdown)
    code = app.exec()
    logs.APP.info("Stopped")
    logs.shutdown()
    return code
