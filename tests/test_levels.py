"""The live levels behind Sonar's meters."""

import array
import os
import stat
import sys
import time

from vertex.audio import levels


def test_peaks_and_the_meter_scale():
    loud = array.array("h", [0, 16384, -32768, 100]).tobytes()
    assert levels.peak_of(loud) == 1.0
    assert levels.peak_of(array.array("h", [0, -8192]).tobytes()) == 0.25
    assert levels.peak_of(b"") == 0.0
    assert levels.meter_fraction(0.0) == 0.0
    assert levels.meter_fraction(1.0) == 1.0
    assert levels.meter_fraction(0.001) == 0.0             # -60 dB, the bottom
    assert abs(levels.meter_fraction(0.1) - 2 / 3) < 1e-9   # -20 dB


def test_a_meter_reads_its_device_through_parec(tmp_path, monkeypatch):
    # A parec that plays a loud block forever, and notes how it was started.
    fake = tmp_path / "parec"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import array, sys, time\n"
        f"open({str(tmp_path / 'args')!r}, 'w').write(' '.join(sys.argv[1:]))\n"
        "block = array.array('h', [0, 16384] * 160).tobytes()\n"
        "while True:\n"
        "    sys.stdout.buffer.write(block); sys.stdout.flush(); time.sleep(0.04)\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    meters = levels.Levels()
    assert meters.start({"game": "vertex_game.monitor"})
    try:
        deadline = time.monotonic() + 5
        peak = 0.0
        while time.monotonic() < deadline and not peak:
            time.sleep(0.05)
            peak = meters.take()["game"]
        assert peak == 0.5
        args = (tmp_path / "args").read_text()
        # A meter, never moved, so Sonar doesn't list it as an app recording.
        assert "--stream-name=Peak detect" in args and "--no-move" in args
        assert args.endswith("-d vertex_game.monitor")
    finally:
        meters.stop()
    assert meters.take() == {}


def test_no_parec_means_no_levels(monkeypatch):
    monkeypatch.setattr(levels.shutil, "which", lambda _name: None)
    meters = levels.Levels()
    assert not meters.start({"game": "vertex_game.monitor"})
    assert meters.take() == {}
