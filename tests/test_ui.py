"""Smoke tests for the Qt UI: every page builds, and the main flows work.

Runs with the offscreen platform. The editor needs OpenGL for video, so its
test only runs with a display (CI runs the suite under xvfb-run).
"""

import ctypes.util
import os
import shutil
import time
from concurrent import futures

import pytest

pytest.importorskip("PySide6")

if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtWidgets import QApplication, QLineEdit

from vertex.config import Config
from vertex.core import naming

pytestmark = pytest.mark.gui


@pytest.fixture(scope="session")
def qapp():
    from vertex.ui import app as app_mod

    return app_mod._create_app()


def wait_until(qapp, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def library_dir(tmp_path, sample_clip):
    clips = tmp_path / "clips"
    clips.mkdir()
    # copy2 keeps the file's date, so the clips don't count as still being written.
    shutil.copy2(sample_clip, clips / os.path.basename(sample_clip))
    shutil.copy2(sample_clip, clips / "Replay_2026-01-02_03-04-05.mp4")
    return clips


@pytest.fixture
def window(qapp, tmp_path, library_dir):
    from vertex.ui.main_window import MainWindow
    from vertex.ui.services import Context

    config = Config(clip_path=str(library_dir), export_path=str(tmp_path / "exports"),
                    data_path=str(tmp_path / "data"), state_path=str(tmp_path / "state"),
                    cache_path=str(tmp_path / "cache"))
    config.recorder.command = str(tmp_path / "no-such-recorder")
    config.save()
    context = Context(config)
    win = MainWindow(context)
    win.add_to_start_menu()             # as starting Vertex does
    win.start_services()
    win.navigate("library")
    win.resize(1280, 800)
    win.show()
    yield win
    # It reads HOME as it goes, and the next test has another one: finishing
    # after this test would leave half an entry here and half there.
    futures.wait([win.start_menu_job], timeout=30)
    win._quitting = True
    win._close_editor()
    context.shutdown()
    win.deleteLater()
    qapp.processEvents()


def test_library_lists_and_tags_clips(qapp, window):
    state = window.state
    assert len(state.visible) == 2
    # The Moments-style name was tagged from the file name on first scan.
    assert ("Apex Legends", 1) in state.games()
    assert wait_until(qapp, lambda: window.library_view.model.duration(state.visible[0]))

    clip = state.find("Replay_2026-01-02_03-04-05.mp4")
    state.set_tags(clip, "The Finals", ["Anna"])
    assert state.tags_of(clip) == ("The Finals", ["Anna"])
    assert state.toggle_favorite(clip)
    assert state.favorite_count() == 1

    from vertex.ui.library.state import Facet
    state.set_facet(Facet("game", "The Finals"))
    assert [c.name for c in state.visible] == [clip.name]
    state.set_facet(Facet("all"))
    state.set_query("anna")
    assert [c.name for c in state.visible] == [clip.name]
    state.set_query("")
    assert state.set_title(clip, "Big play") == "Big play"
    assert state.title_of(clip) == "Big play"


def test_renaming_a_card_keeps_the_typing_while_its_row_changes(qapp, window):
    view = window.library_view
    window.navigate("library")
    index = view.model.index(0)
    view.grid.edit(index)
    qapp.processEvents()
    editor = view.grid.indexWidget(index) or view.grid.findChild(QLineEdit)
    assert editor is not None
    editor.setText("Big play")
    # A hover-preview frame or a thumbnail arriving changes the row.
    view.model.dataChanged.emit(index, index)
    qapp.processEvents()
    assert editor.text() == "Big play"


def test_library_keys_move_a_focus_ring_and_act_on_its_card(qapp, window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view, state = window.library_view, window.state
    grid = view.grid
    # Keys go to the active window only (under Xvfb there's no window manager
    # to make it active).
    window.activateWindow()
    QTest.qWaitForWindowActive(window, 2000)
    grid.setFocus()
    assert wait_until(qapp, grid.hasFocus, 5)
    assert grid.focus_row() == -1            # no ring until a key is used
    QTest.keyClick(grid, Qt.Key.Key_Right)   # shows it, on the first card
    assert grid.focus_row() == 0
    QTest.keyClick(grid, Qt.Key.Key_Right)
    assert grid.focus_row() == 1
    second = state.visible[1]

    QTest.keyClick(grid, Qt.Key.Key_F)
    assert second.name in state.favorites
    opened, deleted = [], []
    window.library_view.open_clip.disconnect()
    view.open_clip.connect(opened.append)
    QTest.keyClick(grid, Qt.Key.Key_Return)
    assert opened == [second]
    monkeypatch.setattr(view, "delete", deleted.append)
    grid.delete_key.disconnect()
    grid.delete_key.connect(view.delete)
    QTest.keyClick(grid, Qt.Key.Key_Delete)
    assert deleted == [second]
    QTest.keyClick(grid, Qt.Key.Key_F2)
    assert grid.state() == grid.State.EditingState
    QTest.keyClick(grid.findChild(QLineEdit), Qt.Key.Key_Escape)
    assert wait_until(qapp, lambda: grid.state() != grid.State.EditingState, 5)
    grid.setFocus()

    menus = []
    grid.customContextMenuRequested.disconnect()
    grid.customContextMenuRequested.connect(menus.append)
    QTest.keyClick(grid, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    assert len(menus) == 1 and grid.indexAt(menus[0]).row() == 1

    # A click hides the ring again.
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.RightButton, pos=grid.visualRect(
        grid.model().index(0, 0)).center())
    assert grid.focus_row() == -1


def test_a_card_is_not_dragged_out(qapp, window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDrag, QMouseEvent

    grid = window.library_view.grid
    dragged = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: dragged.append(
        [url.toLocalFile() for url in self.mimeData().urls()]) or Qt.DropAction.CopyAction)
    opened = []
    window.library_view.open_clip.disconnect()
    window.library_view.open_clip.connect(opened.append)
    start = grid.visualRect(grid.model().index(0, 0)).center()

    def mouse(kind, point, buttons):
        event = QMouseEvent(kind, point, grid.viewport().mapToGlobal(point),
                            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(grid.viewport(), event)

    mouse(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    mouse(QEvent.Type.MouseMove, start + QPoint(40, 0), Qt.MouseButton.LeftButton)
    mouse(QEvent.Type.MouseButtonRelease, start + QPoint(40, 0), Qt.MouseButton.NoButton)
    assert dragged == []                      # the full-size file is never handed out
    opened.clear()
    # A plain click still opens the clip.
    mouse(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    mouse(QEvent.Type.MouseButtonRelease, start, Qt.MouseButton.NoButton)
    assert opened == [window.state.visible[0]]


def test_quick_export_uses_the_saved_trim_and_copies_the_file(qapp, window, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QMenu

    from vertex.media import probe

    view, state, context = window.library_view, window.state, window.context
    clip = state.find("Replay_2026-01-02_03-04-05.mp4")
    context.library.set_trim(clip.name, 1.0, 3.0)
    assert view.quick_size() == ("10 MB", 10 * 1024 * 1024)   # before any export
    context.config.export_size = "Original"
    assert view.quick_size()[0] == "Original"
    notices = []
    view.notice.connect(lambda text, level, _ms, click: notices.append((text, level, click)))
    entries = []

    def read_menu():
        menu = next(w for w in qapp.topLevelWidgets() if isinstance(w, QMenu) and w.isVisible())
        entries.extend(action.text() for action in menu.actions())
        menu.close()
    QTimer.singleShot(200, read_menu)
    grid = view.grid
    view.clip_menu(grid, grid.visualRect(view.model.index(state.visible.index(clip))).center())
    assert "Quick export · Original" in entries
    view.quick_export(clip)
    assert wait_until(qapp, lambda: notices and notices[-1][1] != "info", 60), notices
    text, level, click = notices[-1]
    assert level == "ok" and "copied" in text and callable(click)
    exported = [url.toLocalFile() for url in QGuiApplication.clipboard().mimeData().urls()]
    assert len(exported) == 1 and exported[0].startswith(str(tmp_path / "exports"))
    assert abs(probe.probe(exported[0]).duration - 2.0) < 0.6
    # The offscreen platform crashes at exit while the clipboard holds data.
    QGuiApplication.clipboard().clear()


def test_tag_dialog_suggests_and_saves_on_enter(qapp, window):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest

    from vertex.ui.dialogs.tags import TagDialog

    state = window.state
    state.set_tags(state.find("Replay_2026-01-02_03-04-05.mp4"), "The Finals", ["Anna"])
    clip = next(c for c in state.all_clips if c.name != "Replay_2026-01-02_03-04-05.mp4")
    seen = {}

    def fill():
        dialog = next(w for w in qapp.topLevelWidgets()
                      if isinstance(w, TagDialog) and w.isVisible())
        games, people = dialog.game.completer(), dialog.person.completer()
        games.setCompletionPrefix("fin")
        people.setCompletionPrefix("ann")
        seen["suggested"] = (games.currentCompletion(), people.currentCompletion())
        dialog.activateWindow()
        dialog.person.setFocus()
        seen["focus"] = wait_until(qapp, dialog.person.hasFocus, 5)
        QTest.keyClicks(dialog.person, "Ben")
        people.popup().hide()
        QTest.keyClick(dialog.person, Qt.Key.Key_Return)    # adds Ben, stays open
        seen["open"] = dialog.isVisible()
        dialog.game.setFocus()
        dialog.game.setText("the finals")
        QTest.keyClick(dialog.game, Qt.Key.Key_Return)      # saves
    QTimer.singleShot(0, fill)
    window.library_view.edit_tags(clip)
    assert seen == {"suggested": ("The Finals", "Anna"), "focus": True, "open": True}
    # Saved in the spelling already in use.
    assert state.tags_of(clip) == ("The Finals", ["Ben"])


def test_library_filters_pick_a_game_or_person_from_their_lists(qapp, window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from vertex.ui.library.state import Facet

    state, filters = window.state, window.library_view.filters
    state.set_tags(state.find("Replay_2026-01-02_03-04-05.mp4"), "The Finals", ["Anna"])
    assert filters.all.is_applied() and filters.all.count == "2"
    assert not filters.untagged.isVisibleTo(filters)      # every clip has a game now
    assert filters.games.text() == "All games" and filters.games.count == "2"

    # Games: a list with a search; Enter picks what the search leaves.
    filters.games.click()
    menu = filters.menu
    assert [menu.list.item(i).text() for i in range(menu.list.count())] == \
        ["All games", "Apex Legends", "The Finals"]
    QTest.keyClicks(menu.find, "fin")
    shown = [menu.list.item(i).text() for i in range(menu.list.count())
             if not menu.list.item(i).isHidden()]
    assert shown == ["The Finals"]
    QTest.keyClick(menu.find, Qt.Key.Key_Return)
    assert state.facet == Facet("game", "The Finals")
    assert len(state.visible) == 1
    # The chip names the game it filters by, and All clips no longer applies.
    assert filters.games.text() == "The Finals" and filters.games.is_applied()
    assert not filters.all.is_applied()

    # People the same way; one filter at a time.
    filters.people.click()
    menu = filters.menu
    anna = next(menu.list.item(i) for i in range(menu.list.count())
                if menu.list.item(i).text() == "Anna")
    menu.list.itemClicked.emit(anna)
    assert state.facet == Facet("person", "Anna")
    assert filters.people.text() == "Anna" and not filters.games.is_applied()
    assert filters.games.text() == "All games"

    filters.all.click()
    assert state.facet == Facet("all") and len(state.visible) == 2


def test_library_cards_fill_their_row_at_any_size(qapp, window):
    from vertex.config import CARD_WIDTH_DEFAULT

    view = window.library_view
    grid, model = view.grid, view.grid.model()
    assert not grid.verticalScrollBar().isVisible()     # two clips: no scroll bar
    # Every size whose row holds both clips must show them side by side; the
    # grid used to plan one column more than Qt lays out without a scroll bar.
    for width in range(200, 641, 7):
        grid.set_card_width(width)
        qapp.processEvents()
        cell = view.delegate.cell.width()
        assert cell >= width
        if grid.layout_width() // width >= 2:
            first, second = (grid.visualRect(model.index(i, 0)) for i in (0, 1))
            assert first.y() == second.y(), width
            assert second.right() < grid.viewport().width()

    # Thumbnails load at about the cards' size: sharp, without holding more
    # memory than needed.
    grid.set_card_width(600)
    big = view.model.thumb_size.width()
    assert big >= view.delegate.cell.width() - 20 or big == 960
    grid.set_card_width(200)
    assert view.model.thumb_size.width() < big

    # The header slider, Ctrl+scroll and the shortcuts set it, and it is kept.
    view.card_size.setValue(400)
    assert grid.card_width == 400 and window.context.config.card_width == 400
    view.zoom(1)
    assert window.context.config.card_width == 420
    view.zoom(-3)
    assert window.context.config.card_width == 360
    window.context.save_config()
    assert Config.load().card_width == 360
    view.card_size.setValue(CARD_WIDTH_DEFAULT)


def test_starting_adds_the_start_menu_entry(qapp, window):
    from vertex import desktop

    assert wait_until(qapp, lambda: desktop.desktop_file().exists())
    assert desktop.added_marker().exists()


def test_icons_follow_the_desktop_turning_light_or_dark(qapp, window, monkeypatch):
    from vertex import desktop
    from vertex.ui import icons

    futures.wait([window.start_menu_job], timeout=30)
    assert desktop.icon_ink() == icons.desktop_ink()
    other = "dark" if icons.desktop_ink() == "light" else "light"
    monkeypatch.setattr(icons, "desktop_ink", lambda: other)
    window._ink_changed()
    futures.wait([window.start_menu_job], timeout=30)
    assert desktop.icon_ink() == other
    assert not hasattr(window.settings_view, "logo")       # no choice left to make


def test_pages_and_settings_save(qapp, window):
    for page in ("home", "settings", "library"):
        window.navigate(page)
        qapp.processEvents()
    settings = window.settings_view
    settings.load()
    settings.duration.setCurrentIndex(settings.duration.findData(90))
    assert settings.is_dirty()
    assert settings.save()
    assert Config.load().recorder.replay_seconds == 90
    assert not settings.is_dirty()
    settings.show_page("recording")
    assert "-r 90" in settings.preview.toPlainText()
    # Vertex's own folders are folded away, and still saved.
    assert not settings.folders_advanced.expanded
    settings.cache_path.set_value(str(window.context.config.resolved_cache_dir()) + "-2")
    assert settings.save()
    assert Config.load().cache_path.endswith("-2")


def test_the_scheme_picker_leaves_no_row_short(qapp, window):
    """Nine schemes go three by three rather than four, four and one."""
    from vertex.ui.settings.schemes import SchemePicker

    assert SchemePicker.per_row(9, 4) == 3
    assert SchemePicker.per_row(8, 4) == 4
    assert SchemePicker.per_row(9, 2) == 2
    window.navigate("settings")
    window.settings_view.show_page("general")
    window.resize(1600, 1000)
    picker = window.settings_view.schemes
    assert wait_until(qapp, lambda: picker._per_row == SchemePicker.per_row(
        len(picker.cards), 4))
    window.resize(1280, 800)


def test_drop_down_rows_take_the_highlight(qapp, window):
    """A drop-down opens as a list, so its hovered and current rows take the
    selected colour (as a menu, Qt drew them darker than the list)."""
    from PySide6.QtWidgets import QComboBox, QStyledItemDelegate

    from vertex.ui import theme

    combo = QComboBox(window)
    combo.addItems(["30 seconds", "60 seconds"])
    assert isinstance(combo.itemDelegate(), QStyledItemDelegate)
    assert f"background: {theme.ACCENT_SOFT}" in qapp.styleSheet().split("::item:hover")[1]
    combo.deleteLater()


def test_plum_puts_white_text_on_a_deeper_pink():
    """Plum's buttons: white on a pink deeper than its accent, which stays hot
    for lines and glows; its selected items are periwinkle, not wine."""
    from vertex.ui import theme

    plum = theme.SCHEMES["plum"][2]
    assert plum["ON_ACCENT"] == "#ffffff"
    assert plum["ACCENT_FILL"] != plum["ACCENT"]
    assert plum["ACCENT_SOFT"] == theme._mix(plum["CARD_BG"], plum["SECOND"], 0.3)


def test_a_colour_scheme_shows_and_is_kept_at_once(qapp, window):
    from vertex.ui import theme

    navy, spooky = theme.SCHEMES["navy"][2], theme.SCHEMES["spooky"][2]
    window.navigate("settings")
    settings = window.settings_view
    settings.show_page("general")
    assert settings.schemes.value() == "navy" == theme.scheme
    pill = window.topbar.recorder
    assert navy["SECTION_BG"] in pill.styleSheet()
    try:
        # Picking one restyles everything already built.
        settings.schemes.cards["spooky"].click()
        assert theme.scheme == "spooky"
        assert spooky["ACCENT"] in qapp.styleSheet()
        assert spooky["SECTION_BG"] in pill.styleSheet()
        # Picked, it is saved at once: the next start opens with it.
        assert not settings.is_dirty()
        assert Config.load().colour_scheme == "spooky"
        settings.load()
        assert theme.scheme == "spooky" and settings.schemes.value() == "spooky"
        settings.schemes.cards["navy"].click()
        assert Config.load().colour_scheme == "navy"
        assert navy["SECTION_BG"] in pill.styleSheet()
    finally:
        theme.use(theme.DEFAULT_SCHEME)


def test_shortcuts_tab_lists_commands_the_cli_takes(qapp, window):
    import shlex

    from vertex import cli
    from vertex.ui.settings.shortcuts import COMMANDS

    for _group, commands in COMMANDS:
        for command, _title, _more in commands:
            argv = shlex.split(command)
            assert argv[0] == "vertex"
            cli._parser().parse_args(argv[1:])     # exits on a command it doesn't take
    window.settings_view.show_page("shortcuts")
    assert window.settings_view.tabs.current == "shortcuts"


def test_storage_gauge_fills_by_what_is_not_free(qapp):
    from vertex.core.storage import StorageStats
    from vertex.ui.widgets import StorageGauge

    gb = 1024 ** 3
    # The disk counts 80 GB used, but keeps 15 GB back: 5 GB are free to use.
    stats = StorageStats(clips_bytes=2 * gb, disk_total=100 * gb, disk_used=80 * gb,
                         disk_free=5 * gb)
    gauge, short = StorageGauge(), StorageGauge(short=True)
    for widget in (gauge, short):
        widget.set_stats(stats)
        assert abs(widget.meter.fraction - 0.95) < 1e-9
    assert gauge.text.text().endswith(f"free of {stats.total_human}")
    assert short.text.text() == f"Clips {stats.clips_human} · {stats.free_human} free"


def test_capture_is_picked_on_the_monitor_map(qapp, window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from vertex.recorder import gsr, monitors
    from vertex.ui import screens

    monkeypatch.setattr(screens, "desktop_screens", lambda: [
        monitors.Screen("DP-1", 0, 240, 2560, 1440, "Dell", (2560, 1440), primary=True),
        monitors.Screen("DP-2", 2560, 0, 1080, 1920, "AOC", (1080, 1920))])
    window.navigate("settings")
    settings = window.settings_view
    settings.show_page("recording")
    # The fixture's recorder doesn't exist; let that answer arrive first.
    assert wait_until(qapp, lambda: "not installed" in settings.gsr_status.text())
    the_map = settings.monitor_map
    assert [m.name for m in the_map.monitors] == ["DP-1", "DP-2"]
    # Nothing picked yet (the default, "screen"): the primary monitor is recorded.
    assert the_map.current == "DP-1"
    assert settings.capture_note.text() == "DP-1 · primary monitor"
    assert "-w DP-1" in settings.preview.toPlainText()
    assert not settings.is_dirty()

    options = gsr.parse_capture_options("DP-1|2560x1440\nDP-2|1080x1920\nportal\n")
    settings._show_recorder((gsr.GsrInfo("gsr", True, (5, 15, 1), "5.15.1"), options, []))
    qapp.processEvents()
    vertical = the_map.rect_of("DP-2")
    assert vertical.height() > vertical.width()
    QTest.mouseClick(the_map, Qt.MouseButton.LeftButton, pos=vertical.center().toPoint())
    assert settings.collect().recorder.capture == "DP-2"
    assert settings.capture_note.text() == "DP-2 · 1080 × 1920"
    assert "-w DP-2" in settings.preview.toPlainText()
    QTest.keyClick(the_map, Qt.Key.Key_Left)
    assert settings.collect().recorder.capture == "DP-1" and the_map.current == "DP-1"
    assert settings.save()
    assert Config.load().recorder.capture == "DP-1"

    # A picked monitor that isn't connected stays picked; the primary one
    # is recorded meanwhile, by Settings' preview and the recorder alike.
    window.context.config.recorder.capture = "HDMI-A-1"
    settings.load()
    assert the_map.current == "DP-1"
    assert settings.capture_note.text() == "HDMI-A-1 isn't connected · recording DP-1"
    assert settings.collect().recorder.capture == "HDMI-A-1"
    assert "-w DP-1" in settings.preview.toPlainText()
    assert window.context.recorder.capture_target() == "DP-1"


def test_clip_settings_follow_the_recorded_monitor(qapp, window, monkeypatch):
    from vertex.recorder import monitors
    from vertex.ui import screens
    from vertex.ui.widgets import Disclosure

    monkeypatch.setattr(screens, "desktop_screens", lambda: [
        monitors.Screen("DP-1", 0, 240, 2560, 1440, pixels=(2560, 1440), primary=True),
        monitors.Screen("DP-2", 2560, 0, 1080, 1920, pixels=(1080, 1920))])
    window.navigate("settings")
    settings = window.settings_view
    settings.show_page("recording")
    assert wait_until(qapp, lambda: "not installed" in settings.gsr_status.text())

    def texts(widget):
        return [widget.itemText(i) for i in range(widget.count())]

    assert texts(settings.duration) == ["30 seconds", "60 seconds", "90 seconds",
                                        "120 seconds"]
    assert texts(settings.fps) == ["30 fps", "60 fps", "120 fps"]
    assert texts(settings.resolution) == ["720p · 1280 × 720", "1080p · 1920 × 1080",
                                          "Native · 2560 × 1440"]
    assert settings.video_quality.currentText() == "High · 31 Mbps"
    assert not settings.findChild(Disclosure).expanded

    # The vertical monitor: sizes up to its own, standing up.
    settings.choices.pick_monitor("DP-2")
    assert texts(settings.resolution) == ["720p · 720 × 1280", "Native · 1080 × 1920"]
    assert settings.video_quality.currentText() == "High · 20 Mbps"
    settings.resolution.setCurrentIndex(settings.resolution.findData("720p"))
    assert "-s 720x1280" in settings.preview.toPlainText()
    assert settings.video_quality.currentText() == "High · 11 Mbps"
    # 11 Mbps of video and two AAC tracks (game and mic), for a minute.
    assert settings.clip_size.text() == "About 81 MB per clip"
    assert wait_until(qapp, lambda: "more clips" in settings.disk_room.text())

    # A bitrate set by hand shows as Custom; picking a level drops it.
    settings.bitrate.setValue(40000)
    assert settings.video_quality.currentText() == "Custom · 40 Mbps"
    ultra = settings.video_quality.findData("ultra")
    settings.video_quality.setCurrentIndex(ultra)
    settings.video_quality.activated.emit(ultra)
    assert settings.bitrate.value() == 0
    rec = settings.collect().recorder
    assert (rec.quality, rec.resolution, rec.capture) == ("ultra", "720p", "DP-2")

    # Values from older settings stay chosen, shown as they are.
    window.context.config.recorder.replay_seconds = 45
    window.context.config.recorder.fps = 144
    settings.load()
    assert settings.duration.currentText() == "45 seconds"
    assert settings.fps.currentText() == "144 fps"
    assert not settings.is_dirty()


def test_tracks_are_chosen_on_the_recording_page(qapp, window, monkeypatch):
    from vertex.recorder import gsr

    window.navigate("settings")
    settings = window.settings_view
    settings.show_page("recording")
    assert wait_until(qapp, lambda: "not installed" in settings.gsr_status.text())
    # The default output and microphone by default, and no chat track.
    rec = settings.collect().recorder
    assert (rec.game_audio, rec.chat_audio, rec.mic_audio) == (
        "default_output", "", "default_input")

    devices = [("default_output", "Default output"), ("default_input", "Default input"),
               ("alsa_output.usb-headset.monitor", "Monitor of Arctis Nova Pro"),
               ("alsa_input.usb-headset", "Arctis Nova Pro Mono")]
    info = gsr.GsrInfo("gsr", True, (5, 15, 1), "5.15.1")
    window.context.recorder.info = info          # names tracks in the preview
    settings._show_recorder((info, [], devices))
    qapp.processEvents()

    def texts(widget):
        return [widget.itemText(i) for i in range(widget.count())]

    assert texts(settings.chat_audio) == ["None", "Default output", "Arctis Nova Pro"]
    assert texts(settings.mic_audio) == ["None", "Default microphone", "Arctis Nova Pro Mono"]
    preview = settings.preview.toPlainText()
    assert "name:Vertex Game|default_output" in preview
    assert "name:Vertex Mic|default_input" in preview
    assert "Vertex Chat" not in preview

    settings.chat_audio.setCurrentIndex(
        settings.chat_audio.findData("device:alsa_output.usb-headset.monitor"))
    assert "name:Vertex Chat|device:alsa_output.usb-headset.monitor" in \
        settings.preview.toPlainText()
    settings.chat_audio.setCurrentIndex(settings.chat_audio.findData(""))
    settings.mic_audio.setCurrentIndex(settings.mic_audio.findData("device:alsa_input.usb-headset"))
    assert "Vertex Chat" not in settings.preview.toPlainText()
    assert "name:Vertex Mic|device:alsa_input.usb-headset" in settings.preview.toPlainText()
    assert texts(settings.media_audio) == ["None", "Default output", "Arctis Nova Pro"]
    assert not settings.tracks.volumes                  # GSR records devices as they are
    assert settings.save()
    saved = Config.load().recorder
    assert (saved.chat_audio, saved.mic_audio) == ("", "device:alsa_input.usb-headset")


def test_each_track_has_a_recording_volume_where_the_recorder_sets_one(qapp, monkeypatch):
    from vertex.config import RecorderConfig
    from vertex.ui.settings.tracks import TrackTable

    table = TrackTable(with_volume=True)
    for device in table.devices.values():
        device.addItem("None", "")
        device.addItem("Default output", "default_output")
    table.devices["game"].setCurrentIndex(1)
    table.load(RecorderConfig(game_volume=80))
    assert table.readouts["game"].text() == "80%" and table.volumes["game"].isEnabled()
    assert not table.volumes["media"].isEnabled()         # records nothing
    changed = []
    table.changed.connect(lambda: changed.append(True))
    table.volumes["game"].setValue(55)
    rec = RecorderConfig()
    table.apply(rec)
    assert (rec.game_volume, rec.media_volume, changed) == (55, 100, [True])


def test_a_restart_shows_until_the_buffer_runs_again(qapp, window, tmp_path, monkeypatch):
    import stat
    import sys

    from test_recorder import FAKE_GSR
    from vertex.recorder import backend, monitors
    from vertex.ui import screens

    fake_gsr = tmp_path / "gpu-screen-recorder"
    fake_gsr.write_text(FAKE_GSR.format(python=sys.executable))
    fake_gsr.chmod(fake_gsr.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(screens, "desktop_screens", lambda: [
        monitors.Screen("DP-1", 0, 0, 2560, 1440, primary=True)])
    context = window.context
    context.config.recorder.command = str(fake_gsr)
    recorder = context.recorder
    recorder.start()
    assert wait_until(qapp, lambda: recorder.phase == "running")
    assert "-w DP-1" in backend.describe(recorder.launch_plan())

    states, notices = [], []
    recorder.state_changed.connect(lambda state, _error: states.append(state))
    context.notified.connect(notices.append)
    pill = window.topbar.recorder
    recorder.restart_if_running()
    assert pill.title.text() == "Restarting…"
    assert wait_until(qapp, lambda: recorder.phase == "running" and notices)
    # No "Off" or "Starting…" flashing past in between.
    assert states == ["restarting", "running"]
    assert pill.title.text() == "Replay on"
    assert [(n.kind, n.title) for n in notices] == [("replay_restarted",
                                                     "Replay buffer restarted")]

    # Stopping in the middle of a restart stops it for good.
    recorder.restart_if_running()
    recorder.toggle()
    assert wait_until(qapp, lambda: recorder.phase == "stopped")
    qapp.processEvents()
    time.sleep(0.5)
    qapp.processEvents()
    assert recorder.phase == "stopped" and pill.title.text() == "Replay off"


def test_a_buffer_that_dies_while_recording_starts_again_once(qapp, window, tmp_path,
                                                             monkeypatch):
    import signal
    import stat
    import sys

    from test_recorder import FAKE_GSR
    from vertex.recorder import monitors
    from vertex.ui import screens

    fake_gsr = tmp_path / "gpu-screen-recorder"
    fake_gsr.write_text(FAKE_GSR.format(python=sys.executable))
    fake_gsr.chmod(fake_gsr.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(screens, "desktop_screens", lambda: [
        monitors.Screen("DP-1", 0, 0, 2560, 1440, primary=True)])
    context = window.context
    context.config.recorder.command = str(fake_gsr)
    recorder = context.recorder
    recorder.start()
    assert wait_until(qapp, lambda: recorder.phase == "running")

    states, notices = [], []
    recorder.state_changed.connect(lambda state, _error: states.append(state))
    context.notified.connect(notices.append)
    first = recorder.recorder.pid
    os.kill(first, signal.SIGKILL)
    assert wait_until(qapp, lambda: states[-1:] == ["running"])
    assert states == ["restarting", "running"]
    assert recorder.recorder.pid != first
    assert [(n.kind, n.body) for n in notices] == [
        ("replay_restarted", "GPU Screen Recorder had stopped")]

    # Dying again so soon: it stays off, and says so.
    states.clear()
    notices.clear()
    os.kill(recorder.recorder.pid, signal.SIGKILL)
    assert wait_until(qapp, lambda: recorder.phase == "failed")
    qapp.processEvents()
    assert states == ["failed"]
    assert [n.kind for n in notices] == ["replay_failed"]

    # A start that fails is not retried.
    recorder._recovered_at = float("-inf")
    context.config.recorder.extra_args = "bad"
    states.clear()
    recorder.start()
    assert wait_until(qapp, lambda: states[-1:] == ["failed"])
    time.sleep(0.5)
    qapp.processEvents()
    assert "restarting" not in states and recorder.phase == "failed"
    recorder.stop()


def test_filter_row_fits_long_names_and_narrow_windows(qapp, window, monkeypatch):
    from vertex.ui.library.filters import NAME_MAX
    from vertex.ui.library.state import Facet, LibraryState

    filters = window.library_view.filters
    monkeypatch.setattr(LibraryState, "games",
                        lambda self: [("Euro Truck Simulator 2", 632), ("Long " * 30, 1)])
    window.state.set_facet(Facet("game", "Long " * 30))
    # A name too long for its chip is cut short, the whole of it in a tooltip.
    assert filters.games.sizeHint().width() < NAME_MAX + 80
    assert filters.games.toolTip().strip() == ("Long " * 30).strip()
    window.state.set_facet(Facet("all"))
    for width in (1280, 980):
        window.resize(width, 800)
        qapp.processEvents()
        # Nothing in the row is pushed past its edge; the disk's text goes first.
        assert wait_until(qapp, lambda: filters.layout().sizeHint().width() <= filters.width())
    assert window.library_view.filters.disk_text.isHidden()


def test_home_shows_the_newest_clips_and_leads_to_the_library(qapp, window):
    from vertex.ui.library.model import ClipRole
    from vertex.ui.library.state import Facet

    state, home = window.state, window.home_view
    window.topbar.tabs["home"].click()
    assert window.stack.currentWidget() is home and window.topbar.tabs["home"].isChecked()
    # The newest first, whatever the library is filtered by.
    state.set_facet(Facet("favorites"))
    newest = sorted(state.all_clips, key=lambda clip: clip.date, reverse=True)
    assert [home.model.index(row).data(ClipRole)
            for row in range(home.model.rowCount())] == newest
    assert home.grid.isVisibleTo(home) and not home.empty.isVisibleTo(home)
    assert home.all_link.text() == "All 2 clips"
    state.set_facet(Facet("all"))

    # Favorites shows up once there is one; every count follows the library.
    assert not home.favorites.isVisibleTo(home)
    state.toggle_favorite(newest[0])
    assert home.favorites.isVisibleTo(home) and home.favorites.count == "1"
    state.set_tags(state.find("Replay_2026-01-02_03-04-05.mp4"), "The Finals", ["Anna"])
    assert [name for name, _count in home.games.entries] == ["Apex Legends", "The Finals"]
    assert home.people_tile.isVisibleTo(home) and home.people.people == [("Anna", 1)]

    # A game, a person or a chip opens the library filtered by it.
    home.games.picked.emit("The Finals")
    assert window.stack.currentWidget() is window.library_view
    assert state.facet == Facet("game", "The Finals") and len(state.visible) == 1
    window.navigate("home")
    home.people.picked.emit("Anna")
    assert state.facet == Facet("person", "Anna")
    window.navigate("home")
    home.favorites.click()
    assert state.facet == Facet("favorites") and window.topbar.tabs["library"].isChecked()


def test_home_keeps_two_rows_and_its_tiles_use_the_height(qapp, window):
    """The newest clips stay two rows at any size; the tiles under them take
    the rest of the height, and the top bar's search grows rather than its
    gaps."""
    window.navigate("home")
    home, bar = window.home_view, window.topbar
    # Two clips fill one row, and never more rows than that.
    window.resize(1920, 1080)
    assert wait_until(qapp, lambda: home.grid.layout_width() > 0)
    home._fit()
    assert home.grid.rows == 1
    window.state.all_clips = window.state.all_clips * 40
    for size in ((1280, 820), (1920, 1080), (2560, 1440)):
        window.resize(*size)
        qapp.processEvents()
        home._fit()
        assert wait_until(qapp, lambda: home.grid.rows == 2)
        assert 4 <= home.grid.columns <= 6
        # The tiles under the clips share the width with no gap left over.
        tiles = home.games_tile.geometry()
        assert tiles.height() > 100 and home.storage_tile.geometry().left() > tiles.right()
    assert bar.search.width() > 400                     # at 2560 px
    window.resize(1280, 800)


def test_top_bar_switches_pages_and_searches_the_library(qapp, window):
    from PySide6.QtTest import QTest

    bar = window.topbar
    assert bar.tabs["library"].isChecked()
    assert list(bar.tabs) == ["home", "library", "settings"]
    bar.tabs["home"].click()
    assert window.stack.currentWidget() is window.home_view and bar.tabs["home"].isChecked()
    # Typing a search elsewhere takes you to the library, filtered.
    QTest.keyClicks(bar.search, "replay")
    assert window.stack.currentWidget() is window.library_view
    assert wait_until(qapp, lambda: window.state.query == "replay")
    assert len(window.state.visible) == 1
    assert window.library_view.filters.found.text() == "1 of 2 clips match"
    bar.search.clear()
    assert wait_until(qapp, lambda: len(window.state.visible) == 2)

    # Only when the bar is too narrow for everything do the tabs drop their
    # icons and the replay buffer its second line; at any width it all fits.
    for width in (980, 1280):
        window.resize(width, 800)
        qapp.processEvents()
        compact = bar.natural_width(False) > bar.width()
        assert wait_until(qapp, lambda c=compact: bar.tabs["library"].compact == c)
        assert bar.recorder.detail.isHidden() == compact
        assert bar.recorder.geometry().right() <= bar.width()
        assert bar.search.width() >= 180


def test_delete_clip(qapp, window, monkeypatch):
    state = window.state
    clip = state.find("Replay_2026-01-02_03-04-05.mp4")
    assert state.delete(clip)
    assert not os.path.exists(clip.path)
    assert len(state.visible) == 1


def test_dialogs(qapp, window, sample_clip):
    from vertex.media import probe
    from vertex.ui.dialogs.export import ExportDialog
    from vertex.ui.dialogs.tags import TagDialog

    tags = TagDialog(window, "clip", "", [], ["Apex Legends"], ["Anna"])
    tags.game.setText("apex legends")
    tags.person.setText("Ben")
    tags._save()
    assert tags.result_tags == ("Apex Legends", ["Ben"])

    info = probe.probe(sample_clip)
    clip = window.state.visible[0]
    dialog = ExportDialog(window, window.context, clip, 0.0, 3.0, info.tracks, info)
    dialog.sizes._pick("10 MB")
    assert "kbps" in dialog.detail.text()
    dialog._export()
    assert wait_until(qapp, lambda: bool(dialog.out_path), timeout=60)
    assert os.path.getsize(dialog.out_path) <= 10 * 1024 * 1024
    dialog.reject()


def test_share_renders_into_the_cache(qapp, window, sample_clip, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDrag, QGuiApplication

    from vertex.media import export, probe
    from vertex.ui.dialogs.export import ExportDialog

    info = probe.probe(sample_clip)
    clip = window.state.visible[0]
    dialog = ExportDialog(window, window.context, clip, 0.0, 3.0, info.tracks, info, share=True)
    assert dialog.export_button.text() == "Share"
    dialog._export()
    assert wait_until(qapp, lambda: bool(dialog.out_path), timeout=60)
    cache = window.context.config.resolved_cache_dir()
    assert os.path.dirname(dialog.out_path) == export.share_dir(cache)
    urls = QGuiApplication.clipboard().mimeData().urls()
    assert [url.toLocalFile() for url in urls] == [dialog.out_path]
    # The finished file drags out of the preview.
    dragged = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: dragged.append(
        [url.toLocalFile() for url in self.mimeData().urls()]) or Qt.DropAction.CopyAction)
    dialog.preview.drag()
    assert dragged == [[dialog.out_path]]
    dialog.reject()
    assert os.path.exists(dialog.out_path)    # kept until Vertex next starts
    assert export.clear_shares(cache, older_than=60) == 0
    assert export.clear_shares(cache) == 1
    assert not os.path.exists(dialog.out_path)


def _setup(qapp, tmp_path):
    from vertex.ui.main_window import MainWindow
    from vertex.ui.services import Context

    context = Context(Config())
    win = MainWindow(context)
    win.show_setup()
    view = win.first_run
    view.clip_path.set_value(str(tmp_path / "clips"))
    # Never start a real recorder from a test, wherever one is installed.
    view._autostart_touched = True
    view.rec_autostart.setChecked(False)
    return win, view


def _moments_library(folder):
    folder.mkdir()
    for name in ("THE-FINALS__2024-06-16__19-45-23.mp4", "THE-FINALS__2024-06-17__20-00-00.mp4",
                 "Apex-Legends__2026-08-11__22-14-07.mp4", "Replay_2026-03-28_05-28-25.mp4"):
        (folder / name).write_bytes(b"clip")
    return folder


def _close(win):
    if win.start_menu_job is not None:
        futures.wait([win.start_menu_job], timeout=30)    # see the window fixture
    win._quitting = True
    win.context.shutdown()


def test_first_run_writes_config(qapp, tmp_path):
    win, view = _setup(qapp, tmp_path)
    choices = view.choices
    choices.fps.setCurrentIndex(choices.fps.findData(120))
    # The clip size, as Settings shows it, follows the choices.
    minute = view.clip_size.figure.text()
    assert minute.startswith("About") and minute.endswith("per clip")
    choices.duration.setCurrentIndex(choices.duration.findData(30))
    assert view.clip_size.figure.text() != minute
    for _ in range(2):
        view._go(1)
    assert view.current() == "library"
    assert view.next_button.text() == "Open Vertex"     # starting fresh: the last step
    view._go(1)
    assert win.first_run is None
    saved = Config.load()
    assert saved.clip_path == str(tmp_path / "clips")
    assert saved.export_path == str(tmp_path / "clips" / "Vertex" / "Exports")
    assert (saved.recorder.fps, saved.recorder.replay_seconds) == (120, 30)
    assert saved.is_complete()
    assert os.path.isdir(tmp_path / "clips")
    _close(win)


def test_first_run_uses_existing_clips_where_they_are(qapp, tmp_path):
    source = _moments_library(tmp_path / "Moments")
    win, view = _setup(qapp, tmp_path)
    for _ in range(2):
        view._go(1)
    view.existing.choose()
    assert view.step_label.text() == "Step 3 of 4"
    view.source.set_value(str(source))
    assert wait_until(qapp, lambda: view.copy_plan is not None)
    assert view.source_summary.text() == "Found 4 clips."
    view._go(1)
    assert view.current() == "tags"
    assert wait_until(qapp, lambda: view.tag_plan is not None)
    view.game_fields["THE FINALS"].setText("The Finals")
    view.stray_game.setText("Deep Rock Galactic")
    view._go(1)                                        # Open Vertex
    assert win.first_run is None
    saved = Config.load()
    assert saved.clip_path == str(source)
    assert saved.export_path == str(source / "Vertex" / "Exports")
    assert not os.path.exists(tmp_path / "clips")     # the unused folder isn't made
    tags = win.context.library.tags()
    assert tags["THE-FINALS__2024-06-16__19-45-23.mp4"][0] == "The Finals"
    assert tags["Apex-Legends__2026-08-11__22-14-07.mp4"][0] == "Apex Legends"
    assert tags["Replay_2026-03-28_05-28-25.mp4"][0] == "Deep Rock Galactic"
    _close(win)


def test_first_run_copies_existing_clips(qapp, tmp_path):
    source = _moments_library(tmp_path / "Moments")
    win, view = _setup(qapp, tmp_path)
    for _ in range(2):
        view._go(1)
    view.existing.choose()
    view.copy_in.choose()
    view.source.set_value(str(source))
    assert wait_until(qapp, lambda: view.copy_plan is not None)
    assert "Copies 4 clips" in view.copy_summary.text()
    view._go(1)                                        # copies, then moves on
    assert wait_until(qapp, lambda: view.current() == "tags" and view.tag_plan is not None)
    assert view.tags_note.text() == "Copied 4 clips."
    view._go(1)
    saved = Config.load()
    assert saved.clip_path == str(tmp_path / "clips")
    assert set(os.listdir(source)) <= set(os.listdir(tmp_path / "clips"))
    assert len(os.listdir(source)) == 4                # the originals stay
    assert win.context.library.tags()["THE-FINALS__2024-06-16__19-45-23.mp4"][0] == \
        "THE FINALS"
    _close(win)


def test_first_run_finds_the_recorder(qapp, tmp_path, monkeypatch):
    from vertex.ui.main_window import MainWindow
    from vertex.ui.services import Context

    script = tmp_path / "gsr"
    script.write_text("#!/bin/sh\ncase \"$1\" in\n --version) echo 5.15.1 ;;\n"
                      " --list-capture-options) printf 'DP-1|2560x1440\\nportal\\n' ;;\n"
                      " --list-audio-devices) printf 'spotify.monitor|Monitor of Spotify\\n"
                      "headset|Headset Mic\\n' ;;\n"
                      "esac\n")
    script.chmod(0o755)
    config = Config()
    config.recorder.command = str(tmp_path / "no-such-recorder")
    monkeypatch.setattr("vertex.recorder.notifier.find", lambda: None)
    win = MainWindow(Context(Config()))
    win.show_setup(config)
    view = win.first_run
    assert wait_until(qapp, lambda: view.gsr_info is not None)
    assert not view.install.isHidden() and not view.rec_autostart.isEnabled()
    assert view.install_title.text() == "Install GPU Screen Recorder"
    # Its notifier is looked for on the same step.
    assert not view.notifier_row.isHidden() and not view.notifier_check.isHidden()
    assert view.notifier_status.text().startswith("Optional:")
    assert view.gsr_status.text() == "GPU Screen Recorder isn't installed."

    view.config.recorder.command = str(script)         # installed both; Check again
    monkeypatch.setattr("vertex.recorder.notifier.find", lambda: "/usr/bin/gsr-notify")
    view.gsr_info = None
    view.recheck_button.click()
    assert wait_until(qapp, lambda: view.gsr_info is not None)
    assert view.install.isHidden()
    assert view.notifier_path == "/usr/bin/gsr-notify" and view.notifier_check.isHidden()
    assert view.notifier_status.text() == "In-game notifications available"
    assert [m.name for m in view.choices.monitor_map.monitors] == ["DP-1"]
    assert view.choices.resolution.itemText(0) == "720p · 1280 × 720"
    assert view.rec_autostart.isEnabled() and view.rec_autostart.isChecked()
    # Each track picks its device from what the recorder can record.
    media, mic = view.tracks.devices["media"], view.tracks.devices["mic"]
    assert media.itemText(media.count() - 1) == "Spotify"
    media.setCurrentIndex(media.findData("device:spotify.monitor"))
    mic.setCurrentIndex(mic.findData("device:headset"))
    assert (view.config.recorder.media_audio, view.config.recorder.mic_audio) == \
        ("device:spotify.monitor", "device:headset")
    win._quitting = True
    win.context.shutdown()


def test_notifications_pop_up_by_kind_when_the_window_is_not_in_front(
        qapp, window, monkeypatch):
    from types import SimpleNamespace

    from vertex import notifications
    from vertex.ui.app import Commands

    context, settings = window.context, window.settings_view
    popped = []
    monkeypatch.setattr(window, "tray", SimpleNamespace(pop_up=popped.append))
    monkeypatch.setattr(window, "isActiveWindow", lambda: False)

    context.notify("clip_saved", "Clip saved", "a.mp4")
    assert window.banner.text() == "Clip saved: a.mp4"
    assert [n.kind for n in popped] == ["clip_saved"]
    context.notify("replay_started", "Replay buffer on")          # off by default
    assert window.banner.text() == "Replay buffer on"
    assert len(popped) == 1

    # The tab has a switch for every kind; Save keeps the ones changed.
    assert set(settings.notifications.switches) == set(notifications.BY_ID)
    settings.notifications.switches["replay_started"].setChecked(True)
    settings.notifications.switches["clip_saved"].setChecked(False)
    assert settings.save()
    assert Config.load().notifications == {"replay_started": True, "clip_saved": False}
    context.notify("clip_saved", "Clip saved", "b.mp4")
    context.notify("replay_started", "Replay buffer on")
    assert [n.kind for n in popped] == ["clip_saved", "replay_started"]

    # A save asked for from a shortcut, with the buffer off, says so.
    reply = Commands(window, context)._run("save-clip", {})
    assert not reply["ok"] and popped[-1].kind == "clip_not_saved"
    # With the window in front, only the bar at its bottom shows it.
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    count = len(popped)
    context.notify("replay_started", "Replay buffer on")
    assert len(popped) == count
    with pytest.raises(KeyError):
        context.notify("no_such_kind", "?")


def test_notifications_pop_up_over_games_with_gsr_notifier(qapp, window, monkeypatch):
    from types import SimpleNamespace

    from vertex.ui import theme

    context = window.context
    popped, toasts = [], []
    monkeypatch.setattr(window, "tray", SimpleNamespace(pop_up=popped.append))
    monkeypatch.setattr(window, "isActiveWindow", lambda: False)
    monkeypatch.setattr(window.over_games, "show",
                        lambda *args: toasts.append(args) or True)

    assert context.config.notify_over_games          # on by default
    context.notify("clip_saved", "Clip saved", "a.mp4")
    assert popped == [] and toasts[-1][0] == "Clip saved: a.mp4"
    assert toasts[-1][1:] == ("ok", theme.ACCENT_FILL, theme.ON_ACCENT, "replay")
    context.notify("vertex_problem", "Could not save settings", "disk full")
    assert toasts[-1][1:3] == ("error", theme.DANGER) and toasts[-1][4] == ""

    # Not installed, or it couldn't start: a desktop notification instead.
    monkeypatch.setattr(window.over_games, "show", lambda *args: False)
    context.notify("clip_saved", "Clip saved", "b.mp4")
    assert [n.body for n in popped] == ["b.mp4"]

    # Switched off in Settings.
    settings = window.settings_view
    settings.notifications.over_games.setEnabled(True)
    settings.notifications.over_games.setChecked(False)
    assert settings.save() and not Config.load().notify_over_games
    monkeypatch.setattr(window.over_games, "show",
                        lambda *args: toasts.append(args) or True)
    count = len(toasts)
    context.notify("clip_saved", "Clip saved", "c.mp4")
    assert len(toasts) == count and popped[-1].body == "c.mp4"


def test_over_games_switch_greyed_out_without_the_notifier(qapp, window, monkeypatch):
    page = window.settings_view.notifications
    monkeypatch.setattr("vertex.recorder.notifier.find", lambda: None)
    window.navigate("settings")
    assert not page.over_games.isEnabled() and not page.over_games.isChecked()
    assert not page.test_button.isEnabled()
    assert "isn't installed" in page.over_games_row.hint.text()
    # Greyed out, the saved choice stays as it was.
    assert window.settings_view.save() and Config.load().notify_over_games

    # Installed while Vertex runs: opening Settings again finds it.
    window.navigate("home")
    monkeypatch.setattr("vertex.recorder.notifier.find", lambda: "/usr/bin/gsr-notify")
    window.navigate("settings")
    assert page.over_games.isEnabled() and page.over_games.isChecked()
    assert page.test_button.isEnabled()
    assert page.over_games_row.hint.text() == "Uses GPU Screen Recorder's overlay"


def test_setup_runs_again_from_settings(qapp, window, monkeypatch):
    from vertex.ui import main_window
    from vertex.ui.widgets import ChoiceDialog

    context = window.context
    before = context.config.to_dict()
    answers = [None]
    monkeypatch.setattr(ChoiceDialog, "ask", classmethod(lambda *a, **k: answers.pop(0)))
    window.navigate("settings")
    window.settings_view.show_page("import")

    # Declined at the warning: nothing happens.
    window.settings_view.setup_requested.emit()
    assert window.first_run is None

    # Cancelled part-way: back on the tab, settings as they were.
    answers.append("run")
    window.settings_view.setup_requested.emit()
    setup = window.first_run
    assert setup is not None and setup.again
    assert setup.clip_path.value() == context.config.clip_path
    setup._go(1)
    setup.cancelled.emit()
    assert window.first_run is None
    assert window.settings_view.tabs.current == "import"
    assert context.config.to_dict() == before

    # Finished: the change applies to the running Vertex, which isn't started again.
    monkeypatch.setattr(main_window.MainWindow, "start_services",
                        lambda *_a, **_k: pytest.fail("services started twice"))
    answers.append("run")
    window.settings_view.setup_requested.emit()
    setup = window.first_run
    setup.choices.duration.setCurrentIndex(setup.choices.duration.findData(120))
    for _ in range(len(setup.steps)):
        setup._go(1)
    assert window.first_run is None
    assert context.config.recorder.replay_seconds == 120
    assert Config.load().recorder.replay_seconds == 120
    assert context.config.clip_path == before["clip_path"]


def test_text_dialogs_grow_to_fit_their_wrapped_text(qapp, window):
    from PySide6.QtWidgets import QLabel

    from vertex.ui.widgets import ChoiceDialog

    dialog = ChoiceDialog(window, "Clear the cache", "Clear the cache?",
                          "Thumbnails and previews are deleted and made again as you browse.",
                          [("Clear the cache", "clear", "danger")])
    dialog.show()
    detail = next(lab for lab in dialog.findChildren(QLabel) if "browse" in lab.text())

    def fits():
        qapp.processEvents()
        return detail.height() >= detail.heightForWidth(detail.width())
    assert fits()
    # Its text grows after it was sized (another font, another screen)…
    detail.setStyleSheet("font-size: 18pt;")
    assert wait_until(qapp, fits, 3)
    # …or it is narrower than planned.
    dialog.resize(dialog.minimumWidth(), 10)
    assert wait_until(qapp, fits, 3)
    dialog.reject()


def test_enter_takes_what_a_dialog_asks_for(qapp, window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from vertex.ui.widgets import ChoiceDialog

    for choices, wanted in (([("Move to Trash", "delete", "danger")], "delete"),
                            ([("Discard", "discard", ""), ("Apply", "apply", "primary")],
                             "apply")):
        dialog = ChoiceDialog(window, "Delete clip", "Delete it?", "", choices)
        dialog.show()
        qapp.processEvents()
        QTest.keyClick(dialog.focusWidget() or dialog, Qt.Key.Key_Return)
        assert dialog.result_value == wanted


def test_reset_confirms_by_typing_the_word(qapp, window):
    from vertex.ui.settings.reset import TypeToConfirm

    dialog = TypeToConfirm(window, "Reset", "Reset?", ["Everything."], "Clips stay.",
                           "RESET", "Reset settings")
    assert not dialog.confirm.isEnabled()
    dialog.field.setText("reset")
    assert not dialog.confirm.isEnabled()
    dialog.field.setText("RESET")
    assert dialog.confirm.isEnabled()
    dialog.reject()


def test_reset_library_and_cache(qapp, window, monkeypatch):
    import glob

    from vertex.core import storage

    monkeypatch.setattr(storage, "send2trash", None)
    context, state = window.context, window.state
    clip = state.find("Replay_2026-01-02_03-04-05.mp4")
    state.set_tags(clip, "The Finals", ["Anna"])
    data = context.config.resolved_data_dir()

    window.reset("library")
    assert state.tags_of(clip) == ("", [])
    assert ("Apex Legends", 1) in state.games()       # read from its file name again
    assert glob.glob(f"{data}/library.db.*.bak")
    assert "kept as" in window.settings_view.banner.text()

    thumbs = os.path.join(context.config.resolved_cache_dir(), "thumbnails")
    open(os.path.join(thumbs, "old.jpg"), "w").close()
    window.reset("cache")
    assert not os.path.exists(os.path.join(thumbs, "old.jpg"))
    assert window.settings_view.banner.text().startswith("Cache cleared")


def test_reset_settings_then_setup(qapp, window, monkeypatch, tmp_path):
    from vertex import paths
    from vertex.core import storage
    from vertex.ui import main_window

    monkeypatch.setattr(storage, "send2trash", None)
    context = window.context
    recorder_settings = context.config.recorder
    context.config.recorder.replay_seconds = 120
    context.config.notifications = {"replay_started": True}
    context.save_config()

    window.reset("settings")
    assert not paths.config_path().exists()
    assert glob_backups(paths.config_path())
    assert context.config == Config() and context.config.recorder is recorder_settings
    setup = window.first_run
    assert setup is not None and not setup.again

    monkeypatch.setattr(main_window.MainWindow, "start_services",
                        lambda *_a, **_k: pytest.fail("services started twice"))
    setup.clip_path.set_value(str(tmp_path / "new clips"))
    for _ in range(len(setup.steps)):
        setup._go(1)
    assert window.first_run is None
    saved = Config.load()
    assert saved.is_complete() and saved.clip_path == str(tmp_path / "new clips")
    assert saved.notifications == {} and saved.recorder.replay_seconds == 60


def glob_backups(path) -> list[str]:
    import glob

    return glob.glob(f"{path}.*.bak")


def test_tray_opens_pages_and_drives_the_replay_buffer(qapp, window):
    from vertex.ui.tray import Tray

    context = window.context
    tray = Tray(window, context)
    texts = [action.text() for action in tray.contextMenu().actions() if action.text()]
    assert texts == ["Show Vertex", "Open Library", "Start replay buffer", "Save clip",
                     "Save the last 30 seconds", "Quit"]
    window.navigate("home")
    next(a for a in tray.contextMenu().actions() if a.text() == "Open Library").trigger()
    assert window.stack.currentWidget() is window.library_view
    assert not tray.save_action.isEnabled()          # the buffer isn't running
    tray._recorder_state("running", "")
    assert tray.save_action.isEnabled() and tray.replay_action.text() == "Stop replay buffer"
    tray.deleteLater()


def test_control_api_answers_and_publishes(qapp, window):
    import queue

    from vertex.ui.control import Commands

    context = window.context
    commands = Commands(window, context)

    def call(command, args=None):
        box = []
        commands._handle(command, args or {}, box)
        return box[0]

    assert call("frobnicate")["error"] == "unknown_command"
    for gone in ("sonar", "volume", "mute", "device", "devices"):
        assert call(gone, {"action": "up"})["error"] == "unknown_command"
    assert call("save-clip", {"seconds": 45})["error"] == "bad_argument"
    assert call("save-clip")["error"] == "replay_off"
    assert call("replay", {"action": "sideways"})["error"] == "bad_argument"
    assert call("ping")["data"]["api"] == 2
    assert call("state")["data"] == {"api": 2, "replay": {
        "state": "stopped", "running": False, "seconds": 60}}

    # Subscribers hear the notifications, and the state once it changes.
    events = commands.subscribers.add()
    context.notify("clip_saved", "Clip saved", "a.mp4")
    context.config.recorder.replay_seconds = 120
    context.config_changed.emit()
    seen = []

    def heard(predicate):
        while True:
            try:
                seen.append(events.get_nowait())
            except queue.Empty:
                break
        return any(predicate(event) for event in seen)
    assert wait_until(qapp, lambda: heard(
        lambda e: e["event"] == "state" and e["data"]["replay"]["seconds"] == 120))
    assert heard(lambda e: e["event"] == "notice" and e["data"]["kind"] == "clip_saved")
    commands.subscribers.remove(events)


def test_control_commands(qapp, window):
    from vertex.ui.app import Commands

    commands = Commands(window, window.context)
    assert commands._run("replay", {"action": "status"})["ok"]
    assert not commands._run("save-clip", {})["ok"]          # buffer not running
    assert not commands._run("bogus", {})["ok"]


def _has_gl_display():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and \
        QApplication.platformName() not in ("offscreen", "minimal")


@pytest.mark.skipif(not ctypes.util.find_library("mpv"), reason="libmpv not installed")
def test_editor_plays_mixes_and_trims(qapp, window):
    if not _has_gl_display():
        pytest.skip("the editor needs an OpenGL display (run under xvfb-run)")
    clip = next(c for c in window.state.visible if c.name.startswith("Apex"))
    window.open_clip(clip)
    editor = window.editor
    assert [t.label for t in editor.tracks] == ["Game", "Chat", "Microphone"]
    assert wait_until(qapp, lambda: editor.position > 0.2, timeout=15)
    assert wait_until(qapp, lambda: len(editor.timeline.waves) == 3, timeout=15)
    editor.rows[-1].slider.setValue(40)
    editor.trim_start, editor.trim_end = 0.5, 2.5
    editor._trim_committed()
    editor._save()
    edit = window.context.library.get_edit(clip.name)
    assert edit.trim_start == 0.5 and edit.mix_for("Vertex Mic").volume == 0.4
    # Playback volume: only what is heard, kept for the next clip.
    editor.volume.setValue(250)
    assert editor.player_widget.player.volume == 250 and editor.volume_readout.text() == "250%"
    editor.volume_button.click()
    assert editor.player_widget.player.volume == 0
    editor.volume_button.click()
    assert editor.volume.value() == 250 and window.context.config.playback_volume == 250
    assert window.context.library.get_edit(clip.name).mix_for("Vertex Mic").volume == 0.4
    editor._start_trim("copy")
    assert wait_until(qapp, lambda: editor._trim_job is None, timeout=30)
    assert any("(trimmed)" in name for name in os.listdir(os.path.dirname(clip.path)))
    window.navigate("library")
    assert window.editor is None


@pytest.mark.skipif(not ctypes.util.find_library("mpv"), reason="libmpv not installed")
def test_editor_opens_without_the_window_vanishing(qapp, window):
    if not _has_gl_display():
        pytest.skip("the editor needs an OpenGL display (run under xvfb-run)")
    window.show()
    qapp.processEvents()
    hidden = []

    class Watch(QObject):
        def eventFilter(self, obj, event):
            if obj is window and event.type() == QEvent.Type.Hide:
                hidden.append(True)
            return False

    watch = Watch()
    window.installEventFilter(watch)
    window.open_clip(next(c for c in window.state.visible if c.name.startswith("Apex")))
    assert wait_until(qapp, lambda: window.editor.position > 0.2, timeout=15)
    window.removeEventFilter(watch)
    assert not hidden
    window.navigate("library")


@pytest.mark.skipif(not ctypes.util.find_library("mpv"), reason="libmpv not installed")
def test_editor_holds_playback_while_scrubbing_and_mixes_live(qapp, window):
    if not _has_gl_display():
        pytest.skip("the editor needs an OpenGL display (run under xvfb-run)")
    window.open_clip(next(c for c in window.state.visible if c.name.startswith("Apex")))
    editor = window.editor
    player = editor.player_widget.player
    player["ao"] = "null"                   # there may be no sound card here
    player.command("ao-reload")
    assert wait_until(qapp, lambda: player.audio_params is not None, timeout=15)
    assert player.audio_params["channel-count"] == 6     # three tracks, side by side
    assert wait_until(qapp, lambda: editor.position > 0.2, timeout=15)

    seeks = []
    player.observe_property("seeking", lambda _n, value: value and seeks.append(value))
    for value in range(100, 20, -5):        # a slider being dragged
        editor.rows[0].slider.setValue(value)
        qapp.processEvents()
    wait_until(qapp, lambda: False, timeout=0.5)
    assert not seeks and not player.pause
    assert editor.tracks[0].volume == 0.25
    # The live path, not the fallback: the command reaches the track's volume.
    player.command("af-command", "mix", "volume", "0.25", "volume@v0")

    editor.timeline.scrub_started.emit()
    editor.timeline.seek_requested.emit(1.0)
    assert wait_until(qapp, lambda: player.pause, timeout=2)
    wait_until(qapp, lambda: False, timeout=0.6)
    assert abs(editor.position - 1.0) < 0.05          # the playhead stays put
    editor.timeline.scrub_finished.emit()
    assert wait_until(qapp, lambda: editor.position > 1.2, timeout=5)

    player.pause = True                                # paused stays paused
    editor.timeline.scrub_started.emit()
    editor.timeline.seek_requested.emit(0.5)
    editor.timeline.scrub_finished.emit()
    wait_until(qapp, lambda: False, timeout=0.6)
    assert player.pause and abs(editor.position - 0.5) < 0.05
    window.navigate("library")


def test_editor_controls_grow_with_the_window(qapp):
    from vertex.ui.editor.timeline import LANE_H, Timeline
    from vertex.ui.editor.view import SCALE_MAX, editor_scale

    assert editor_scale(980, 700) == 1.0
    assert editor_scale(1280, 820) == 1.0
    assert editor_scale(2560, 1380) == SCALE_MAX
    # A wide but short window keeps the room for the video.
    assert editor_scale(2560, 820) == 1.0
    timeline = Timeline()
    timeline.set_lanes([("#336699", False)])
    small = timeline.height()
    timeline.set_scale(1.5)
    assert timeline.lane_h == round(LANE_H * 1.5)
    assert timeline.height() > small


def test_settings_apply_at_once_and_recording_waits_for_apply(qapp, window, monkeypatch):
    from vertex.ui.widgets import ChoiceDialog

    window.navigate("settings")
    settings = window.settings_view
    assert settings.apply_button.isHidden()
    # A switch is saved as it is flipped.
    settings.close_to_tray.setChecked(not settings.close_to_tray.isChecked())
    assert Config.load().close_to_tray == settings.close_to_tray.isChecked()
    settings.rec_autostart.setChecked(not settings.rec_autostart.isChecked())
    assert Config.load().recorder.autostart == settings.rec_autostart.isChecked()
    assert settings.apply_button.isHidden()
    # A folder once the field is left.
    folder = str(window.context.config.resolved_export_dir()) + "-2"
    settings.export_path.set_value(folder)
    settings.export_path.edit.editingFinished.emit()
    assert Config.load().export_path == folder
    # What restarts the replay buffer waits for Apply.
    settings.duration.setCurrentIndex(settings.duration.findData(90))
    assert not settings.apply_button.isHidden()
    assert Config.load().recorder.replay_seconds != 90
    asked = []
    monkeypatch.setattr(ChoiceDialog, "ask",
                        lambda *args, **kwargs: asked.append(args[2]) or "apply")
    window.navigate("library")
    assert asked == ["Apply the recording changes?"]
    assert Config.load().recorder.replay_seconds == 90
    window.navigate("settings")
    assert settings.apply_button.isHidden()




def test_first_run_copies_clips_from_folders_inside_but_not_the_left_out_ones(qapp, tmp_path):
    source = tmp_path / "Medal"
    for folder, name in (("", "top.mp4"), ("First Light", "a.mp4"), ("Exports", "b.mp4")):
        (source / folder).mkdir(parents=True, exist_ok=True)
        (source / folder / name).write_bytes(b"x" * 10)
    win, view = _setup(qapp, tmp_path)
    for _ in range(2):
        view._go(1)
    view.existing.choose()
    view.source.set_value(str(source))
    assert wait_until(qapp, lambda: view.copy_plan is not None)
    # Where they are, the ones in folders inside wouldn't show.
    assert "2 of them are in folders inside it" in view.source_summary.text()
    assert view.folders.isHidden()
    view.copy_in.choose()
    assert view.source_summary.text() == "Found 3 clips."
    assert not view.folders.isHidden()
    assert list(view.folders.boxes) == ["", "Exports", "First Light"]
    assert "Copies 3 clips" in view.copy_summary.text()
    view.folders.boxes["Exports"].setChecked(False)
    assert "Copies 2 clips" in view.copy_summary.text()
    view._go(1)
    assert wait_until(qapp, lambda: view.current() == "tags" and view.tag_plan is not None)
    assert sorted(os.listdir(tmp_path / "clips")) == ["a.mp4", "top.mp4"]
    _close(win)


def test_the_import_dialog_lists_the_folders_it_found(qapp, tmp_path):
    from vertex.ui.dialogs.importing import CopyClipsDialog

    source = tmp_path / "Moments"
    for folder in ("Apex", "Exports"):
        (source / folder).mkdir(parents=True)
        (source / folder / f"{folder}.mp4").write_bytes(b"x" * 10)
    dialog = CopyClipsDialog(None, str(tmp_path / "clips"), str(source))
    assert list(dialog.folders.boxes) == ["Apex", "Exports"]
    assert dialog.summary.text().startswith("2 clips to copy")
    dialog.folders.boxes["Exports"].setChecked(False)
    assert dialog.summary.text().startswith("1 clip to copy")
    dialog.folders.boxes["Apex"].setChecked(False)
    assert dialog.summary.text() == "Nothing new to copy."
    assert not dialog.copy_button.isEnabled()
    assert dialog.folders.every.text() == "Select all"
    dialog.folders.every.click()
    assert dialog.summary.text().startswith("2 clips to copy")
    assert dialog.folders.every.text() == "Deselect all"
    dialog.folders.every.click()
    assert dialog.summary.text() == "Nothing new to copy."
    dialog.deleteLater()


def test_the_icon_ink_follows_the_windows_taskbar_not_the_apps(qapp, monkeypatch):
    from vertex import system
    from vertex.ui import icons

    monkeypatch.setattr(system, "light_desktop", lambda: False)    # dark taskbar
    assert icons.desktop_ink() == icons.desktop_ink_outside_app() == "light"
    monkeypatch.setattr(system, "light_desktop", lambda: True)
    assert icons.desktop_ink() == "dark"


def test_first_run_learns_medal_names_and_reads_them(qapp, tmp_path):
    source = tmp_path / "Medal"
    source.mkdir()
    for name in ("MedalTVFirstLight20260817235610725.mp4",
                 "MedalTV007FirstLight20260818101500001.mp4"):
        (source / name).write_bytes(b"x")
    win, view = _setup(qapp, tmp_path)
    for _ in range(2):
        view._go(1)
    view.existing.choose()
    view.source.set_value(str(source))
    assert wait_until(qapp, lambda: view.copy_plan is not None)
    view._go(1)
    assert wait_until(qapp, lambda: view.current() == "tags" and view.tag_plan is not None)
    assert not view.names.isHidden() and len(view.tag_plan.strays) == 2
    assert not view.sources.adding.isHidden()          # nothing listed yet: teaching opens
    view.sources.teacher.choose("Medal")
    assert view.sources.teacher.preview_title.text() == "What Vertex reads: 2 of 2 clips"
    assert wait_until(qapp, lambda: view.tag_plan is not None and
                      set(view.tag_plan.games) == {"First Light", "007 First Light"})
    view._go(1)
    assert win.first_run is None
    assert [p.app for p in win.context.config.patterns()] == ["Medal"]
    assert Config.load().name_patterns[0]["app"] == "Medal"
    tags = win.context.library.tags()
    assert tags["MedalTVFirstLight20260817235610725.mp4"][0] == "First Light"
    naming.use_patterns([])
    _close(win)


def test_name_sources_list_apps_and_teach_from_what_none_reads(qapp):
    from vertex.core.name_patterns import PRESETS
    from vertex.ui.name_teacher import NameSources

    def preset(app):
        return next(p.pattern for p in PRESETS if p.app.startswith(app))

    names = ["MedalTVValorant20260809184502117.mp4", "MedalTVApex20260810101500001.mp4",
             "Minecraft 2024-05-18 20-32-45.mp4", "clip_final_edit.mp4",
             "Replay_2026-03-28_05-28-25.mp4"]
    sources = NameSources()
    changed = []
    sources.changed.connect(lambda: changed.append(True))
    sources.set_patterns([preset("Medal")])
    sources.set_names(names)
    assert sources.adding.isHidden()                  # something listed: not opened by itself
    assert sources._rows[0].count.text() == "reads 2 clips"
    assert sources.status.text() == "2 of 5 clips aren't read yet"
    # Adding the next app teaches from what's left.
    sources.add_button.click()
    assert sources.teacher.names == ["Minecraft 2024-05-18 20-32-45.mp4", "clip_final_edit.mp4"]
    assert not sources.add_to_list.isEnabled()
    sources.teacher.choose("Xbox Game Bar")
    assert sources.draft().app == "Xbox Game Bar"
    sources.add_to_list.click()
    assert [p.app for p in sources.patterns()] == ["Medal", "Xbox Game Bar"]
    assert sources.adding.isHidden() and changed == [True]
    assert sources.status.text() == "1 of 5 clips aren't read yet"
    assert sources.unread() == ["clip_final_edit.mp4"]
    # Dragged to the top, it is tried first; removed, its clips are unread again.
    second = sources._rows[1]
    sources._drag(second, sources._rows[0].mapToGlobal(sources._rows[0].rect().topLeft()).y())
    sources._dropped()
    assert [p.app for p in sources.patterns()] == ["Xbox Game Bar", "Medal"]
    sources._remove(sources._rows[0])
    assert [p.app for p in sources.patterns()] == ["Medal"] and len(changed) == 3
    assert sources.status.text() == "2 of 5 clips aren't read yet"
    sources.deleteLater()


def test_the_name_teacher_learns_from_marked_parts(qapp):
    from vertex.ui.name_teacher import NameTeacher

    teacher = NameTeacher()
    teacher.set_names(["Clip_Valorant_16-06-2024.mp4", "Clip_Apex_01-02-2025.mp4"])
    teacher.choose("Something else")
    assert teacher.sample.text() == "Clip_Apex_01-02-2025.mp4"
    teacher._set_sample("Clip_Valorant_16-06-2024.mp4")

    def mark(text, kind):
        teacher.sample.setSelection(teacher.sample.text().index(text), len(text))
        teacher._mark(kind)

    mark("Valorant", "game")
    assert teacher.pattern() is not None
    mark("16-06-2024", "date")
    assert teacher.format.isHidden()                # only day-month-year fits 16-06
    assert teacher.pattern().template == "Clip_{game}_{date:DD-MM-YYYY}"
    assert teacher.preview_title.text() == "What Vertex reads: 2 of 2 clips"
    mark("Clip", "date")
    assert "can't read" in teacher.note.text()
    teacher._clear_marks()
    teacher._mark("game")
    assert "Select a part" in teacher.note.text()
    teacher.deleteLater()


def test_ignoring_the_app_name_before_the_game_leaves_it_out(qapp):
    from vertex.ui.name_teacher import NameTeacher

    names = ["MedalTVAssassinsCreedII20260102140204766.mp4",
             "MedalTVHalo20260103090000001.mp4"]
    teacher = NameTeacher()
    teacher.set_names(names)
    teacher.choose("Something else")
    teacher._set_sample(names[0])
    for text, kind in (("MedalTV", "skip"), ("AssassinsCreedII", "game"), ("20260102", "date"),
                       ("1402", "time"), ("04766", "skip")):
        teacher.sample.setSelection(teacher.sample.text().index(text), len(text))
        teacher.mark_buttons[kind].click()
    teacher.split_words.setChecked(True)
    pattern = teacher.pattern()
    assert [pattern.read(name).game for name in names] == ["Assassins Creed II", "Halo"]
    assert teacher.preview_title.text() == "What Vertex reads: 2 of 2 clips"
    teacher.deleteLater()


def test_a_marked_part_survives_the_field_losing_focus(qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtWidgets import QApplication

    from vertex.ui.name_teacher import NameTeacher

    teacher = NameTeacher()
    teacher.set_names(["Clip_Valorant_16-06-2024.mp4"])
    teacher.choose("Something else")
    teacher.sample.setSelection(teacher.sample.text().index("Valorant"), len("Valorant"))
    # What a click on a button does to the field: Qt takes its selection away.
    QApplication.sendEvent(teacher.sample, QFocusEvent(QEvent.Type.FocusOut,
                                                       Qt.FocusReason.MouseFocusReason))
    assert not teacher.sample.hasSelectedText()
    teacher.mark_buttons["game"].click()
    assert teacher.pattern().template == "Clip_{game}_16-06-2024"
    teacher.deleteLater()


def _hotkeys_page(monkeypatch):
    from vertex import hotkeys
    from vertex.config import Config
    from vertex.ui.services import Context
    from vertex.ui.settings.shortcuts import ShortcutsPage

    monkeypatch.setattr(hotkeys, "AVAILABLE", True)
    context = Context(Config())
    return context, ShortcutsPage(context).hotkeys


def test_a_hotkey_is_recorded_with_the_keys_held_shown_live(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from vertex.config import Config

    context, page = _hotkeys_page(monkeypatch)
    paused = []
    recorder = page.rows["save_clip"].recorder
    recorder.recording.connect(paused.append)
    assert recorder.caps.parts == () and recorder.hotkey is None
    recorder.listen()
    assert paused == [True]
    QTest.keyPress(recorder, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
    QTest.keyPress(recorder, Qt.Key.Key_Alt,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert recorder.caps.parts == ("Ctrl", "Alt")
    QTest.keyRelease(recorder, Qt.Key.Key_Alt)
    assert recorder.caps.parts == ("Ctrl",)
    QTest.keyPress(recorder, Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier)
    assert "Add Ctrl, Alt or Win" in page.rows["save_clip"].note.text()
    assert recorder.listening
    QTest.keyPress(recorder, Qt.Key.Key_F9,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert not recorder.listening and paused == [True, False]
    assert Config.load().hotkeys == {"save_clip": "Ctrl+Alt+F9"}
    assert recorder.caps.parts == ("Ctrl", "Alt", "F9")

    recorder.listen()
    QTest.keyPress(recorder, Qt.Key.Key_Escape)
    assert not recorder.listening and context.config.hotkeys == {"save_clip": "Ctrl+Alt+F9"}
    page.rows["save_clip"].clear.click()
    assert context.config.hotkeys == {}


def test_keys_another_action_has_move_and_can_come_back(qapp, monkeypatch):
    from vertex import hotkeys

    context, page = _hotkeys_page(monkeypatch)
    keys = hotkeys.parse("Ctrl+Alt+F9")
    page._chosen("save_clip", keys)
    page._chosen("replay", keys)
    assert context.config.hotkeys == {"replay": "Ctrl+Alt+F9"}
    assert "Taken from “Save a clip”" in page.rows["replay"].note.text()
    page.rows["replay"].note.linkActivated.emit("undo")
    assert context.config.hotkeys == {"save_clip": "Ctrl+Alt+F9"}
    assert page.rows["replay"].note.isHidden()


def test_keys_another_program_holds_go_back_or_say_so(qapp, monkeypatch):
    from vertex import hotkeys

    context, page = _hotkeys_page(monkeypatch)
    page._chosen("show", hotkeys.parse("Ctrl+Alt+V"))
    context.hotkeys._got_result(set())
    page._chosen("show", hotkeys.parse("Win+Alt+G"))
    context.hotkeys._got_result({"show"})         # Windows refused the new keys
    assert context.config.hotkeys == {"show": "Ctrl+Alt+V"}
    assert "Another program already uses Win + Alt + G. Your old keys are kept." in \
        page.rows["show"].note.text()
    context.hotkeys._got_result(set())
    assert "Your old keys are kept" in page.rows["show"].note.text()
    context.hotkeys._got_result({"show"})         # held elsewhere since, say at start
    assert page.rows["show"].recorder.warn
    assert "does nothing for now" in page.rows["show"].note.text()
    context.hotkeys._got_result(set())
    assert not page.rows["show"].recorder.warn and page.rows["show"].note.isHidden()


def test_a_hotkey_runs_its_action(qapp, window):
    from vertex.ui.control import Commands

    commands = Commands(window, window.context)
    ran = []
    commands._run = lambda command, args: ran.append((command, args)) or {"ok": True}
    window.context.config.hotkey_last_seconds = 60
    for action in ("save_clip", "save_last", "replay", "show"):
        window.context.hotkeys.pressed.emit(action)
    assert ran == [("save-clip", {}), ("save-clip", {"seconds": 60}),
                   ("replay", {"action": "toggle"}), ("show", {})]
