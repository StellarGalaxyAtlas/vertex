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
    ("Starfall Arena", 0, ["Sam", "Riley"], "Triple at the last second", True),
    ("Neon Drift", 1, ["Jordan"], "", False),
    ("Starfall Arena", 2, ["Sam"], "Clutch on the bridge", False),
    ("Hollow Keep", 3, ["Alex", "Riley"], "The boss finally fell", True),
    ("Orbit Rush", 4, [], "", False),
    ("Neon Drift", 5, ["Jordan", "Sam"], "Photo finish", False),
    ("Rust Valley", 6, ["Alex"], "", False),
    ("Starfall Arena", 7, ["Riley"], "Ace", False),
    ("Hollow Keep", 8, [], "", False),
    ("Orbit Rush", 9, ["Sam", "Jordan"], "Docked with one hit left", True),
    ("Rust Valley", 10, [], "", False),
    ("Neon Drift", 11, ["Alex"], "", False),
    ("Starfall Arena", 12, ["Sam", "Riley", "Jordan"], "Team wipe", False),
    ("Hollow Keep", 13, ["Riley"], "", False),
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


# Color sets for the made-up footage: two for the backdrop, three for shapes.
PALETTES = (
    ("1b1f4b", "3a1c71", "ffaf7b", "d76d77", "4ecdc4"),
    ("0f2027", "2c5364", "f7b733", "fc4a1a", "e0e0e0"),
    ("232526", "414345", "00d2ff", "928dab", "ff6b6b"),
    ("142850", "27496d", "00909e", "dae1e7", "f4a261"),
    ("2d1b3d", "6a2c70", "f08a5d", "f9ed69", "3ec1d3"),
    ("10302f", "1e5945", "a8e6cf", "ffd3b6", "ff8b94"),
    ("1a1a2e", "16213e", "e94560", "0f3460", "f5f5f5"),
)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def geometry(look: int) -> str:
    """An ffmpeg geq filter drawing slowly moving abstract shapes: a big
    circle, a diagonal band and a square over a gradient."""
    back1, back2, circle, band, square = map(_rgb, PALETTES[look % len(PALETTES)])
    flip = "W-X" if look % 2 else "X"
    cx, cy = f"(W*(0.3+0.08*{look % 3})+W*0.06*sin(T*0.5+{look}))", "(H*0.5+H*0.08*cos(T*0.4))"
    shapes = (
        (circle, f"lte(hypot(X-{cx},Y-{cy}),H*{0.2 + 0.06 * (look % 3)})"),
        (band, f"lte(abs(({flip})-Y*{0.4 + 0.3 * (look % 3)}-W*0.5-W*0.03*sin(T*0.3)),"
                f"W*{0.03 + 0.02 * (look % 2)})"),
        (square, f"lte(abs(X-W*{0.8 - 0.12 * (look % 2)}),H*0.12)"
                  f"*lte(abs(Y-H*(0.3+0.05*sin(T*0.6+{look}))),H*0.12)"),
    )

    def channel(k: int) -> str:
        expr = f"{back1[k]}+({back2[k]}-{back1[k]})*(X+Y)/(W+H)"
        for color, inside in reversed(shapes):
            expr = f"if({inside},{color[k]},{expr})"
        return expr

    return f"geq=r='{channel(0)}':g='{channel(1)}':b='{channel(2)}'"


def make_clip(path: str, look: int, seconds: int) -> None:
    # Tones that swell and fade, so every lane has a waveform worth seeing:
    # Game, Chat and Mic, the three tracks Vertex records.
    tones = ((220, 0.7, 0.0), (330, 1.9, 1.0), (550, 1.3, 0.5))
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
           "-i", f"color=black:size=480x270:rate=10,{geometry(look)},"
           "scale=1280:720:flags=bicubic,fps=30"]
    for freq, speed, phase in tones:
        expr = f"0.8*sin(2*PI*{freq}*t)*pow(abs(sin({speed}*t+{phase})),3)"
        cmd += ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={seconds}"]
    cmd += ["-map", "0:v"] + [x for i in range(3) for x in ("-map", f"{i + 1}:a")]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
            "-c:a", "aac", "-t", str(seconds)]
    for i, name in enumerate(("Vertex Game", "Vertex Chat", "Vertex Mic")):
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
    for i, (game, look, people, title, favorite) in enumerate(CLIPS):
        when = now - 3600 * (5 + i * 19)
        stamp = time.strftime("%Y-%m-%d__%H-%M-%S", time.localtime(when))
        name = f"{game.replace(' ', '-')}__{stamp}.mp4"
        path = f"{clips}/{name}"
        make_clip(path, look, 6 + (i * 7) % 25)
        os.utime(path, (when, when))
        library.set_tags(name, game, people)
        if title:
            library.set_title(name, title)
        if favorite:
            library.set_favorite(name, True)
        if game == "Hollow Keep" and title:
            # The editor's shot: a selection, and a too-loud mic turned down.
            library.set_trim(name, 4.0, 22.0)
            library.set_volumes(name, {"Vertex Mic": {"volume": 0.45, "muted": False},
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

    def editor():
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

    steps = [
        (play, None),
        (lambda: window.navigate("home"), "home"),
        (lambda: window.navigate("library"), "library"),
        (editor, "editor"),
        (export, None),
        (lambda: window.navigate("sonar"), "sonar"),
        (settings_page("general"), "settings-general"),
        (settings_page("recording"), "settings-recording"),
        (settings_page("notifications"), "settings-notifications"),
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
