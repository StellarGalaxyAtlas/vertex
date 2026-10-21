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

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from vertex.config import Config
from vertex.core import naming

from fake_pactl import FakePactl

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
def fake_audio(monkeypatch):
    fake = FakePactl(sinks=("hw_headset",), sources=("hw_mic",))
    monkeypatch.setattr("vertex.ui.services.Pactl", lambda: fake)
    return fake


@pytest.fixture
def no_sonar(monkeypatch):
    """A system without Sonar, as Windows is. Asked for before `window`."""
    from vertex import platform

    monkeypatch.setattr(platform.here(), "SONAR", False)


@pytest.fixture
def library_dir(tmp_path, sample_clip):
    clips = tmp_path / "clips"
    clips.mkdir()
    # copy2 keeps the file's date, so the clips don't count as still being written.
    shutil.copy2(sample_clip, clips / os.path.basename(sample_clip))
    shutil.copy2(sample_clip, clips / "Replay_2026-01-02_03-04-05.mp4")
    return clips


@pytest.fixture
def window(qapp, tmp_path, library_dir, fake_audio):
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
    model = window.library_view.model
    tip = model.index(state.visible.index(clip)).data(Qt.ItemDataRole.ToolTipRole)
    assert tip == f"{clip.name}\nWith Anna\n{clip.size_human}"
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
    assert level == "ok" and text.startswith("Copied") and callable(click)
    exported = [url.toLocalFile() for url in QGuiApplication.clipboard().mimeData().urls()]
    assert len(exported) == 1 and exported[0].startswith(str(tmp_path / "exports"))
    assert abs(probe.probe(exported[0]).duration - 2.0) < 0.6
    # Several at once: all of them on the clipboard together.
    notices.clear()
    view.quick_export(*state.visible[:2])
    assert wait_until(qapp, lambda: notices and notices[-1][1] != "info", 60), notices
    assert notices[-1][0].startswith("Copied 2 clips")
    assert len(QGuiApplication.clipboard().mimeData().urls()) == 2
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
    from vertex.platform import linux

    assert wait_until(qapp, lambda: linux.desktop_file().exists())
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
    for page in ("sonar", "settings", "library"):
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
        strip = window.sonar_view.strips["media"]
        assert spooky["MEDIA"] in strip.slider.styleSheet()
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
    # 11 Mbps of video and four AAC tracks, for a minute.
    assert settings.clip_size.text() == "About 83 MB per clip"
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
    from PySide6.QtWidgets import QCheckBox

    from vertex.recorder import gsr

    window.navigate("settings")
    settings = window.settings_view
    settings.show_page("recording")
    assert wait_until(qapp, lambda: "not installed" in settings.gsr_status.text())
    # Sonar's devices by default; nothing about recording on the Sonar page.
    rec = settings.collect().recorder
    assert (rec.game_audio, rec.chat_audio, rec.mic_audio) == (
        "device:vertex_game.monitor", "device:vertex_chat.monitor", "device:vertex_mic")
    assert not window.sonar_view.findChildren(QCheckBox)

    devices = [("default_output", "Default output"), ("default_input", "Default input"),
               ("alsa_output.usb-headset.monitor", "Monitor of Arctis Nova Pro"),
               ("alsa_input.usb-headset", "Arctis Nova Pro Mono")]
    info = gsr.GsrInfo("gsr", True, (5, 15, 1), "5.15.1")
    window.context.recorder.info = info          # names tracks in the preview
    settings._show_recorder((info, [], devices))
    qapp.processEvents()

    def texts(widget):
        return [widget.itemText(i) for i in range(widget.count())]

    # Sonar is off here: its channels say what records instead.
    assert texts(settings.chat_audio) == [
        "None", "Default output", "Vertex Game (Sonar off: default output)",
        "Vertex Chat (Sonar off: default output)", "Vertex Media (Sonar off: default output)",
        "Arctis Nova Pro"]
    assert texts(settings.mic_audio) == [
        "None", "Default microphone", "Vertex Mic (Sonar off: default microphone)",
        "Arctis Nova Pro Mono"]
    preview = settings.preview.toPlainText()
    assert "name:Vertex Chat|default_output" in preview
    assert "name:Vertex Mic|default_input" in preview

    settings.chat_audio.setCurrentIndex(settings.chat_audio.findData(""))
    settings.mic_audio.setCurrentIndex(settings.mic_audio.findData("device:alsa_input.usb-headset"))
    assert "Vertex Chat" not in settings.preview.toPlainText()
    assert "name:Vertex Mic|device:alsa_input.usb-headset" in settings.preview.toPlainText()
    assert settings.save()
    saved = Config.load().recorder
    assert (saved.chat_audio, saved.mic_audio) == ("", "device:alsa_input.usb-headset")


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

    # Sonar's devices coming or going switches tracks to or from their stand-ins.
    from vertex.audio.sonar import SonarStatus
    recorder._sonar_active = False
    for active in (True, False):
        states.clear()
        context.sonar.status_changed.emit(SonarStatus(active=active))
        assert wait_until(qapp, lambda: recorder.phase == "running" and len(states) >= 2)
        assert states == ["restarting", "running"]
    # Nothing changed: no restart.
    states.clear()
    context.sonar.status_changed.emit(SonarStatus(active=False))
    qapp.processEvents()
    assert states == []

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
    # The recorder's own state turns first; the controller hears of it later.
    assert wait_until(qapp, lambda: recorder.phase == "failed" and states)
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


def test_sonar_page_drives_the_fake_server(qapp, window, fake_audio):
    window.navigate("sonar")
    window.sonar_view.toggle.setChecked(True)
    assert wait_until(qapp, lambda: any(s.name == "vertex_game" for s in fake_audio.sinks_))
    assert wait_until(qapp, lambda: window.context.sonar.status.active)
    fake_audio.play("Spotify")
    window.context.sonar.route("spotify", "media")
    assert wait_until(qapp, lambda: fake_audio.inputs_[-1].sink ==
                      fake_audio._sink("vertex_media").index)
    assert wait_until(qapp, lambda: Config.load().sonar.app_rules == {"spotify": "media"})
    window.sonar_view.toggle.setChecked(False)
    assert wait_until(qapp, lambda: not any(s.name.startswith("vertex_")
                                            for s in fake_audio.sinks_))


