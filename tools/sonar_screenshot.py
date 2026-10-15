"""Screenshot the Sonar page against a fake audio server, for UI work.

usage: xvfb-run -a python tools/sonar_screenshot.py OUT_PREFIX [WIDTH ...]

Loads vertex from this checkout's src/ (so a worktree's version is used, not
whatever is installed), plays a few fake apps, and saves OUT_PREFIX-<width>.png
(the whole window) and OUT_PREFIX-<width>-manager.png (the device manager)
for each width: by default 1280 (the default window) and 980 (the minimum).
Needs no audio server and never touches your real config.
"""

import dataclasses
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADSET_OUT = "alsa_output.usb-SteelSeries_Arctis_Nova_Pro"
HEADSET_IN = "alsa_input.usb-SteelSeries_Arctis_Nova_Pro"
OUTPUTS = (
    (HEADSET_OUT, "Arctis Nova Pro Wireless Analog Stereo"),
    ("alsa_output.pci-0000_00_1f.3.analog-stereo", "Built-in Audio Analog Stereo"),
    ("alsa_output.pci-0000_01_00.1.hdmi-stereo", "GA104 High Definition Audio Controller HDMI"),
)
INPUTS = (
    (HEADSET_IN, "Arctis Nova Pro Wireless Mono"),
    ("alsa_input.usb-046d_HD_Pro_Webcam_C920", "HD Pro Webcam C920 Analog Stereo"),
)


def isolate() -> str:
    """A throwaway HOME with a config that has Sonar on."""
    home = tempfile.mkdtemp(prefix="sonar-shot-")
    os.environ.update(HOME=home, XDG_CONFIG_HOME=f"{home}/.config",
                      XDG_DATA_HOME=f"{home}/.local/share", XDG_STATE_HOME=f"{home}/.local/state",
                      XDG_CACHE_HOME=f"{home}/.cache", XDG_RUNTIME_DIR=home)
    os.makedirs(f"{home}/.config/vertex")
    os.makedirs(f"{home}/clips")
    config = {
        "clip_path": f"{home}/clips",
        "export_path": f"{home}/exports",
        "sonar": {"enabled": True, "output_device": HEADSET_OUT, "mic_device": HEADSET_IN,
                  "app_rules": {"spotify": "media", "discord": "chat"}},
        "recorder": {"command": f"{home}/no-gsr"},
    }
    with open(f"{home}/.config/vertex/config.json", "w") as file:
        json.dump(config, file)
    return home


def fake_server():
    from fake_pactl import FakePactl

    fake = FakePactl(sinks=(), sources=())
    for name, description in OUTPUTS:
        fake.add_sink(name, props={"device.description": description})
    for name, description in INPUTS:
        source = fake.add_source(name)
        fake.sources_[fake.sources_.index(source)] = dataclasses.replace(
            source, description=description)
    fake.default_sink_ = HEADSET_OUT
    fake.default_source_ = HEADSET_IN
    return fake


def main(prefix: str, widths: list[int]) -> int:
    sys.path[:0] = [os.path.join(REPO, "src"), os.path.join(REPO, "tests")]
    isolate()
    import vertex
    assert vertex.__file__.startswith(os.path.join(REPO, "src")), vertex.__file__

    fake = fake_server()
    import vertex.ui.services as services
    services.Pactl = lambda: fake

    from PySide6.QtCore import QTimer

    from vertex.config import Config
    from vertex.ui import app as app_mod
    from vertex.ui.main_window import MainWindow

    qt = app_mod._create_app()
    context = services.Context(Config.load())
    window = MainWindow(context)
    window.start_services()
    window.navigate("sonar")
    window.resize(widths[0], 860)
    window.show()

    def play():
        fake.play("Deep Rock Galactic", binary="FSD-Win64-Shipping.exe")
        fake.play("Spotify")
        fake.play("Discord", binary="Discord")
        fake.play("Firefox")
        fake.record("Discord", "vertex_mic", binary="Discord")
        context.sonar.refresh_streams()
        context.sonar.refresh_devices()

    def shoot(i=0):
        if i == len(widths):
            window.close()
            qt.quit()
            return
        window.resize(widths[i], 860)

        def grab():
            window.grab().save(f"{prefix}-{widths[i]}.png")
            window.sonar_view.manager.grab().save(f"{prefix}-{widths[i]}-manager.png")
            print("saved", f"{prefix}-{widths[i]}.png")
            shoot(i + 1)
        QTimer.singleShot(600, grab)

    QTimer.singleShot(800, play)
    QTimer.singleShot(2500, shoot)
    QTimer.singleShot(20000, lambda: (print("timed out"), qt.exit(1)))
    qt.aboutToQuit.connect(context.shutdown)
    return qt.exec()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], [int(w) for w in sys.argv[2:]] or [1280, 980]))
