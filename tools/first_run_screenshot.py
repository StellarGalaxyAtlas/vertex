"""Screenshot every step of first-run setup against fake devices, for UI work.

usage: xvfb-run -a python tools/first_run_screenshot.py OUT_PREFIX [WIDTH ...]

Loads vertex from this checkout's src/ (so a worktree's version is used, not
whatever is installed) and saves OUT_PREFIX-<width>-<step>.png for each step
and width: by default 1280 × 820 (the default window) and 980 × 640 (the
minimum). The Moments step is shot twice: with no GPU Screen Recorder
("moments-missing") and with the stand-in recorder and three monitors of
tools/settings_screenshot.py. The last two steps bring along a fake
SteelSeries Moments library. Needs no audio server and never touches your real
config.
"""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(REPO, "tools")]

CLIPS = ("THE-FINALS__2024-06-16__19-45-23.mp4", "THE-FINALS__2024-06-17__20-00-00.mp4",
         "Apex-Legends__2026-08-11__22-14-07.mp4", "Deep-Rock-Galactic__2025-02-01__21-10-44.mp4",
         "Replay_2026-03-28_05-28-25.mp4")


def isolate() -> str:
    home = tempfile.mkdtemp(prefix="first-run-shot-")
    os.environ.update(HOME=home, XDG_CONFIG_HOME=f"{home}/.config",
                      XDG_DATA_HOME=f"{home}/.local/share", XDG_STATE_HOME=f"{home}/.local/state",
                      XDG_CACHE_HOME=f"{home}/.cache", XDG_RUNTIME_DIR=home)
    os.makedirs(f"{home}/Moments")
    for name in CLIPS:
        with open(f"{home}/Moments/{name}", "wb") as handle:
            handle.write(b"clip")
    return home


def main(prefix: str, widths: list[int]) -> int:
    sys.path[:0] = [os.path.join(REPO, "src"), os.path.join(REPO, "tests")]
    home = isolate()
    import vertex
    assert vertex.__file__.startswith(os.path.join(REPO, "src")), vertex.__file__

    from settings_screenshot import fake_recorder_and_monitors
    from sonar_screenshot import fake_server

    import vertex.ui.services as services

    fake = fake_server()
    services.Pactl = lambda: fake
    from vertex.recorder import gsr
    real_detect = gsr.detect
    fake_recorder_and_monitors()
    fake_detect = gsr.detect
    found = [False]
    # The stand-in recorder answers only once "installed".
    gsr.detect = lambda command: fake_detect(command) if found[0] else real_detect(command)
    # Its notifier too.
    from vertex.recorder import notifier
    notifier.find = lambda: "/usr/bin/gsr-notify" if found[0] else None

    from PySide6.QtCore import QTimer

    from vertex.config import Config
    from vertex.ui import app as app_mod
    from vertex.ui.main_window import MainWindow

    qt = app_mod._create_app()
    context = services.Context(Config())
    window = MainWindow(context)
    config = Config()
    config.recorder.command = f"{home}/no-gsr"
    window.show_setup(config)
    view = window.first_run
    window.show()

    shots = []
    for width in widths:
        height = 820 if width >= 1280 else 640
        shots += [(width, height, step) for step in
                  ("folders", "sonar", "moments-missing", "moments", "library", "tags")]

    def prepare(step):
        if step in ("moments-missing", "moments"):
            found[0] = step == "moments"
            view._find_recorder()
            view._show("moments")
        elif step == "library":
            view.existing.choose()
            view.source.set_value(f"{home}/Moments")
            view._show("library")
        else:
            view._show(step)

    def shoot(i=0):
        if i == len(shots):
            window.close()
            qt.quit()
            return
        width, height, step = shots[i]
        window.resize(width, height)
        prepare(step)

        def grab():
            path = f"{prefix}-{width}-{step}.png"
            window.grab().save(path)
            print("saved", path)
            shoot(i + 1)
        QTimer.singleShot(900, grab)

    QTimer.singleShot(1200, shoot)
    QTimer.singleShot(60000, lambda: (print("timed out"), qt.exit(1)))
    window._quitting = True
    qt.aboutToQuit.connect(context.shutdown)
    return qt.exec()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], [int(w) for w in sys.argv[2:]] or [1280, 980]))
