"""The main window: the rail beside whichever page is showing."""

from __future__ import annotations

import copy
import os

from PySide6.QtCore import QFileSystemWatcher, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from vertex import APP_NAME, desktop, notifications
from vertex.audio import channels
from vertex.config import Config
from vertex.ui import icons, theme, workers
from vertex.ui.editor.view import EditorView
from vertex.ui.first_run import FirstRunView
from vertex.ui.library.state import LibraryState
from vertex.ui.library.view import LibraryView
from vertex.ui.rail import Rail
from vertex.ui.settings.view import SettingsView
from vertex.ui.sonar_view import SonarView
from vertex.ui.widgets import Banner, ChoiceDialog


class MainWindow(QMainWindow):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.tray = None
        self._quitting = False
        self._told_about_tray = False
        self._services_started = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon(context.config.logo_variant))
        self.resize(1280, 820)
        self.setMinimumSize(980, 640)

        self.state = LibraryState(context, self)
        central = QWidget()
        central.setObjectName("Page")
        self.setCentralWidget(central)
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.rail = Rail(context, self.state)
        self.rail.navigate.connect(self.navigate)
        row.addWidget(self.rail)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        row.addLayout(column, 1)
        self.stack = QStackedWidget()
        column.addWidget(self.stack, 1)
        self.banner = Banner()
        self.banner.setContentsMargins(theme.CONTENT_MARGIN, 0, theme.CONTENT_MARGIN, 8)
        column.addWidget(self.banner)

        self.library_view = LibraryView(context, self.state)
        self.library_view.open_clip.connect(self.open_clip)
        self.library_view.import_requested.connect(self._open_import)
        self.sonar_view = SonarView(context)
        self.settings_view = SettingsView(context)
        self.settings_view.saved.connect(self._settings_saved)
        self.settings_view.imported.connect(self.state.reload)
        self.settings_view.setup_requested.connect(self.run_setup_again)
        for page in (self.library_view, self.sonar_view, self.settings_view):
            self.stack.addWidget(page)
        self.editor: EditorView | None = None
        self.first_run: FirstRunView | None = None

        context.message.connect(self.banner.show_message)
        context.notified.connect(self._notified)
        self.state.status.connect(self.banner.show_message)
        context.recorder.saved.connect(self._clip_saved)
        context.library_reset.connect(self._watch_folder)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self._rescan_timer.start())
        self._rescan_timer = QTimer(self, singleShot=True, interval=1200)
        self._rescan_timer.timeout.connect(self._rescan)

        for keys, handler in (("Ctrl+F", self._focus_search), ("F5", self.state.reload),
                              ("Ctrl+Q", self.quit), ("Ctrl+,", lambda: self.navigate("settings")),
                              ("Ctrl+1", lambda: self.navigate("library")),
                              ("Ctrl+2", lambda: self.navigate("sonar"))):
            QShortcut(QKeySequence(keys), self, handler)

    # --- Pages ---------------------------------------------------------------

    def navigate(self, page: str) -> None:
        if self.first_run is not None:
            return
        if self._on_settings() and page != "settings" and not self._may_leave_settings():
            self.rail.set_page("settings")
            return
        self._close_editor()
        self.rail.show()
        target = {"library": self.library_view, "sonar": self.sonar_view,
                  "settings": self.settings_view}[page]
        if page == "settings":
            self.settings_view.load()
        self.stack.setCurrentWidget(target)
        self.rail.set_page(page)
        if page == "library":
            self.library_view.grid.setFocus()

    def _on_settings(self) -> bool:
        return self.stack.currentWidget() is self.settings_view and \
            self.settings_view.isVisible()

    def _remove_page(self, page) -> None:
        """Take a transient page out of the stack without the stack flipping to
        whatever page happens to sit next to it — Settings, say, which would
        then ask about unsaved changes nobody made."""
        if self.stack.currentWidget() is page:
            self.stack.setCurrentWidget(self.library_view)
        self.stack.removeWidget(page)
        page.deleteLater()

    def _may_leave_settings(self) -> bool:
        if not self.settings_view.is_dirty():
            return True
        answer = ChoiceDialog.ask(self, "Unsaved settings", "Save your changes to Settings?",
                                  choices=[("Discard", "discard", ""),
                                           ("Save", "save", "primary")])
        if answer == "save":
            return self.settings_view.save()
        if answer == "discard":
            self.settings_view.load()
            return True
        return False

    def show_setup(self, config: Config | None = None, missing=(), again: bool = False) -> None:
        self._close_editor()
        self.rail.hide()
        self.first_run = FirstRunView(self.context, config, missing, again=again)
        self.first_run.finished.connect(self._setup_done)
        self.first_run.cancelled.connect(self._setup_cancelled)
        self.stack.addWidget(self.first_run)
        self.stack.setCurrentWidget(self.first_run)

    def run_setup_again(self) -> None:
        """First-run setup on a running Vertex, from Settings, after a warning."""
        if self._on_settings() and not self._may_leave_settings():
            return
        answer = ChoiceDialog.ask(
            self, "Run setup again", "Run first-run setup again?",
            "Setup opens with your current settings filled in. When you finish it, what "
            "you chose there replaces them: the clips and exports folders, whether Sonar "
            "is on and its devices, and the replay buffer's duration and whether it starts "
            "with Vertex.\n\nCancel at any step to keep everything as it is. Nothing is "
            "deleted: your clips, tags and edits stay.",
            [("Run setup", "run", "primary")])
        if answer == "run":
            self.show_setup(copy.deepcopy(self.context.config), again=True)

    def _setup_cancelled(self) -> None:
        page, self.first_run = self.first_run, None
        self._remove_page(page)
        self.navigate("settings")
        self.settings_view.show_page("import")

    def _setup_done(self, config: Config, enable_sonar: bool, start_recorder: bool) -> None:
        context = self.context
        before = copy.deepcopy(context.config)
        for key in ("clip_path", "export_path", "data_path", "state_path", "cache_path"):
            setattr(context.config, key, getattr(config, key))
        context.config.recorder = config.recorder
        if not self._services_started:
            context.config.sonar.output_device = config.sonar.output_device
            context.config.sonar.mic_device = config.sonar.mic_device
        failed = context.config.ensure_dirs()
        context.save_config()
        if failed:
            context.notify("vertex_problem", "Could not create a folder", failed[0])
        page, self.first_run = self.first_run, None
        self._remove_page(page)
        self.settings_view.load()
        if self._services_started:
            self._apply_setup_again(before, config, enable_sonar)
        else:
            self.start_services(enable_sonar=enable_sonar, start_recorder=start_recorder)
        self.navigate("library")

    def _apply_setup_again(self, before: Config, config: Config, enable_sonar: bool) -> None:
        """Setup ran again on a running Vertex: change what it changed, the way
        Settings and the Sonar page do, rather than starting anything twice."""
        context = self.context
        self._settings_saved(any(getattr(before, key) != getattr(context.config, key)
                                 for key in ("clip_path", "data_path", "cache_path",
                                             "state_path")))
        if enable_sonar != before.sonar.enabled:
            context.config.sonar.output_device = config.sonar.output_device
            context.config.sonar.mic_device = config.sonar.mic_device
            context.sonar.set_enabled(enable_sonar)
        elif enable_sonar:
            status = context.sonar.status
            output, mic = config.sonar.output_device, config.sonar.mic_device
            if output and output != status.output:
                # Linked, one channel's device is every channel's.
                for channel in (channels.OUTPUTS[:1] if context.config.sonar.linked
                                else channels.OUTPUTS):
                    context.sonar.set_channel_output(channel.id, output)
            if mic and mic != status.mic:
                context.sonar.set_mic(mic)
        if context.config.recorder != before.recorder:
            context.recorder.detect()
            context.recorder.restart_if_running()

    def start_services(self, enable_sonar: bool | None = None,
                       start_recorder: bool | None = None) -> None:
        self._services_started = True
        context = self.context
        context.open_library()
        self.state.reload()
        if context.thumbs is not None:
            QTimer.singleShot(5000, lambda: context.thumbs.prune(
                [clip.path for clip in self.state.all_clips]))
        context.sonar.start()
        if enable_sonar:
            context.sonar.set_enabled(True)
        context.recorder.detect()
        if start_recorder if start_recorder is not None else context.config.recorder.autostart:
            context.recorder.start()
        # Into the start menu on the first run; never again once removed.
        variant = context.config.logo_variant
        self.start_menu_job = workers.run(lambda: desktop.ensure(variant), None,
                                          lambda _exc: None)

    def _settings_saved(self, folders_changed: bool) -> None:
        self.setWindowIcon(icons.app_icon(self.context.config.logo_variant))
        self.rail.set_logo(self.context.config.logo_variant)
        if self.tray is not None:
            self.tray.setIcon(icons.app_icon(self.context.config.logo_variant))
        if folders_changed:
            self.context.open_library()
            self.state.reload()

    def _open_import(self) -> None:
        self.navigate("settings")
        self.settings_view.show_page("import")

    def _focus_search(self) -> None:
        if self.first_run is None:
            self.navigate("library")
            self.rail.search.setFocus()
            self.rail.search.selectAll()

    # --- Editor ----------------------------------------------------------------

    def open_clip(self, clip) -> None:
        if not clip.path or not os.path.exists(clip.path):
            self.banner.show_message(f"{clip.name} is gone from the clips folder.", "warn")
            self.state.reload()
            return
        self._close_editor()
        self.editor = EditorView(self.context, self.state, clip)
        self.editor.back.connect(lambda: self.navigate("library"))
        self.editor.delete_requested.connect(self._delete_from_editor)
        self.editor.trimmed.connect(self._clip_trimmed)
        self.stack.addWidget(self.editor)
        self.stack.setCurrentWidget(self.editor)
        # The editor takes the whole window: nothing on the rail helps mid-trim.
        self.rail.hide()
        self.editor.setFocus()

    def _close_editor(self) -> None:
        editor, self.editor = self.editor, None
        if editor is None:
            return
        editor.close_editor()
        self._remove_page(editor)

    def _delete_from_editor(self, clip) -> None:
        if not self.library_view.confirm_delete(clip):
            return
        # Leave first: mpv still has the file open.
        self.navigate("library")
        self.state.delete(clip)

    def _clip_trimmed(self, clip, mode: str, path: str) -> None:
        if mode == "copy":
            self.state.reload()
            return
        self.navigate("library")            # releases the file before it is replaced
        self.state.replace_with_trim(clip, path)

    # --- Folder and recorder events ---------------------------------------------

    def _watch_folder(self) -> None:
        folders = self.watcher.directories()
        if folders:
            self.watcher.removePaths(folders)
        for folder in {self.context.config.resolved_clip_dir(),
                       self.context.config.resolved_recording_dir()}:
            if folder and os.path.isdir(folder):
                self.watcher.addPath(folder)

    def _rescan(self) -> None:
        if self.first_run is None:
            self.state.reload()

    def _clip_saved(self, path: str) -> None:
        self.state.reload()
        self.context.notify("clip_saved", "Clip saved", os.path.basename(path))

    def _notified(self, notice: notifications.Notice) -> None:
        """Every notice shows at the bottom of the window. It pops up on the
        desktop too, if its kind is switched on and the window isn't in front."""
        kind = notifications.BY_ID[notice.kind]
        self.banner.show_message(notice.line, kind.level, 12000 if kind.level == "error"
                                 else 6000)
        in_front = self.isVisible() and self.isActiveWindow() and not self.isMinimized()
        if self.tray is not None and not in_front and not self._quitting and \
                notifications.enabled(self.context.config.notifications, kind.id):
            self.tray.pop_up(notice)

    # --- Window -------------------------------------------------------------------

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        tray_ok = self.tray is not None and QSystemTrayIcon.isSystemTrayAvailable()
        if not self._quitting and self.context.config.close_to_tray and tray_ok:
            event.ignore()
            self._close_editor()
            self.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self.context.notify("in_tray", "Still running in the tray",
                                    "Quit from its menu.")
            return
        if not self._quitting:
            event.ignore()
            self.quit()
            return
        event.accept()

    def quit(self) -> None:
        if self._on_settings() and not self._may_leave_settings():
            return
        self._quitting = True
        self._close_editor()
        self.close()
        QApplication.instance().quit()