def test_sonar_lists_apps_under_channels_and_routes_drops(qapp, window, fake_audio):
    window.navigate("sonar")
    view = window.sonar_view
    window.context.sonar.set_enabled(True)
    assert wait_until(qapp, lambda: window.context.sonar.status.active)
    fake_audio.play("Spotify")                         # lands on the default channel
    fake_audio.play("Overwatch", sink="hw_headset")    # picked the headset itself
    fake_audio.record("Discord", "vertex_mic")
    window.context.sonar.refresh_streams()

    def keys(channel_id):
        layout = view.strips[channel_id].apps
        return [layout.itemAt(i).widget().key for i in range(layout.count())
                if hasattr(layout.itemAt(i).widget(), "key")]

    assert wait_until(qapp, lambda: keys("game") == ["spotify"])
    assert keys("mic") == ["discord"]
    assert view.unrouted.isVisibleTo(view)
    assert view.unrouted_flow.itemAt(0).widget().key == "overwatch"

    view.route("spotify", "media")                     # what a drop onto Media does
    assert wait_until(qapp, lambda: keys("media") == ["spotify"])
    assert keys("game") == []
    assert wait_until(qapp, lambda: Config.load().sonar.app_rules.get("spotify") == "media")

    # Held back while dragging, applied once the drag ends.
    view.drag_started()
    view.route("overwatch", "game")
    qapp.processEvents()
    view.drag_finished()
    assert wait_until(qapp, lambda: "overwatch" in keys("game"))
    assert wait_until(qapp, lambda: not view.unrouted.isVisibleTo(view))

    view.route("spotify", None)                        # "Use the default channel"
    assert wait_until(qapp, lambda: "spotify" in keys("game"))
    assert "spotify" not in window.context.config.sonar.app_rules

    # An app that isn't playing isn't shown, though its channel is kept.
    view.route("steam", "chat")
    assert wait_until(qapp, lambda: window.context.config.sonar.app_rules.get("steam"))
    window.context.sonar.refresh_streams()
    qapp.processEvents()
    assert "steam" not in keys("chat") and keys("chat") == []


def test_app_left_half_behind_after_a_drop_heals(qapp, window, fake_audio):
    """Reported bug: a dropped app showed on both channels."""
    window.navigate("sonar")
    view = window.sonar_view
    window.context.sonar.set_enabled(True)
    assert wait_until(qapp, lambda: window.context.sonar.status.active)
    fake_audio.play("Discord", binary="Discord")
    second = fake_audio.play("Discord", binary="Discord")
    fake_audio.refuse_moves[second.index] = 1

    def keys(channel_id):
        layout = view.strips[channel_id].apps
        return [layout.itemAt(i).widget().key for i in range(layout.count())
                if hasattr(layout.itemAt(i).widget(), "key")]

    view.route("discord", "chat")
    assert wait_until(qapp, lambda: keys("chat") == ["discord"] and keys("game") == [])


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
    the rest of the height and use it (the mixer turns into faders), and the
    top bar's search grows rather than its gaps."""
    window.navigate("home")
    home, bar = window.home_view, window.topbar
    # Two clips fill one row, and never more rows than that.
    window.resize(1920, 1080)
    assert wait_until(qapp, lambda: home.grid.layout_width() > 0)
    home._fit()
    assert home.grid.rows == 1
    window.state.all_clips = window.state.all_clips * 40
    grooves = []
    for size, faders in (((1280, 820), False), ((1920, 1080), True), ((2560, 1440), True)):
        window.resize(*size)
        qapp.processEvents()
        home._fit()
        assert wait_until(qapp, lambda f=faders: home.grid.rows == 2 and
                          home.mixer.faders.isVisible() == f)
        assert home.mixer.rows.isVisible() != faders
        assert 4 <= home.grid.columns <= 6
        if faders:
            fader = home.faders["game"]
            grooves.append(fader._groove)
            assert fader.slider.width() == fader._groove + 12
    # The faders widen with the room they get.
    assert 8 <= grooves[0] < grooves[1] <= 22
    # A fader set here keeps the row in step, for when the window shrinks.
    home.faders["media"].slider.setValue(30)
    assert home.channels["media"].slider.value() == 30
    assert bar.search.width() > 400                     # at 2560 px
    window.resize(1280, 800)


def test_home_mixer_sets_a_channel_and_follows_it(qapp, window):
    from vertex.audio.sonar import ChannelStatus, SonarStatus

    window.navigate("home")
    row = window.home_view.channels["chat"]
    row.slider.setValue(40)
    assert window.context.config.sonar.channel("chat").volume == 0.4
    assert row.value.text() == "40%"
    row.mute.setChecked(True)            # the mixer is greyed out while Sonar is off
    assert window.context.config.sonar.channel("chat").muted
    # Changed elsewhere (the Sonar page, the system mixer): Home follows.
    from vertex.audio import channels
    status = SonarStatus(available=True, active=True, channels={
        "chat": ChannelStatus(channels.BY_ID["chat"], present=True, volume=0.7, muted=False)})
    window.context.sonar.status_changed.emit(status)
    assert row.slider.value() == 70 and not row.mute.isChecked()


def test_top_bar_switches_pages_and_searches_the_library(qapp, window):
    from PySide6.QtTest import QTest

    bar = window.topbar
    assert bar.tabs["library"].isChecked()
    bar.tabs["sonar"].click()
    assert window.stack.currentWidget() is window.sonar_view and bar.tabs["sonar"].isChecked()
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


