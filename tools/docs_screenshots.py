"""Take the screenshots in docs/screenshots/ from a made-up demo library.

usage: xvfb-run -a python tools/docs_screenshots.py OUT_DIR [WIDTH HEIGHT]

Loads vertex from this checkout's src/. Builds a throwaway HOME with a demo
library (generated test-pattern clips with four audio tracks, made-up games
and people), a fake audio server, a stand-in GPU Screen Recorder and three
fake monitors, then saves one PNG per page into OUT_DIR. The window is
1440×900 unless a size is given. Never touches your real config, library or
audio devices.
"""

import dataclasses
import json
import os
import stat
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.abspath(__file__))

# Made-up games and people: (game, pattern, people, title, favorite).
CLIPS = (
    ("Starfall Arena", "testsrc2", ["Sam", "Riley"], "Triple at the last second", True),
    ("Neon Drift", "mandelbrot", ["Jordan"], "", False),
    ("Starfall Arena", "smptehdbars", ["Sam"], "Clutch on the bridge", False),
    ("Hollow Keep", "cellauto", ["Alex", "Riley"], "The boss finally fell", True),
    ("Orbit Rush", "rgbtestsrc", [], "", False),
    ("Neon Drift", "testsrc", ["Jordan", "Sam"], "Photo finish", False),
    ("Rust Valley", "life", ["Alex"], "", False),
    ("Starfall Arena", "mandelbrot", ["Riley"], "Ace", False),
    ("Hollow Keep", "testsrc2", [], "", False),
    ("Orbit Rush", "smptebars", ["Sam", "Jordan"], "Docked with one hit left", True),
    ("Rust Valley", "cellauto", [], "", False),
    ("Neon Drift", "rgbtestsrc", ["Alex"], "", False),
    ("Starfall Arena", "testsrc", ["Sam", "Riley", "Jordan"], "Team wipe", False),
    ("Hollow Keep", "life", ["Riley"], "", False),
)

CAPTURE_OPTIONS = "DP-1|2560x1440\nDP-2|1080x1920\nHDMI-A-1|1920x1080\nregion\nportal\n"

FAKE_GSR = '''#!{python}
import signal, sys, time
args = sys.argv[1:]
if args == ["--version"]:
    print("5.15.1"); sys.exit(0)
if args == ["--list-audio-devices"]:
    print("default_output|Default output"); print("default_input|Default input")
    for name in ("Game", "Chat", "Media"):
        print(f"vertex_{{name.lower()}}.monitor|Monitor of Vertex {{name}}")
    print("vertex_mic|Vertex Mic"); sys.exit(0)
if args == ["--list-capture-options"]:
    print({options!r}, end=""); sys.exit(0)
signal.signal(signal.SIGINT, lambda *a: sys.exit(0))
while True:
    time.sleep(0.2)
'''

HEADSET_OUT = "alsa_output.usb-SteelSeries_Arctis_Nova_Pro"
HEADSET_IN = "alsa_input.usb-Elgato_Wave_3"
OUTPUTS = ((HEADSET_OUT, "Arctis Nova Pro Wireless"),
           ("alsa_output.pci-0000_00_1f.3.analog-stereo", "Built-in Audio"),
           ("alsa_output.pci-0000_01_00.1.hdmi-stereo", "HDMI Audio"))
INPUTS = ((HEADSET_IN, "Elgato Wave:3"),
          ("alsa_input.usb-SteelSeries_Arctis_Nova_Pro", "Arctis Nova Pro Wireless"),
          ("alsa_input.usb-046d_HD_Pro_Webcam_C920", "HD Pro Webcam C920"))


def make_clip(path: str, pattern: str, seconds: int) -> None:
    # Tones that swell and fade, so every lane has a waveform worth seeing.
    tones = ((220, 0.7, 0.0), (330, 1.9, 1.0), (550, 0.4, 2.0), (880, 1.3, 0.5))
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
           "-i", f"{pattern}=size=1280x720:rate=30"]
    for freq, speed, phase in tones:
        expr = f"0.8*sin(2*PI*{freq}*t)*pow(abs(sin({speed}*t+{phase})),3)"
        cmd += ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={seconds}"]
    cmd += ["-map", "0:v"] + [x for i in range(4) for x in ("-map", f"{i + 1}:a")]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
            "-c:a", "aac", "-t", str(seconds)]
    for i, name in enumerate(("Vertex Game", "Vertex Chat", "Vertex Media", "Vertex Mic")):
        cmd += [f"-metadata:s:a:{i}", f"title={name}"]
    subprocess.run([*cmd, path], check=True)


def isolate() -> str:
    home = tempfile.mkdtemp(prefix="docs-shot-")
    os.environ.update(HOME=home, XDG_CONFIG_HOME=f"{home}/.config",
                      XDG_DATA_HOME=f"{home}/.local/share", XDG_STATE_HOME=f"{home}/.local/state",
                      XDG_CACHE_HOME=f"{home}/.cache", XDG_RUNTIME_DIR=home)
    os.makedirs(f"{home}/.config/vertex")
    clips = f"{home}/Videos/Clips"
    os.makedirs(clips)
    gsr = f"{home}/gpu-screen-recorder"
    with open(gsr, "w") as file:
        file.write(FAKE_GSR.format(python=sys.executable, options=CAPTURE_OPTIONS))
    os.chmod(gsr, os.stat(gsr).st_mode | stat.S_IEXEC)
    config = {
        "clip_path": clips,
        "export_path": f"{home}/Videos/Exports",
        "sonar": {"enabled": True, "output_device": HEADSET_OUT, "mic_device": HEADSET_IN,
                  "app_rules": {"spotify": "media", "discord": "chat", "firefox": "media"},
                  "channels": {"game": {"volume": 0.85}, "chat": {"volume": 0.7},
                               "media": {"volume": 0.4}, "mic": {"volume": 0.9}}},
        "recorder": {"command": gsr, "capture": "DP-1", "autostart": True},
    }
    with open(f"{home}/.config/vertex/config.json", "w") as file:
        json.dump(config, file)
    return home


