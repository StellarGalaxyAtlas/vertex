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

from PySide6.QtWidgets import QApplication

from vertex.config import Config

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


def test_rail_groups_fold_and_keep_the_filter_in_view(qapp, window):
    from vertex.ui.library.state import Facet

    state, rail = window.state, window.rail
    state.set_tags(state.find("Replay_2026-01-02_03-04-05.mp4"), "The Finals", ["Anna"])

    def shown(group):
        return {row.text(): row.isVisibleTo(rail) for row in rail.facet_group.buttons()
                if row.group == group}

    games = rail.group_headers["games"]
    assert games.count == "2" and games.expanded
    assert shown("games") == {"Apex Legends": True, "The Finals": True}
    games.click()
    assert not games.expanded
    assert shown("games") == {"Apex Legends": False, "The Finals": False}
    assert shown("people") == {"Anna": True}
    # The game the library is filtered by stays in view while its group is folded.
    state.set_facet(Facet("game", "The Finals"))
    assert shown("games") == {"Apex Legends": False, "The Finals": True}
    state.set_facet(Facet("all"))
    assert shown("games") == {"Apex Legends": False, "The Finals": False}
    # Remembered: saved with the settings, and kept when the rail is rebuilt.
    window.context.save_config()
    assert Config.load().rail_collapsed == ["games"]
    rail.rebuild_facets()
    assert not rail.group_headers["games"].expanded
    assert shown("games") == {"Apex Legends": False, "The Finals": False}
    rail.group_headers["games"].click()
    assert shown("games") == {"Apex Legends": True, "The Finals": True}
    assert window.context.config.rail_collapsed == []


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


def test_first_run_adds_the_start_menu_entry(qapp, window):
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
    settings._pick_monitor("DP-2")
    assert texts(settings.resolution) == ["720p · 720 × 1280", "Native · 1080 × 1920"]
    assert settings.video_quality.currentText() == "High · 20 Mbps"
    settings.resolution.setCurrentIndex(settings.resolution.findData("720p"))
    assert "-s 720x1280" in settings.preview.toPlainText()
    assert settings.video_quality.currentText() == "High · 11 Mbps"
    # 11 Mbps of video and three AAC tracks, for a minute.
    assert settings.clip_size.text() == "About 82 MB per clip"
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
    assert "-w DP-1" in " ".join(recorder.argv())

    states, notices = [], []
    recorder.state_changed.connect(lambda state, _error: states.append(state))
    context.notified.connect(notices.append)
    card = window.rail.recorder_card
    recorder.restart_if_running()
    assert card.detail.text() == "Restarting…"
    assert wait_until(qapp, lambda: recorder.phase == "running" and notices)
    # No "Off" or "Starting…" flashing past in between.
    assert states == ["restarting", "running"]
    assert card.detail.text().startswith("On")
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
    assert recorder.phase == "stopped" and card.detail.text() == "Off"


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


def test_unrouted_apps_badge_follows_its_channel(qapp, window, fake_audio):
    from vertex.ui import theme

    window.navigate("sonar")
    view = window.sonar_view
    assert view.unrouted_field.colour == theme.channel_colour("game")
    combo = view.default_channel
    combo.setCurrentIndex(combo.findData("chat"))
    combo.activated.emit(combo.currentIndex())
    assert view.unrouted_field.colour == theme.channel_colour("chat")
    assert wait_until(qapp, lambda: Config.load().sonar.default_channel == "chat")


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
    # Unlinked: each its own.
    view.toggle_link("chat")
    assert wait_until(qapp, lambda: not sonar.linked)
    view.choose_device("media").pick("hw_headset")
    assert wait_until(qapp, lambda: strips["media"].current_device == "hw_headset")
    assert strips["game"].current_device == "hw_speakers"
    assert "own device" in view.subtitle.text()
    # Linking from Media: everything plays through Media's device.
    view.toggle_link("media")
    assert wait_until(qapp, lambda: sonar.linked and all(
        strips[c].current_device == "hw_headset" for c in ("game", "chat", "media")))
    assert Config.load().sonar.output_device == "hw_headset"


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
    assert panel.mode.current == "auto"
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

    # Manual: the device picked stays, whatever the order.
    panel.mode._pick("manual")
    assert wait_until(qapp, lambda: not sonar.output_auto)
    assert "you pick" in panel.mode_hint.text()


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
    assert "and also Speakers" in view.subtitle.text()
    assert Config.load().sonar.second_output == "hw_speakers"

    strips["chat"].also.setChecked(False)                 # Chat stays in the headset
    assert wait_until(qapp, lambda: not view.controller.status.channels["chat"].also)
    assert view.controller.status.channels["game"].also
    assert sonar.channel("chat").also_second is False
    assert "and Game and Media also through Speakers" in view.subtitle.text()

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
    dialog._export()
    assert wait_until(qapp, lambda: bool(dialog.out_path), timeout=60)
    assert os.path.getsize(dialog.out_path) <= 10 * 1024 * 1024
    dialog.reject()


def test_first_run_writes_config(qapp, tmp_path, fake_audio):
    from vertex.ui.main_window import MainWindow
    from vertex.ui.services import Context

    context = Context(Config())
    win = MainWindow(context)
    win.show_setup()
    view = win.first_run
    view.clip_path.set_value(str(tmp_path / "clips"))
    view.sonar_enabled.setChecked(False)
    for _ in range(3):
        view._go(1)
    view._go(1)      # Open Vertex
    assert win.first_run is None
    saved = Config.load()
    assert saved.clip_path == str(tmp_path / "clips")
    assert saved.is_complete()
    assert os.path.isdir(tmp_path / "clips")
    futures.wait([win.start_menu_job], timeout=30)    # see the window fixture
    win._quitting = True
    context.shutdown()


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
    setup.replay_seconds.setCurrentIndex(setup.replay_seconds.findData(120))
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

    # Next device: the other connected output, in Manual mode; then back again.
    fake_audio.add_sink("hw_speakers", props={"device.description": "Speakers"})
    context.sonar.refresh_devices()
    assert wait_until(qapp, lambda: len(context.sonar.outputs) == 2)
    reply = call("device", {"action": "next"})
    assert reply["ok"] and not context.config.sonar.output_auto
    assert wait_until(qapp, lambda: context.sonar.status.output == "hw_speakers")
    call("device", {"action": "next"})
    assert wait_until(qapp, lambda: context.sonar.status.output == "hw_headset")
    assert call("device", {"action": "next", "channel": "mic"})["error"] == "no_device"

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
    assert [t.label for t in editor.tracks] == ["Game", "Chat", "Microphone"]
    assert wait_until(qapp, lambda: editor.position > 0.2, timeout=15)
    assert wait_until(qapp, lambda: len(editor.timeline.waves) == 3, timeout=15)
    editor.rows[-1].slider.setValue(40)
    editor.trim_start, editor.trim_end = 0.5, 2.5
    editor._trim_committed()
    editor._save()
    edit = window.context.library.get_edit(clip.name)
    assert edit.trim_start == 0.5 and edit.mix_for("Vertex Mic").volume == 0.4
    editor._start_trim("copy")
    assert wait_until(qapp, lambda: editor._trim_job is None, timeout=30)
    assert any("(trimmed)" in name for name in os.listdir(os.path.dirname(clip.path)))
    window.navigate("library")
    assert window.editor is None