def test_new_apps_channel_is_chosen_in_the_header(qapp, window, fake_audio):
    window.navigate("sonar")
    view = window.sonar_view
    combo = view.default_channel
    assert combo.currentData() == "game"
    combo.setCurrentIndex(combo.findData("chat"))
    combo.activated.emit(combo.currentIndex())
    assert wait_until(qapp, lambda: Config.load().sonar.default_channel == "chat")


def test_channels_wrap_two_by_two_when_the_window_is_narrow(qapp, window, fake_audio):
    window.navigate("sonar")
    window.show()
    grid = window.sonar_view.strips_host
    window.resize(1600, 860)
    assert wait_until(qapp, lambda: grid._per_row == 4)
    window.resize(980, 860)
    assert wait_until(qapp, lambda: grid._per_row in (2, 4))
    # Whichever it chose, nothing hangs off the right of the page.
    page = window.sonar_view.scroll
    assert wait_until(qapp, lambda: not page.horizontalScrollBar().isVisible())
    for column in window.sonar_view.strips.values():
        assert column.geometry().right() <= grid.width()


def test_each_channel_shows_and_picks_its_device(qapp, window, fake_audio):
    fake_audio.add_sink("hw_speakers", props={"device.description": "Speakers"})
    window.navigate("sonar")
    view = window.sonar_view
    view.toggle.setChecked(True)
    sonar = window.context.config.sonar
    assert wait_until(qapp, lambda: view.controller.status.active and view._outputs)
    strips = view.strips
    assert set(strips) == {"game", "chat", "media", "mic"}
    assert wait_until(qapp, lambda: strips["chat"].current_device == "hw_headset")
    assert strips["mic"].current_device == "hw_mic" and strips["mic"].link is None

    # Linked: a device picked for one channel is every channel's.
    popup = view.choose_device("chat")
    assert set(popup.buttons) == {"hw_headset", "hw_speakers"}
    popup.pick("hw_speakers")
    assert wait_until(qapp, lambda: all(strips[c].current_device == "hw_speakers"
                                        for c in ("game", "chat", "media")))
    assert view.link_line.linked
    # Picking a device is all the list offers.
    assert not any(isinstance(b, QPushButton) and b.text() == "Device manager"
                   for b in popup.findChildren(QPushButton))
    # Unlinked: each its own.
    view.toggle_link("chat")
    assert wait_until(qapp, lambda: not sonar.linked and not view.link_line.linked)
    view.choose_device("media").pick("hw_headset")
    assert wait_until(qapp, lambda: strips["media"].current_device == "hw_headset")
    assert strips["game"].current_device == "hw_speakers"
    assert view.subtitle.text() == "On"
    # Linking from Media: everything plays through Media's device.
    view.toggle_link("media")
    assert wait_until(qapp, lambda: sonar.linked and all(
        strips[c].current_device == "hw_headset" for c in ("game", "chat", "media")))
    assert wait_until(qapp, lambda: view.output_panel.picked_note.isVisibleTo(view))


def test_device_manager_orders_the_devices(qapp, window, fake_audio):
    fake_audio.add_sink("hw_speakers", props={"device.description": "Speakers"})
    window.navigate("sonar")
    view = window.sonar_view
    view.toggle.setChecked(True)
    sonar = window.context.config.sonar
    panel = view.output_panel
    assert wait_until(qapp, lambda: panel.priority.names() == ["hw_headset", "hw_speakers"]
                      and panel.now.full_text() == "hw_headset")
    assert sonar.output_priority == ["hw_headset", "hw_speakers"]    # learned and saved
    assert panel.picked_note.isHidden()
    assert view.mic_panel.priority.names() == ["hw_mic"]

    # Reordered: Auto plays through the new top device.
    view.device_order_changed("output", ["hw_speakers", "hw_headset"], [])
    assert wait_until(qapp, lambda: view.controller.status.output == "hw_speakers")
    assert Config.load().sonar.output_priority == ["hw_speakers", "hw_headset"]
    # Excluded: never picked by itself, but still offered by hand.
    view.device_order_changed("output", ["hw_headset"], ["hw_speakers"])
    assert wait_until(qapp, lambda: view.controller.status.output == "hw_headset")
    assert wait_until(qapp, lambda: panel.excluded.names() == ["hw_speakers"])
    popup = view.choose_device("game")
    assert list(popup.buttons) == ["hw_headset", "hw_speakers"]
    popup.close()

    # Disconnected devices: hidden unless asked for, and kept in their place.
    fake_audio.remove_device("hw_speakers")
    view.controller.refresh_devices()
    assert wait_until(qapp, lambda: panel.excluded.names() == [])
    view.show_disconnected.setChecked(True)
    assert panel.excluded.names() == ["hw_speakers"]
    view.show_disconnected.setChecked(False)
    assert sonar.output_excluded == ["hw_speakers"]

    # Picked on a channel: used for now, said under the device in use, and
    # the list keeps its order.
    fake_audio.add_sink("hw_speakers", props={"device.description": "Speakers"})
    view.controller.refresh_devices()
    view.controller.set_channel_output("game", "hw_speakers")
    assert wait_until(qapp, lambda: view.controller.status.output == "hw_speakers")
    assert wait_until(qapp, lambda: not panel.picked_note.isHidden())
    assert (sonar.output_priority, sonar.output_excluded) == (["hw_headset"], ["hw_speakers"])
    assert panel.format.text().startswith("In use")