def build_library(home: str) -> None:
    from vertex.library.database import Library

    clips = f"{home}/Videos/Clips"
    library = Library(f"{home}/.local/share/vertex")
    now = time.time()
    for i, (game, pattern, people, title, favorite) in enumerate(CLIPS):
        when = now - 3600 * (5 + i * 19)
        stamp = time.strftime("%Y-%m-%d__%H-%M-%S", time.localtime(when))
        name = f"{game.replace(' ', '-')}__{stamp}.mp4"
        path = f"{clips}/{name}"
        make_clip(path, pattern, 6 + (i * 7) % 25)
        os.utime(path, (when, when))
        library.set_tags(name, game, people)
        if title:
            library.set_title(name, title)
        if favorite:
            library.set_favorite(name, True)
        if game == "Hollow Keep" and title:
            # The editor's shot: a selection, and the music turned down.
            library.set_trim(name, 4.0, 22.0)
            library.set_volumes(name, {"Vertex Media": {"volume": 0.35, "muted": False},
                                       "Vertex Chat": {"volume": 1.2, "muted": False}})
    library.close()


def fakes():
    from vertex.recorder import gsr, monitors
    from vertex.ui import screens

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
    gsr.list_capture_options = lambda command: gsr.parse_capture_options(CAPTURE_OPTIONS)
    screens.desktop_screens = lambda: [
        monitors.Screen("HDMI-A-1", -1920, 360, 1920, 1080, "LG ULTRAGEAR", (1920, 1080)),
        monitors.Screen("DP-1", 0, 240, 2560, 1440, "DELL S2721DGF", (2560, 1440),
                        primary=True),
        monitors.Screen("DP-2", 2560, 0, 1080, 1920, "AOC 24G2W1G4", (1080, 1920)),
    ]
    return fake


def main(out: str, size: tuple[int, int]) -> int:
    sys.path[:0] = [os.path.join(REPO, "src"), os.path.join(REPO, "tests")]
    os.makedirs(out, exist_ok=True)
    home = isolate()
    import vertex
    assert vertex.__file__.startswith(os.path.join(REPO, "src")), vertex.__file__
    build_library(home)
    fake = fakes()
    import vertex.ui.services as services
    services.Pactl = lambda: fake

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog

    from vertex.config import Config
    from vertex.ui import app as app_mod
    from vertex.ui.library.state import Facet
    from vertex.ui.main_window import MainWindow

    qt = app_mod._create_app()
    context = services.Context(Config.load())
    window = MainWindow(context)
    window.start_services()
    window.resize(*size)
    window.show()
    settings = window.settings_view

    def play():
        fake.play("Starfall Arena", binary="starfall.exe")
        fake.play("Spotify")
        fake.play("Discord", binary="Discord")
        fake.play("Firefox")
        fake.record("Discord", "vertex_mic", binary="Discord")
        context.sonar.refresh_streams()
        context.sonar.refresh_devices()

    def save(name, widget=None):
        window.banner.clear()
        (widget or window).grab().save(os.path.join(out, f"{name}.png"))
        print("saved", name)

    def dialog_shot(name):
        def grab():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QDialog) and widget.isVisible():
                    save(name, widget)
                    widget.reject()
        return grab

    def library_game():
        window.navigate("library")
        window.state.set_facet(Facet("game", "Starfall Arena"))

    def library_search():
        window.state.set_facet(Facet())
        window.state.set_query("neon")

    def editor():
        window.state.set_query("")
        clip = next(c for c in window.state.visible if "Hollow" in c.path)
        window.open_clip(clip)

    def export():
        QTimer.singleShot(1200, dialog_shot("export"))
        window.editor.start_export()

    def settings_page(key):
        def go():
            window.navigate("settings")
            settings.show_page(key)
        return go

    def device_manager():
        window.navigate("sonar")
        save("sonar-devices", window.sonar_view.manager)

    steps = [
        (play, None),
        (lambda: window.navigate("home"), "home"),
        (lambda: window.navigate("library"), "library"),
        (library_game, "library-game"),
        (library_search, "library-search"),
        (editor, "editor"),
        (export, None),
        (lambda: window.navigate("sonar"), "sonar"),
        (device_manager, None),
        (settings_page("general"), "settings-general"),
        (settings_page("recording"), "settings-recording"),
        (settings_page("notifications"), "settings-notifications"),
        (settings_page("shortcuts"), "settings-shortcuts"),
    ]

    def run(i=0):
        if i == len(steps):
            window.close()
            qt.quit()
            return
        action, name = steps[i]
        action()

        def after():
            if name:
                save(name)
            run(i + 1)
        QTimer.singleShot(6000 if name == "editor" else 1800, after)

    QTimer.singleShot(2500, run)
    QTimer.singleShot(120000, lambda: (print("timed out"), qt.exit(1)))
    qt.aboutToQuit.connect(context.shutdown)
    return qt.exec()


if __name__ == "__main__":
    if len(sys.argv) not in (2, 4):
        sys.exit(__doc__)
    size = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) == 4 else (1440, 900)
    sys.exit(main(sys.argv[1], size))
