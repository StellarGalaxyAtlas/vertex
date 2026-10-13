"""Smoke tests for the Qt UI: every page builds, and the main flows work.

Runs with the offscreen platform. The editor needs OpenGL for video, so its
test only runs with a display (CI runs the suite under xvfb-run).
"""

import ctypes.util
import os
import shutil
import time

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


def test_pages_and_settings_save(qapp, window):
    for page in ("sonar", "settings", "library"):
        window.navigate(page)
        qapp.processEvents()
    settings = window.settings_view
    settings.load()
    settings.replay_seconds.setValue(45)
    assert settings.is_dirty()
    assert settings.save()
    assert Config.load().recorder.replay_seconds == 45
    assert not settings.is_dirty()
    settings.show_page("recording")
    assert "-r 45" in settings.preview.toPlainText()


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
    assert view.mic_field.colour == theme.channel_colour("mic")
    combo = view.default_channel
    combo.setCurrentIndex(combo.findData("chat"))
    combo.activated.emit(combo.currentIndex())
    assert view.unrouted_field.colour == theme.channel_colour("chat")
    assert wait_until(qapp, lambda: Config.load().sonar.default_channel == "chat")


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
    win._quitting = True
    context.shutdown()


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