def test_channels_also_play_through_a_second_device(qapp, window, fake_audio):
    fake_audio.add_sink("hw_speakers", props={"device.description": "Speakers"})
    window.navigate("sonar")
    view = window.sonar_view
    view.toggle.setChecked(True)
    sonar = window.context.config.sonar
    strips = view.strips
    combo = view.output_panel.second
    assert wait_until(qapp, lambda: combo.findData("hw_speakers") >= 0)
    assert strips["game"].also_row.isHidden()            # no second device yet

    # It offers the device manager's list, less the device in use.
    assert wait_until(qapp, lambda: [combo.itemData(i) for i in range(combo.count())]
                      == ["", "hw_speakers"])
    combo.setCurrentIndex(combo.findData("hw_speakers"))
    combo.activated.emit(combo.currentIndex())
    assert wait_until(qapp, lambda: view.controller.status.channels["chat"].also)
    assert not strips["game"].also_row.isHidden() and strips["mic"].also_row.isHidden()
    assert strips["chat"].also_label.full_text() == "Also on Speakers"
    assert view.subtitle.text().endswith("+ Speakers")
    assert Config.load().sonar.second_output == "hw_speakers"

    strips["chat"].also.setChecked(False)                 # Chat stays in the headset
    assert wait_until(qapp, lambda: not view.controller.status.channels["chat"].also)
    assert view.controller.status.channels["game"].also
    assert sonar.channel("chat").also_second is False
    assert view.subtitle.text().endswith("+ Speakers")

    # An excluded device isn't offered; one excluded after being set stays shown.
    fake_audio.add_sink("hw_hdmi", props={"device.description": "HDMI"})
    view.controller.refresh_devices()
    assert wait_until(qapp, lambda: combo.findData("hw_hdmi") >= 0)
    view.device_order_changed("output", ["hw_headset"], ["hw_speakers", "hw_hdmi"])
    assert wait_until(qapp, lambda: combo.findData("hw_hdmi") < 0)
    assert combo.currentData() == "hw_speakers"


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
    assert dialog.progress.isHidden()        # only while exporting
    dialog._export()
    assert not dialog.progress.isHidden()
    assert wait_until(qapp, lambda: bool(dialog.out_path), timeout=60)
    assert os.path.getsize(dialog.out_path) <= 10 * 1024 * 1024
    assert dialog.progress.isHidden()
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
    view.sonar_enabled.setChecked(False)
    # Never start a real recorder from a test, wherever one is installed.
    view._autostart_touched = True
    view.rec_autostart.setChecked(False)
    return win, view


def test_without_sonar_no_part_of_it_shows(qapp, tmp_path, no_sonar, window):
    from vertex.ui.main_window import MainWindow
    from vertex.ui.services import Context

    assert window.sonar_view is None and window.home_view.sonar_tile is None
    assert "sonar" not in window.topbar.tabs
    settings = window.settings_view
    assert not settings.tag_from_game.isVisibleTo(settings)
    settings.tracks.show_devices([], window.context.config.recorder)
    assert [settings.chat_audio.itemText(i) for i in range(settings.chat_audio.count())] == [
        "None", "Default output"]
    # Setup skips the Sonar step.
    win = MainWindow(Context(Config()))
    win.show_setup()
    assert win.first_run.steps[:2] == ["folders", "moments"]
    assert "sonar" not in win.first_run.pages
    _close(win)


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


def test_first_run_writes_config(qapp, tmp_path, fake_audio):
    win, view = _setup(qapp, tmp_path)
    choices = view.choices
    choices.fps.setCurrentIndex(choices.fps.findData(120))
    # The clip size, as Settings shows it, follows the choices.
    minute = view.clip_size.figure.text()
    assert minute.startswith("About") and minute.endswith("per clip")
    choices.duration.setCurrentIndex(choices.duration.findData(30))
    assert view.clip_size.figure.text() != minute
    for _ in range(3):
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


def test_first_run_uses_existing_clips_where_they_are(qapp, tmp_path, fake_audio):
    source = _moments_library(tmp_path / "Moments")
    win, view = _setup(qapp, tmp_path)
    for _ in range(3):
        view._go(1)
    view.existing.choose()
    assert view.step_label.text() == "Step 4 of 5"
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


def test_first_run_copies_existing_clips(qapp, tmp_path, fake_audio):
    source = _moments_library(tmp_path / "Moments")
    win, view = _setup(qapp, tmp_path)
    for _ in range(3):
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


def test_first_run_finds_the_recorder(qapp, tmp_path, fake_audio, monkeypatch):
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
    # Each track picks its device: Sonar's channels, then what the recorder
    # can record.
    media, mic = view.tracks.devices["media"], view.tracks.devices["mic"]
    assert media.currentData() == "device:vertex_media.monitor"
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
    from vertex.audio.sonar import SonarStatus
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
    # Sonar switching device.
    context.config.sonar.device_names["hw_b"] = "USB headset"
    context.sonar._got_status(SonarStatus(active=True, output="hw_a", mic="mic_a"))
    context.sonar._got_status(SonarStatus(active=True, output="hw_b", mic="mic_a"))
    assert (popped[-1].kind, popped[-1].body) == ("output_changed", "USB headset")

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
    sonar_settings = context.config.sonar
    context.config.recorder.replay_seconds = 120
    context.config.notifications = {"replay_started": True}
    context.save_config()

    window.reset("settings")
    assert not paths.config_path().exists()
    assert glob_backups(paths.config_path())
    assert context.config == Config() and context.config.sonar is sonar_settings
    setup = window.first_run
    assert setup is not None and not setup.again

    monkeypatch.setattr(main_window.MainWindow, "start_services",
                        lambda *_a, **_k: pytest.fail("services started twice"))
    setup.clip_path.set_value(str(tmp_path / "new clips"))
    setup.sonar_enabled.setChecked(False)
    for _ in range(len(setup.steps)):
        setup._go(1)
    assert window.first_run is None
    saved = Config.load()
    assert saved.is_complete() and saved.clip_path == str(tmp_path / "new clips")
    assert saved.notifications == {} and saved.recorder.replay_seconds == 60


def test_reset_settings_takes_sonar_down_first(qapp, window, fake_audio, monkeypatch):
    from vertex.core import storage

    monkeypatch.setattr(storage, "send2trash", None)
    context = window.context
    context.sonar.set_enabled(True)
    assert wait_until(qapp, lambda: context.sonar.status.active)

    def vertex_sinks():
        return [sink.name for sink in fake_audio.sinks() if sink.name.startswith("vertex_")]
    assert vertex_sinks()
    window.reset("settings")
    assert wait_until(qapp, lambda: window.first_run is not None)
    assert not context.config.sonar.enabled
    assert not vertex_sinks()


