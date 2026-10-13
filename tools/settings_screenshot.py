"""Screenshot Settings › Recording against a fake recorder and fake monitors.

usage: xvfb-run -a python tools/settings_screenshot.py OUT_PREFIX [WIDTH ...]

Loads vertex from this checkout's src/ (so a worktree's version is used, not
whatever is installed). GPU Screen Recorder and the desktop's monitors are
stood in for: a 2560×1440 monitor in the middle, a 1080×1920 one standing up on
its right and a 1920×1080 one on its left. Saves OUT_PREFIX-<width>.png (the
whole window) and OUT_PREFIX-<width>-section.png (the section with the monitor
map) for each width: by default 1280 (the default window) and 980 (the
minimum). Never touches your real config.
"""

import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CAPTURE_OPTIONS = """\
DP-1|2560x1440
DP-2|1080x1920
HDMI-A-1|1920x1080
region
/dev/video0|1920x1080@30hz|mjpeg
/dev/video0|1280x720@30hz|yuyv
portal
"""


def isolate() -> str:
    """A throwaway HOME with a config that records DP-1."""
    home = tempfile.mkdtemp(prefix="settings-shot-")
    os.environ.update(HOME=home, XDG_CONFIG_HOME=f"{home}/.config",
                      XDG_DATA_HOME=f"{home}/.local/share", XDG_STATE_HOME=f"{home}/.local/state",
                      XDG_CACHE_HOME=f"{home}/.cache", XDG_RUNTIME_DIR=home)
    os.makedirs(f"{home}/.config/vertex")
    os.makedirs(f"{home}/clips")
    config = {
        "clip_path": f"{home}/clips",
        "export_path": f"{home}/exports",
        "recorder": {"command": "gpu-screen-recorder", "capture": "DP-1"},
    }
    with open(f"{home}/.config/vertex/config.json", "w") as file:
        json.dump(config, file)
    return home


def fake_recorder_and_monitors() -> None:
    from vertex.recorder import gsr, monitors
    from vertex.ui import screens

    gsr.detect = lambda command: gsr.GsrInfo(command, True, (5, 15, 1), "5.15.1")
    gsr.list_capture_options = lambda command: gsr.parse_capture_options(CAPTURE_OPTIONS)
    gsr.list_audio_devices = lambda command: [
        ("default_output", "Default output"), ("default_input", "Default input"),
        ("vertex_game.monitor", "Monitor of Vertex Game"),
        ("vertex_chat.monitor", "Monitor of Vertex Chat"),
        ("vertex_media.monitor", "Monitor of Vertex Media"),
        ("vertex_aux.monitor", "Monitor of Vertex Aux"), ("vertex_mic", "Vertex Mic"),
        ("alsa_output.usb-headset.monitor", "Monitor of Arctis Nova Pro Wireless"),
        ("alsa_input.usb-headset", "Arctis Nova Pro Wireless Mono")]
    screens.desktop_screens = lambda: [
        monitors.Screen("HDMI-A-1", -1920, 360, 1920, 1080, "LG ULTRAGEAR", (1920, 1080)),
        monitors.Screen("DP-1", 0, 240, 2560, 1440, "DELL S2721DGF", (2560, 1440),
                        primary=True),
        monitors.Screen("DP-2", 2560, 0, 1080, 1920, "AOC 24G2W1G4", (1080, 1920)),
    ]


def main(prefix: str, widths: list[int]) -> int:
    sys.path[:0] = [os.path.join(REPO, "src"), os.path.join(REPO, "tests")]
    isolate()
    import vertex
    assert vertex.__file__.startswith(os.path.join(REPO, "src")), vertex.__file__

    import vertex.ui.services as services

    from fake_pactl import FakePactl
    fake = FakePactl(sinks=("hw_headset",), sources=("hw_mic",))
    services.Pactl = lambda: fake
    fake_recorder_and_monitors()

    from PySide6.QtCore import QTimer

    from vertex.config import Config
    from vertex.ui import app as app_mod
    from vertex.ui.main_window import MainWindow

    qt = app_mod._create_app()
    context = services.Context(Config.load())
    window = MainWindow(context)
    window.start_services()
    window.navigate("settings")
    settings = window.settings_view
    settings.show_page("recording")
    window.resize(widths[0], 860)
    window.show()
    section = settings.monitor_map.parentWidget()

    def shoot(i=0):
        if i == len(widths):
            window.close()
            qt.quit()
            return
        window.resize(widths[i], 860)

        def grab():
            settings.pages["recording"].verticalScrollBar().setValue(section.y())
            window.grab().save(f"{prefix}-{widths[i]}.png")
            section.grab().save(f"{prefix}-{widths[i]}-section.png")
            print("saved", f"{prefix}-{widths[i]}.png")
            shoot(i + 1)
        QTimer.singleShot(600, grab)

    QTimer.singleShot(1500, shoot)
    QTimer.singleShot(20000, lambda: (print("timed out"), qt.exit(1)))
    qt.aboutToQuit.connect(context.shutdown)
    return qt.exec()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], [int(w) for w in sys.argv[2:]] or [1280, 980]))
