"""The main window: the top bar over whichever page is showing."""

from __future__ import annotations

import copy
import os
import sqlite3

from PySide6.QtCore import QEvent, QFileSystemWatcher, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from vertex import (
    APP_NAME,
    backup,
    desktop,
    fmt,
    logs,
    notifications,
    paths,
    platform,
    reset,
    setting_groups,
)
from vertex.audio import channels
from vertex.config import Config
from vertex.core import clips as clips_mod
from vertex.media import export
from vertex.media.thumbnails import ThumbnailCache
from vertex.recorder import notifier
from vertex.setting_groups import LIBRARY
from vertex.ui import icons, theme, workers
from vertex.ui.editor.view import EditorView
from vertex.ui.first_run import FirstRunView, SetupResult
from vertex.ui.game_toast import GameToast
from vertex.ui.home import HomeView
from vertex.ui.library.state import LibraryState
from vertex.ui.library.view import LibraryView
from vertex.ui.settings.view import SettingsView
from vertex.ui.sonar_view import SonarView
from vertex.ui.topbar import TopBar
from vertex.ui.widgets import Banner, ChoiceDialog, GlowArea


class MainWindow(QMainWindow):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.tray = None
        # Over games: Vertex's own toast where it has one, else GSR's notifier.
        self.over_games = notifier.Notifier()
        self.game_toast: GameToast | None = None
        self._quitting = False
        self._told_about_tray = False
        self._services_started = False
        self.start_menu_job = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon(icons.desktop_ink()))
        # The icon on the desktop's panels follows its light or dark look.
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._ink_changed)
        self.resize(1280, 820)
        self.setMinimumSize(980, 640)

        self.state = LibraryState(context, self)
        central = QWidget()
        central.setObjectName("Page")
        self.setCentralWidget(central)
        rows = QVBoxLayout(central)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self.topbar = TopBar(context, self.state)
        self.topbar.navigate.connect(self.navigate)
        rows.addWidget(self.topbar)
        self.page_area = GlowArea()
        column = QVBoxLayout(self.page_area)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        rows.addWidget(self.page_area, 1)
        self.stack = QStackedWidget()
        column.addWidget(self.stack, 1)
        # Messages float over the pages as toasts.
        self.banner = Banner(self.page_area)

        self.library_view = LibraryView(context, self.state)
        self.library_view.open_clip.connect(self.open_clip)
        self.library_view.import_requested.connect(self._open_import)
        self.settings_view = SettingsView(context)
        self.settings_view.saved.connect(self._settings_saved)
        self.settings_view.imported.connect(self.state.reload)
        self.settings_view.setup_requested.connect(self.run_setup_again)
        self.settings_view.reset_requested.connect(self.reset)
        self.settings_view.restore_requested.connect(self.restore_backup)
        self.settings_view.test_requested.connect(self._test_over_games)
        # Sonar's page, where Sonar can run.
        self.sonar_view = SonarView(context) if context.sonar is not None else None
        self.home_view = HomeView(context, self.state, self.library_view)
        self.home_view.navigate.connect(self.navigate)
        self.home_view.open_clip.connect(self.open_clip)
        for page in (self.home_view, self.library_view, self.sonar_view, self.settings_view):
            if page is not None:
                self.stack.addWidget(page)
        self.editor: EditorView | None = None
        self._editor_from = "library"
        # The editor's video is an OpenGL widget, and the first one a shown
        # window gets makes Qt rebuild the window for OpenGL: it vanishes and
        # comes back. A hidden one from the start means it is built that way.
        self._gl_ready = QOpenGLWidget(central)
        self._gl_ready.hide()
        self.first_run: FirstRunView | None = None

        context.message.connect(self.banner.show_message)
        self.library_view.notice.connect(self.banner.show_message)
        context.notified.connect(self._notified)
        self.state.status.connect(self.banner.show_message)
        context.recorder.saved.connect(self._clip_saved)
        context.library_reset.connect(self._watch_folder)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self._rescan_timer.start())
        self._rescan_timer = QTimer(self, singleShot=True, interval=1200)
        self._rescan_timer.timeout.connect(self._rescan)
        # The day's automatic backup: at the start, then looked at now and
        # then, for a Vertex that stays in the tray for days.
        self._backup_timer = QTimer(self, interval=3 * 3600 * 1000)
        self._backup_timer.timeout.connect(self.back_up_daily)

        for keys, handler in (("Ctrl+F", self._focus_search), ("F5", self.state.reload),
                              ("Ctrl+Q", self.quit), ("Ctrl+,", lambda: self.navigate("settings")),
                              ("Ctrl+1", lambda: self.navigate("library"))):
            QShortcut(QKeySequence(keys), self, handler)
        if self.sonar_view is not None:
            QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.navigate("sonar"))

    # --- Pages ---------------------------------------------------------------

    def navigate(self, page: str) -> None:
        if self.first_run is not None:
            return
        if self._on_settings() and page != "settings" and not self._may_leave_settings():
            self.topbar.set_page("settings")
            return
        self._close_editor()
        self.topbar.show()
        target = {"home": self.home_view, "library": self.library_view,
                  "sonar": self.sonar_view, "settings": self.settings_view}[page]
        if page == "settings":
            self.settings_view.load()
        self.stack.setCurrentWidget(target)
        self.topbar.set_page(page)
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
        """Most settings apply as they change; recording changes wait for Apply,
        since they restart the replay buffer."""
        if not self.settings_view.apply_now():
            return False
        if not self.settings_view.pending_recording():
            return True
        answer = ChoiceDialog.ask(self, "Recording changes", "Apply the recording changes?",
                                  "Applying restarts the replay buffer if it's on.",
                                  choices=[("Discard", "discard", ""),
                                           ("Apply", "apply", "primary")])
        if answer == "apply":
            return self.settings_view.apply_recording()
        if answer == "discard":
            self.settings_view.load()
            return True
        return False

    def show_setup(self, config: Config | None = None, missing=(), again: bool = False) -> None:
        self._close_editor()
        self.topbar.hide()
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
            self, "Run setup again", "Run setup again?",
            "Setup starts with your current settings. Your clips, tags and edits stay as "
            "they are.",
            [("Run setup", "run", "primary")])
        if answer == "run":
            self.show_setup(copy.deepcopy(self.context.config), again=True)

    def _setup_cancelled(self) -> None:
        page, self.first_run = self.first_run, None
        self._remove_page(page)
        self.navigate("settings")
        self.settings_view.show_page("import")

    def _setup_done(self, result: SetupResult) -> None:
        context, config = self.context, result.config
        before = copy.deepcopy(context.config)
        for key in ("clip_path", "export_path", "data_path", "state_path", "cache_path"):
            setattr(context.config, key, getattr(config, key))
        context.config.recorder = config.recorder
        if not self._services_started:
            context.config.sonar.output_device = config.sonar.output_device
            context.config.sonar.mic_device = config.sonar.mic_device
        context.config.name_patterns = config.name_patterns
        failed = context.config.ensure_dirs()
        context.save_config()
        if failed:
            context.notify("vertex_problem", "Couldn't create a folder", failed[0])
        page, self.first_run = self.first_run, None
        self._remove_page(page)
        self.settings_view.load()
        if self._services_started:
            self._apply_setup_again(before, config, result.enable_sonar, result.start_recorder)
            if self._write_setup_tags(result.games, result.dates):
                self.state.reload()
        else:
            self.start_services(enable_sonar=result.enable_sonar,
                                start_recorder=result.start_recorder,
                                tags=(result.games, result.dates))
        self.navigate("home")

    def _write_setup_tags(self, games: dict[str, str], dates: dict[str, float]) -> bool:
        """Save the games confirmed in setup for the clips brought along."""
        library = self.context.library
        if not (games or dates) or library is None:
            return False
        try:
            library.apply_import(games, dates)
        except sqlite3.Error as exc:
            self.context.notify("vertex_problem", "Couldn't save the tags", str(exc))
            return False
        return True

    def _apply_setup_again(self, before: Config, config: Config, enable_sonar: bool,
                           start_recorder: bool) -> None:
        """Setup ran again on a running Vertex: change what it changed, the way
        Settings and the Sonar page do, rather than starting anything twice."""
        context = self.context
        self._settings_saved(any(getattr(before, key) != getattr(context.config, key)
                                 for key in ("clip_path", "data_path", "cache_path",
                                             "state_path")))
        if context.sonar is not None:
            self._apply_sonar_setup(before, config, enable_sonar)
        if context.config.recorder != before.recorder and context.recorder.enabled:
            context.recorder.detect()
            context.recorder.restart_if_running()
        if start_recorder and not before.recorder.autostart:
            context.recorder.start()      # just asked to start with Vertex: now, too

    def _apply_sonar_setup(self, before: Config, config: Config, enable_sonar: bool) -> None:
        context = self.context
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
                    context.sonar.set_channel_output(channel.id, output, lasting=True)
            if mic and mic != status.mic:
                context.sonar.set_mic(mic, lasting=True)

    # --- Reset and delete -----------------------------------------------------------

    def reset(self, what: str) -> None:
        """Settings, the library or the cache back to a fresh install's, once
        Settings › Reset and delete has had it confirmed."""
        {"settings": self.reset_settings, "library": self.reset_library,
         "cache": self.clear_cache}[what]()

    def reset_settings(self) -> None:
        """Stop the buffer and take Sonar down (giving back the system's default
        devices), put the settings file away, then first-run setup."""
        context = self.context
        self._close_editor()
        context.recorder.stop()

        def sonar_down(_value=None):
            try:
                where = reset.discard_settings()
            except OSError as exc:
                context.notify("vertex_problem", "Couldn't reset settings", str(exc))
                return
            logs.APP.info("Settings reset%s", f"; the old ones are in {where}" if where else "")
            # In place: Sonar and the recorder hold on to the settings' parts.
            reset.reset_in_place(context.config, Config())
            self.settings_view.load()
            self.show_setup()
            self.banner.show_message(f"Settings reset. {_kept(where, 'old ones are')}", "ok",
                                     10000)

        if context.sonar is not None and context.sonar.enabled:
            context.sonar.set_enabled(False, then=sonar_down)
        else:
            sonar_down()

    def reset_library(self) -> None:
        context = self.context
        self._close_editor()
        if context.library is not None:
            context.library.close()
        try:
            where = reset.discard_library(context.config.resolved_data_dir())
        except OSError as exc:
            context.notify("vertex_problem", "Couldn't reset the library", str(exc))
            where = None
        if where is not None:
            logs.CLIPS.info("Library reset%s", f"; the old one is in {where}" if where else "")
        context.open_library()
        self.state.reload()
        if where is not None:
            self.settings_view.banner.show_message(
                f"Library reset. {_kept(where, 'old one is')}", "ok", 10000)

    def restore_backup(self, path: str, picks: list[str]) -> None:
        """Put back what was picked of the backup at `path`: the recorder (and
        Sonar, if its settings come back) stop first, and the library closes."""
        context = self.context
        items = setting_groups.items()
        settings = [items[key] for key in picks if key != LIBRARY]
        sonar_back = any(name.startswith("sonar.") for item in settings for name in item.fields)
        recorder_back = any(name.startswith("recorder.") for item in settings
                            for name in item.fields)
        current = copy.deepcopy(context.config)
        was_recording = context.recorder.running
        self._close_editor()
        if recorder_back:
            context.recorder.stop()

        def restore(_value=None):
            if context.library is not None:
                context.library.close()
                context.library = None
            workers.run(lambda: backup.restore(path, current, picks), restored, failed)

        def restored(result: backup.Restored) -> None:
            logs.APP.info("Restored %s from %s", ", ".join(result.picks), path)
            # In place: Sonar and the recorder hold on to the settings' parts.
            reset.reset_in_place(context.config, result.config)
            context.save_config()            # and what follows a change: logs, names
            context.open_library()
            self.state.reload()
            self.settings_view.load()
            if sonar_back and context.sonar is not None and context.config.sonar.enabled:
                context.sonar.set_enabled(True)
            if recorder_back and (was_recording or context.config.recorder.autostart):
                context.recorder.start()
            what = fmt.oxford([part for part, back in (("settings", bool(settings)),
                                                       ("library", LIBRARY in result.picks))
                               if back])
            self.settings_view.banner.show_message(
                f"Restored your {what}. {_kept(result.moved_to, 'replaced ones are')}", "ok",
                10000)
            self._check_clips()

        def failed(exc) -> None:
            context.open_library()
            self.state.reload()
            if recorder_back and was_recording:
                context.recorder.start()
            self.settings_view.banner.show_message(f"Couldn't restore the backup: {exc}",
                                                   "error", 10000)

        if sonar_back and context.sonar is not None and context.sonar.enabled:
            context.sonar.set_enabled(False, then=restore)
        else:
            restore()

    def _check_clips(self) -> None:
        """After a restore: if most of the library's clips aren't in the clips
        folder, offer to pick the folder they are in."""
        config = copy.deepcopy(self.context.config)

        def counted(result) -> None:
            missing, known = result
            if not known or missing * 2 <= known:
                return
            folder = paths.tilde(config.resolved_clip_dir())
            answer = ChoiceDialog.ask(
                self, "Clips not found",
                f"{missing:,} of the library's {fmt.plural(known, 'clip')} aren't in {folder}",
                "Pick the folder they're in now, or leave it if they're on a drive that isn't "
                "plugged in.", [("Pick the clips folder…", "pick", "primary")],
                cancel="Leave it")
            if answer != "pick":
                return
            chosen = QFileDialog.getExistingDirectory(self, "Your clips folder",
                                                      config.resolved_clip_dir())
            if chosen:
                self.context.config.clip_path = chosen
                self.context.save_config()
                self.settings_view.load()
                self._settings_saved(True)

        workers.run(lambda: backup.missing_clips(config), counted)

    def clear_cache(self) -> None:
        context = self.context
        if context.thumbs is not None:
            context.thumbs.shutdown()
        ThumbnailCache(context.config.resolved_cache_dir()).clear()
        logs.APP.info("Cache cleared")
        context.open_library()
        self.state.reload()
        self.settings_view.banner.show_message("Cache cleared", "ok")

    def start_services(self, enable_sonar: bool | None = None,
                       start_recorder: bool | None = None,
                       tags: tuple[dict, dict] | None = None) -> None:
        """Open the library and start Sonar and the recorder. `tags` are the
        games and dates setup confirmed, written before the first scan so it
        doesn't tag those clips its own way first."""
        self._services_started = True
        context = self.context
        context.open_library()
        cache = context.config.resolved_cache_dir()
        workers.run(lambda: export.clear_shares(cache))
        if tags is not None:
            self._write_setup_tags(*tags)
        self.state.reload()
        if context.thumbs is not None:
            QTimer.singleShot(5000, lambda: context.thumbs.prune(
                [clip.path for clip in self.state.all_clips]))
        if context.sonar is not None:
            context.sonar.start()
            if enable_sonar:
                context.sonar.set_enabled(True)
        if context.recorder.enabled:
            context.recorder.detect()
        self.back_up_daily()
        self._backup_timer.start()
        if start_recorder if start_recorder is not None else context.config.recorder.autostart:
            context.recorder.start()

    def back_up_daily(self) -> None:
        config = copy.deepcopy(self.context.config)

        def made(path: str) -> None:
            if path:
                logs.APP.info("Backed up to %s", path)
                self.settings_view.show_backups()

        workers.run(lambda: backup.back_up_daily(config), made,
                    lambda exc: logs.APP.warning("Couldn't back up: %s", exc))

    def event(self, event) -> bool:
        # Qt builds the native window again for the editor's OpenGL video,
        # and the new one has none of the taskbar's properties: each one
        # gets them, or the taskbar shows (and pins) python.exe.
        if event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange) and self.internalWinId():
            platform.put_on_taskbar(int(self.internalWinId()))
        return super().event(event)

    def add_to_start_menu(self) -> None:
        """Into the start menu on the first start, before setup is done, so
        quitting setup still leaves the entry; never again once removed."""
        ink = icons.desktop_ink()
        self.start_menu_job = workers.run(
            lambda: desktop.ensure(ink), None,
            lambda exc: logs.APP.warning("Couldn't add the start menu entry: %s", exc))

    def _ink_changed(self, *_args) -> None:
        """The desktop turned light or dark: the icons on it follow."""
        ink = icons.desktop_ink()
        icon = icons.app_icon(ink)
        QApplication.instance().setWindowIcon(icon)
        self.setWindowIcon(icon)
        if self.tray is not None:
            self.tray.setIcon(icon)
        self.add_to_start_menu()

    def _settings_saved(self, folders_changed: bool) -> None:
        if folders_changed:
            self.context.open_library()
            self.state.reload()

    def _open_import(self) -> None:
        self.navigate("settings")
        self.settings_view.show_page("import")

    def _focus_search(self) -> None:
        if self.first_run is None:
            self.navigate("library")
            self.topbar.search.setFocus()
            self.topbar.search.selectAll()

    # --- Editor ----------------------------------------------------------------

    def open_clip(self, clip, opened_from: str = "") -> None:
        if not clip.path or not os.path.exists(clip.path):
            self.banner.show_message(f"{clip.name} is gone from the clips folder.", "warn")
            self.state.reload()
            return
        self._close_editor()
        # Back, and out after a delete or trim, goes where the clip was opened from.
        self._editor_from = opened_from or (
            "home" if self.stack.currentWidget() is self.home_view else "library")
        self.editor = EditorView(self.context, self.state, clip)
        self.editor.back.connect(lambda: self.navigate(self._editor_from))
        self.editor.step.connect(self._step_clip)
        names = [each.name for each in self._editor_order()]
        here = names.index(clip.name) if clip.name in names else -1
        self.editor.set_neighbours(here > 0, 0 <= here < len(names) - 1)
        self.editor.delete_requested.connect(self._delete_from_editor)
        self.editor.trimmed.connect(self._clip_trimmed)
        self.stack.addWidget(self.editor)
        self.stack.setCurrentWidget(self.editor)
        # The editor takes the whole window: nothing on the top bar helps mid-trim.
        self.topbar.hide()
        self.editor.setFocus()

    def _close_editor(self) -> None:
        editor, self.editor = self.editor, None
        if editor is None:
            return
        editor.close_editor()
        self._remove_page(editor)

    def _editor_order(self) -> list:
        """The clips the editor steps through: the library's, as it shows
        them, or from Home every clip, newest first."""
        if self._editor_from == "home":
            return clips_mod.sort_clips(self.state.all_clips, "date", True)
        return list(self.state.visible)

    def _step_clip(self, delta: int) -> None:
        if self.editor is None:
            return
        order = self._editor_order()
        names = [clip.name for clip in order]
        if self.editor.clip.name in names:
            index = names.index(self.editor.clip.name) + delta
            if 0 <= index < len(order):
                self.open_clip(order[index], self._editor_from)

    def _delete_from_editor(self, clip) -> None:
        if not self.library_view.confirm_delete(clip):
            return
        # Leave first: mpv still has the file open.
        self.navigate(self._editor_from)
        self.state.delete(clip)

    def _clip_trimmed(self, clip, mode: str, path: str) -> None:
        if mode == "copy":
            self.state.reload()
            return
        self.navigate(self._editor_from)    # releases the file before it is replaced
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
        self.context.notify("clip_saved", "Clip saved", "It's in your library")

    def _notified(self, notice: notifications.Notice) -> None:
        """Every notice shows at the bottom of the window. It pops up too, if its
        kind is switched on and the window isn't in front: over games through
        GPU Screen Recorder's notifier when that is on, else on the desktop."""
        kind = notifications.BY_ID[notice.kind]
        self.banner.show_message(notice.line, kind.level, 12000 if kind.level == "error"
                                 else 6000)
        in_front = self.isVisible() and self.isActiveWindow() and not self.isMinimized()
        if in_front or self._quitting or \
                not notifications.enabled(self.context.config.notifications, kind.id):
            return
        if self.context.config.notify_over_games and self._over_games(notice, kind):
            return
        if self.tray is not None:
            self.tray.pop_up(notice)

    def _over_games(self, notice: notifications.Notice, kind: notifications.Kind) -> bool:
        if platform.GAME_TOAST:
            if self.game_toast is None:
                self.game_toast = GameToast()
            return self.game_toast.show_notice(notice.title, notice.body, kind.level)
        background, ink = {"warn": (theme.WARN, theme.ON_DANGER),
                           "error": (theme.DANGER, theme.ON_DANGER)}.get(
            kind.level, (theme.ACCENT_FILL, theme.ON_ACCENT))
        return self.over_games.show(notice.line, kind.level, background, ink, kind.icon)

    def _test_over_games(self) -> None:
        """Settings › Notifications' "Send a test": a sample over whatever is on
        screen, as a saved clip would show over a game. GSR's notifier may not
        start; Vertex's own toast always does."""
        notice = notifications.Notice("clip_saved", "Clip saved", "This is how it looks")
        if not self._over_games(notice, notifications.BY_ID["clip_saved"]):
            self.settings_view.banner.show_message(
                "GPU Screen Recorder's notifier didn't start.", "error", 8000)

    # --- Window -------------------------------------------------------------------

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        if QGuiApplication.platformName() == "wayland":
            # Wayland won't let us take the focus; the desktop may give it.
            # The pause lets a window coming out of the tray map first.
            pid = os.getpid()
            QTimer.singleShot(150, lambda: workers.run(lambda: platform.activate_windows(pid)))

    def closeEvent(self, event):
        tray_ok = self.tray is not None and QSystemTrayIcon.isSystemTrayAvailable()
        if not self._quitting and self.context.config.close_to_tray and tray_ok:
            event.ignore()
            self._close_editor()
            self.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self.context.notify("in_tray", "Still running in the tray")
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
        self.library_view.cancel_exports()
        self._close_editor()
        if self.game_toast is not None:
            self.game_toast.close()
        self.close()
        QApplication.instance().quit()


def _kept(where: str, subject: str) -> str:
    """Where a reset put the file it replaced, as a sentence."""
    if not where:
        return ""
    if where == "the Trash":
        return f"The {subject} in the Trash."
    return f"The {subject} kept as {where}."