def glob_backups(path) -> list[str]:
    import glob

    return glob.glob(f"{path}.*.bak")


def test_tray_opens_pages_and_switches_devices(qapp, window, fake_audio):
    from vertex.ui.tray import Tray

    context = window.context
    tray = Tray(window, context)

    def texts(menu):
        return [(action.text(), action.isChecked()) for action in menu.actions()]

    assert not tray.output_menu.menuAction().isEnabled()     # Sonar off
    window.navigate("home")
    next(a for a in tray.contextMenu().actions() if a.text() == "Open Sonar").trigger()
    assert window.stack.currentWidget() is window.sonar_view

    fake_audio.add_sink("hw_speakers", props={"device.description": "Speakers"})
    fake_audio.add_sink("hw_hdmi", props={"device.description": "HDMI"})
    context.sonar.set_enabled(True)
    assert wait_until(qapp, lambda: context.sonar.status.active
                      and len(context.sonar.outputs) == 3)
    context.config.sonar.output_excluded = ["hw_hdmi"]
    context.config_changed.emit()
    assert wait_until(qapp, lambda: tray.output_menu.menuAction().isEnabled())
    current = context.sonar.status.output
    outputs = texts(tray.output_menu)
    assert sorted(outputs) == sorted([("hw_headset", current == "hw_headset"),
                                      ("Speakers", current == "hw_speakers")])
    assert [text for text, _on in texts(tray.mic_menu)] == ["hw_mic"]

    other = "Speakers" if current != "hw_speakers" else "hw_headset"
    next(a for a in tray.output_menu.actions() if a.text() == other).trigger()
    assert wait_until(qapp, lambda: context.sonar.status.output != current)
    assert wait_until(qapp, lambda: dict(texts(tray.output_menu))[other])
    tray.deleteLater()


def test_control_api_drives_sonar(qapp, window, fake_audio):
    import queue

    from vertex.ui.control import Commands

    context = window.context
    commands = Commands(window, context)

    def call(command, args=None):
        box = []
        commands._handle(command, args or {}, box)
        return box[0]

    def chat_volume():
        return call("state")["data"]["sonar"]["channels"]["chat"]["volume"]

    assert call("volume", {"channel": "chat", "action": "up"})["error"] == "sonar_off"
    assert call("frobnicate")["error"] == "unknown_command"
    assert call("volume", {"channel": "aux", "action": "up"})["error"] == "bad_argument"
    assert call("save-clip", {"seconds": 45})["error"] == "bad_argument"
    assert call("save-clip")["error"] == "replay_off"
    assert call("ping")["data"]["api"] == 1

    context.sonar.set_enabled(True)
    assert wait_until(qapp, lambda: context.sonar.status.active)
    events = commands.subscribers.add()

    reply = call("volume", {"channel": "chat", "action": "set", "value": 40})
    assert reply["ok"] and reply["data"]["volume"] == 40
    assert wait_until(qapp, lambda: chat_volume() == 40)
    assert call("volume", {"channel": "chat", "action": "up"})["data"]["volume"] == 45
    assert call("mute", {"channel": "mic"})["data"]["muted"] is True
    assert wait_until(qapp, lambda: call("state")["data"]["sonar"]["channels"]["mic"]["muted"])

    # Next device: the other connected output, for now; then back again.
    fake_audio.add_sink("hw_speakers", props={"device.description": "Speakers"})
    context.sonar.refresh_devices()
    assert wait_until(qapp, lambda: len(context.sonar.outputs) == 2)
    reply = call("device", {"action": "next"})
    assert reply["ok"]
    assert wait_until(qapp, lambda: context.sonar.status.output == "hw_speakers")
    assert context.sonar.status.output_picked and call("state")["data"]["sonar"][
        "output_picked"]
    assert context.config.sonar.output_priority == ["hw_headset", "hw_speakers"]
    call("device", {"action": "next"})
    assert wait_until(qapp, lambda: context.sonar.status.output == "hw_headset")
    assert call("device", {"action": "next", "channel": "mic"})["error"] == "no_device"

    # Microphones: down the device manager's list, top to bottom and round again,
    # leaving the list's order as it is.
    fake_audio.add_source("hw_webcam", props={"device.description": "Webcam"})
    fake_audio.add_source("hw_usb_mic", props={"device.description": "USB mic"})
    context.sonar.refresh_devices()
    assert wait_until(qapp, lambda: len(context.sonar.inputs) == 3)
    sonar_config = context.config.sonar
    sonar_config.mic_priority = ["hw_mic", "hw_webcam", "hw_usb_mic"]
    context.sonar._got_status(context.sonar.sonar.status())
    assert context.sonar.status.mic == "hw_mic"
    for expected in ("hw_webcam", "hw_usb_mic", "hw_mic"):
        assert call("device", {"action": "next", "channel": "mic"})["ok"]
        assert wait_until(qapp, lambda e=expected: context.sonar.status.mic == e)
    assert sonar_config.mic_priority == ["hw_mic", "hw_webcam", "hw_usb_mic"]

    # A named microphone, for now; the list names them all.
    mics = call("devices")["data"]["mics"]
    assert [(m["name"], m["connected"]) for m in mics] == [
        ("hw_mic", True), ("hw_webcam", True), ("hw_usb_mic", True)]
    reply = call("device", {"action": "set", "channel": "mic", "name": "hw_usb_mic"})
    assert reply["ok"] and reply["data"]["devices"]["mic"]["name"] == "hw_usb_mic"
    assert wait_until(qapp, lambda: context.sonar.status.mic == "hw_usb_mic")
    assert sonar_config.mic_priority == ["hw_mic", "hw_webcam", "hw_usb_mic"]
    assert call("device", {"action": "set", "channel": "mic",
                           "name": "hw_gone"})["error"] == "no_device"
    assert call("device", {"action": "set", "channel": "mic"})["error"] == "bad_argument"

    # Subscribers heard the changes, and the notifications.
    context.notify("clip_saved", "Clip saved", "a.mp4")
    seen = []

    def heard(predicate):
        while True:
            try:
                seen.append(events.get_nowait())
            except queue.Empty:
                break
        return any(predicate(event) for event in seen)
    assert wait_until(qapp, lambda: heard(
        lambda e: e["event"] == "state" and
        e["data"]["sonar"]["channels"]["mic"]["muted"]))
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
    assert [t.label for t in editor.tracks] == ["Game", "Chat", "Mic"]
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


def test_sonar_stands_tall_on_a_big_window(qapp, window, monkeypatch):
    from PySide6.QtCore import Qt

    from vertex.audio import levels

    started = []
    monkeypatch.setattr(levels.Levels, "start", lambda self, sources: started.append(sources))
    window.resize(1280, 820)
    window.navigate("sonar")
    qapp.processEvents()
    view = window.sonar_view
    assert not view.big and not view.strips["game"].tall
    window.resize(2560, 1380)
    assert wait_until(qapp, lambda: view.big)
    game = view.strips["game"]
    assert game.tall and game.slider.orientation() == Qt.Orientation.Vertical
    # The devices sit right of the channels, which take the height.
    assert view.manager.geometry().left() > game.geometry().right()
    assert game.height() > 600
    # The fader shares the height with the apps, and the devices line up.
    assert game.apps_area.height() > 150
    assert len({strip.device.mapTo(view, QPoint(0, 0)).y()
                for strip in view.strips.values()}) == 1
    # Sonar's page has no meters of its own.
    assert window.context.levels._wanted == set()
    window.resize(1280, 820)
    assert wait_until(qapp, lambda: not view.big)
    assert not game.tall
    window.navigate("home")
    assert window.context.levels._wanted == {"home"}
    if window.context.sonar.status.active:
        assert wait_until(qapp, lambda: started)
        assert started[0]["game"] == "vertex_game.monitor"
        assert started[0]["mic"] == "vertex_mic"
    window.context.levels.levels.emit({"chat": 0.5})
    assert window.home_view.channels["chat"].meter.level == 0.5
    assert window.home_view.faders["chat"].meter.level == 0.5


def test_first_run_copies_clips_from_folders_inside_but_not_the_left_out_ones(qapp, tmp_path,
                                                                              fake_audio):
    source = tmp_path / "Medal"
    for folder, name in (("", "top.mp4"), ("First Light", "a.mp4"), ("Exports", "b.mp4")):
        (source / folder).mkdir(parents=True, exist_ok=True)
        (source / folder / name).write_bytes(b"x" * 10)
    win, view = _setup(qapp, tmp_path)
    for _ in range(3):
        view._go(1)
    view.existing.choose()
    view.source.set_value(str(source))
    assert wait_until(qapp, lambda: view.copy_plan is not None)
    # Where they are, the ones in folders inside wouldn't show.
    assert "2 of them are in subfolders" in view.source_summary.text()
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


def test_first_run_learns_medal_names_and_reads_them(qapp, tmp_path, fake_audio):
    source = tmp_path / "Medal"
    source.mkdir()
    for name in ("MedalTVFirstLight20260817235610725.mp4",
                 "MedalTV007FirstLight20260818101500001.mp4"):
        (source / name).write_bytes(b"x")
    win, view = _setup(qapp, tmp_path)
    for _ in range(3):
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


def test_renaming_a_game_retags_its_clips_and_new_ones(qapp, window):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest

    from vertex.ui.dialogs.tags import RenameGameDialog
    from vertex.ui.library.state import Facet

    state, context = window.state, window.context
    clip = state.find("Replay_2026-01-02_03-04-05.mp4")
    state.set_tags(clip, "Heroes of the Storm(Retail)", [])
    state.set_facet(Facet("game", "Heroes of the Storm(Retail)"))
    filters = window.library_view.filters
    filters._open("game")
    menu = filters.menu
    # F2 on the game picked in the menu renames it.
    menu.list.setCurrentRow(next(row for row in range(menu.list.count())
                                 if menu.list.item(row).text().startswith("Heroes")))
    seen = {}

    def rename():
        dialog = next(w for w in qapp.topLevelWidgets()
                      if isinstance(w, RenameGameDialog) and w.isVisible())
        seen["typed"] = dialog.name.text()
        dialog.name.setText("apex legends")
        seen["hint"] = dialog.hint.text()
        dialog.name.setText("Heroes of the Storm")
        QTest.keyClick(dialog.name, Qt.Key.Key_Return)
    QTimer.singleShot(0, rename)
    QTest.keyClick(menu.find, Qt.Key.Key_F2)
    assert seen == {"typed": "Heroes of the Storm(Retail)",
                    "hint": "Merges with Apex Legends (1 clip)"}
    assert state.tags_of(state.find(clip.name))[0] == "Heroes of the Storm"
    assert state.facet == Facet("game", "Heroes of the Storm")
    assert context.config.game_names == {"Heroes of the Storm(Retail)": "Heroes of the Storm"}
    assert context.library.tag_recorded("new.mp4", "Heroes of the Storm (Retail)") == \
        "Heroes of the Storm"

    # Settings lists it, and forgets it.
    settings = window.settings_view
    window.navigate("settings")
    settings.show_page("import")
    assert len(settings.game_names._rows) == 1 and settings.game_names.empty.isHidden()
    settings._forget_game_name("Heroes of the Storm(Retail)")
    assert context.config.game_names == {} and not settings.game_names.empty.isHidden()


def test_a_saved_clip_gets_each_tracks_recording_volume(qapp, window, library_dir,
                                                         monkeypatch):
    from vertex.media import track_volume

    applied = []
    real_apply = track_volume.apply

    def apply(path, volumes):
        applied.append(volumes)
        return real_apply(path, volumes)

    recorder = window.context.recorder
    saved = []
    recorder.saved.connect(saved.append)
    clip = str(library_dir / "Replay_2026-01-02_03-04-05.mp4")
    size = os.path.getsize(clip)
    recorder._volumes = [100, 100, 100]
    recorder._on_saved(clip)
    assert saved == [clip] and os.path.getsize(clip) == size      # nothing to set
    recorder._volumes = [60, 100, 100]
    monkeypatch.setattr(track_volume, "apply", apply)
    recorder._on_saved(clip)
    assert wait_until(qapp, lambda: len(saved) == 2)
    assert applied == [{0: 60}] and saved[-1] == clip and os.path.getsize(clip) != size


def test_a_saved_clip_takes_the_game_channel_and_is_named_after_it(qapp, window,
                                                                    library_dir):
    import time

    context = window.context
    name = "Desktop-Capture__2026-10-20__21-00-00.mp4"
    shutil.copy2(library_dir / "Replay_2026-01-02_03-04-05.mp4", library_dir / name)
    context.library.autotag_games([name])         # as the file appeared
    context.recorder._game_hint = (time.monotonic(), "Heroes of the Storm", "channel")
    saved = []
    context.recorder.saved.connect(saved.append)
    context.recorder._on_saved(str(library_dir / name))
    wait_until(qapp, lambda: saved)
    renamed = "Heroes-of-the-Storm__2026-10-20__21-00-00.mp4"
    assert saved == [str(library_dir / renamed)]
    assert not (library_dir / name).exists()
    assert context.library.get_edit(renamed).game == "Heroes of the Storm"
    assert name not in context.library.tags()
    assert window.banner.text() == "Clip saved: It's in your library"

    # Without a game it keeps its name; a name taken gets a number.
    context.recorder._on_saved(str(library_dir / "Replay_2026-01-02_03-04-05.mp4"))
    assert saved[-1].endswith("Replay_2026-01-02_03-04-05.mp4")
    shutil.copy2(library_dir / renamed, library_dir / "Replay_2026-10-20_21-00-00.mp4")
    context.recorder._game_hint = (time.monotonic(), "Heroes of the Storm", "channel")
    context.recorder._on_saved(str(library_dir / "Replay_2026-10-20_21-00-00.mp4"))
    wait_until(qapp, lambda: len(saved) == 3)
    assert saved[-1].endswith("Heroes-of-the-Storm__2026-10-20__21-00-00_2.mp4")


def test_settings_review_tags_from_file_names(qapp, window, library_dir, sample_clip):
    from PySide6.QtCore import QTimer

    from vertex.core.name_patterns import PRESETS
    from vertex.ui.settings.reread import RereadDialog

    medal = ["MedalTVHelldivers220260817235610725.mp4",
             "MedalTVValorant20260809184502117.mp4"]
    for name in medal:
        shutil.copy2(sample_clip, library_dir / name)
    context, settings = window.context, window.settings_view
    context.library.set_tags(medal[0], "Helldivers", [])
    context.library.set_tags(medal[1], "Ranked night", [])
    context.config.name_patterns = [PRESETS[0].pattern.to_dict()]
    window.navigate("settings")
    settings.show_page("import")
    line = settings.reread
    assert wait_until(qapp, lambda: any(g.game == "Valorant" for g in line.groups))
    assert line.isVisibleTo(settings)
    assert line.text.text().startswith("2 clips are tagged differently from their file names")

    def answer():
        dialog = next(w for w in qapp.topLevelWidgets()
                      if isinstance(w, RereadDialog) and w.isVisible())
        cards = {card.group.game: card for card in dialog.cards}
        assert cards["Helldivers 2"].use.text() == "Tag it Helldivers 2"
        assert cards["Valorant"].keep.text() == "Keep Ranked night"
        cards["Helldivers 2"].use.click()
        cards["Valorant"].keep.click()
        assert all(not card.group.game for card in dialog.cards)
        dialog.done_button.click()
    QTimer.singleShot(0, answer)
    line.button.click()
    tags = context.library.tags()
    assert tags[medal[0]][0] == "Helldivers 2" and tags[medal[1]][0] == "Ranked night"
    assert context.config.kept_tags == [["Ranked night", "Valorant"]]
    # Kept is remembered: Valorant isn't asked about again.
    assert wait_until(qapp, lambda: not any(g.game for g in line.groups))

def test_each_track_has_a_recording_volume(qapp):
    from vertex.config import RecorderConfig
    from vertex.ui.settings.tracks import TrackTable

    table = TrackTable()
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


def test_tray_opens_pages_and_drives_the_replay_buffer(qapp, no_sonar, window):
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


def test_control_api_answers_and_publishes(qapp, no_sonar, window):
    import queue

    from vertex.ui.control import Commands

    context = window.context
    commands = Commands(window, context)

    def call(command, args=None):
        box = []
        commands._handle(command, args or {}, box)
        return box[0]

    from vertex import control

    assert window.sonar_view is None and context.sonar is None
    assert call("frobnicate")["error"] == "unknown_command"
    for command, args in (("sonar", {"action": "status"}), ("devices", {}),
                          ("volume", {"channel": "game", "action": "up"}),
                          ("mute", {"channel": "mic", "action": "toggle"}),
                          ("device", {"action": "next"})):
        assert call(command, args)["error"] == "sonar_off"
    assert call("save-clip", {"seconds": 45})["error"] == "bad_argument"
    assert call("save-clip")["error"] == "replay_off"
    assert call("replay", {"action": "sideways"})["error"] == "bad_argument"
    assert call("ping")["data"]["api"] == control.API_VERSION
    assert call("state")["data"] == {"api": control.API_VERSION, "replay": {
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


def test_the_icon_ink_follows_the_windows_taskbar_not_the_apps(qapp, monkeypatch):
    from vertex import platform
    from vertex.ui import icons

    monkeypatch.setattr(platform.here(), "light_desktop", lambda: False)    # dark taskbar
    assert icons.desktop_ink() == icons.desktop_ink_outside_app() == "light"
    monkeypatch.setattr(platform.here(), "light_desktop", lambda: True)
    assert icons.desktop_ink() == "dark"


def _hotkeys_page(monkeypatch):
    from vertex import hotkeys
    from vertex.config import Config
    from vertex.ui.services import Context
    from vertex.ui.settings.shortcuts import ShortcutsPage

    monkeypatch.setattr(hotkeys, "AVAILABLE", True)
    context = Context(Config())
    page = ShortcutsPage(context)
    page.hotkeys.owner = page        # its widgets live as long as the page
    return context, page.hotkeys


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


def test_a_saved_clip_is_tagged_with_the_fullscreen_game(qapp, window, monkeypatch):
    from types import SimpleNamespace

    from vertex import platform
    from vertex.platform import windows as windows_platform

    context, library = window.context, window.context.library
    recorder = context.recorder
    monkeypatch.setattr(recorder, "recorder", SimpleNamespace(running=True,
                                                              save=lambda _seconds: None,
                                                              stop=lambda timeout: None))
    monkeypatch.setattr(platform, "WINDOWS", True)
    context.rename_game("HeroesOfTheStorm_x64", "Heroes of the Storm")
    windows = [("", r"C:\Games\HeroesOfTheStorm_x64.exe"), ("", ""), None]
    asked = []
    monkeypatch.setattr(windows_platform, "fullscreen_app",
                        lambda: asked.append(1) or windows.pop(0))
    hints = []
    real_got = recorder._got_fullscreen
    monkeypatch.setattr(recorder, "_got_fullscreen",
                        lambda window: (real_got(window), hints.append(window)))

    for count, clip in enumerate(("a.mp4", "b.mp4", "c.mp4"), 1):
        recorder.save()
        assert wait_until(qapp, lambda count=count: len(hints) == count)
        recorder._on_saved(f"/clips/{clip}")
    games = {name: game for name, (game, _people) in library.tags().items()}
    # Nothing fullscreen is the desktop; Vertex in front can't tell.
    assert games.get("a.mp4") == "Heroes of the Storm"
    assert games.get("b.mp4") == "Desktop"
    assert not games.get("c.mp4")
    assert context.config.game_names == {"HeroesOfTheStorm_x64": "Heroes of the Storm"}



def test_the_commands_open_while_there_is_room_beside_the_hotkeys(qapp, monkeypatch):
    from vertex import hotkeys
    from vertex.config import Config
    from vertex.ui.services import Context
    from vertex.ui.settings.shortcuts import ShortcutsPage

    monkeypatch.setattr(hotkeys, "AVAILABLE", True)
    page = ShortcutsPage(Context(Config()))
    columns = page.columns
    columns.resize(columns.WIDE + 100, 600)
    columns.show()
    qapp.processEvents()
    assert not page.commands.isHidden()
    columns.resize(columns.WIDE - 100, 600)
    qapp.processEvents()
    assert page.commands.isHidden()
    columns.close()


@pytest.mark.skipif(not ctypes.util.find_library("mpv"), reason="libmpv not installed")
def test_the_editor_steps_through_the_clips_in_the_librarys_order(qapp, window):
    if not _has_gl_display():
        pytest.skip("the editor needs an OpenGL display (run under xvfb-run)")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    first, second = window.state.visible[:2]
    window.open_clip(first)
    editor = window.editor
    assert not editor.previous_button.isEnabled() and editor.next_button.isEnabled()
    QTest.keyClick(editor, Qt.Key.Key_PageDown)
    assert window.editor is not editor and window.editor.clip.name == second.name
    assert window.editor.previous_button.isEnabled()
    assert not window.editor.next_button.isEnabled()
    window.editor.previous_button.click()
    assert window.editor.clip.name == first.name
    # Back still goes where the first clip was opened from.
    window.editor.back.emit()
    assert window.editor is None and window.stack.currentWidget() is window.library_view


def test_library_picks_several_clips_and_acts_on_them_at_once(qapp, window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from vertex.ui.dialogs.tags import TagDialog
    from vertex.ui.widgets import ChoiceDialog

    view, state = window.library_view, window.state
    window.navigate("library")
    first, second = state.visible
    state.set_tags(first, "Apex Legends", ["Anna"])
    grid, bar = view.grid, view.selection_bar
    assert view.top.currentWidget() is view.filters
    # Ctrl-click picks a card instead of opening it; the bar takes the filters' place.
    opened = []
    view.open_clip.connect(opened.append)
    centre = grid.visualRect(view.model.index(0)).center()
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier, centre)
    assert view.picked() == [first] and not opened
    assert view.top.currentWidget() is bar and bar.count.text() == "1 selected"
    # While some are picked, a plain click picks too.
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0),
                     grid.visualRect(view.model.index(1)).center())
    assert view.picked() == [first, second] and not opened
    QTest.keyClick(grid, Qt.Key.Key_Escape)
    assert not view.picked() and view.top.currentWidget() is view.filters
    QTest.keyClick(grid, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert bar.count.text() == "2 selected"

    bar.buttons["favorite"].click()
    assert {first.name, second.name} <= state.favorites
    assert bar.buttons["favorite"].toolTip() == "Unfavorite"
    bar.buttons["favorite"].click()
    assert not state.favorites & {first.name, second.name}

    monkeypatch.setattr(TagDialog, "ask", classmethod(lambda *a, **k: ("The Finals", [])))
    bar.buttons["game"].click()
    assert state.tags_of(first) == ("The Finals", ["Anna"])
    assert state.tags_of(second)[0] == "The Finals"
    monkeypatch.setattr(TagDialog, "ask", classmethod(lambda *a, **k: ("", ["Ben", "anna"])))
    bar.buttons["people"].click()
    assert state.tags_of(first) == ("The Finals", ["Anna", "Ben"])
    assert state.tags_of(second)[1] == ["Ben", "anna"]

    monkeypatch.setattr(ChoiceDialog, "ask", classmethod(lambda *a, **k: "delete"))
    QTest.keyClick(grid, Qt.Key.Key_Delete)
    assert not state.visible and not view.selection
    assert view.top.currentWidget() is view.filters
